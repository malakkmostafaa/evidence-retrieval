"""Block 0 - environment check (read-only, changes nothing on disk except a temp file).

Run from the repo root:   python scripts/check_env.py --data-dir "D:\\averitec\\dev300_zips"
Every check prints PASS / WARN / FAIL. Save the full output as docs/env_report.txt for the thesis.
"""
import argparse
import json
import os
import platform
import shutil
import sys
import tempfile
import time

RESULTS = []


def report(name, status, detail=""):
    RESULTS.append({"check": name, "status": status, "detail": detail})
    print(f"[{status:4}] {name}: {detail}")


def check_python():
    v = sys.version_info
    ok = (v.major, v.minor) in [(3, 10), (3, 11), (3, 12)]
    report("python", "PASS" if ok else "WARN", f"{platform.python_version()} at {sys.executable}")
    report("os", "PASS", f"{platform.system()} {platform.release()} ({platform.machine()})")
    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix) or "CONDA_PREFIX" in os.environ
    report("isolated environment", "PASS" if in_venv else "WARN",
           "venv/conda active" if in_venv else "running in the global Python - create a venv first")


def check_encoding():
    # Windows often defaults to cp1252; scraped text contains Arabic, emoji, U+2028.
    report("default file encoding", "PASS" if sys.flags.utf8_mode else "WARN",
           f"utf8_mode={sys.flags.utf8_mode}; always pass encoding='utf-8' when opening files "
           "(or set PYTHONUTF8=1)")
    sample = "Arabic \u0645\u0631\u062d\u0628\u0627 | emoji \U0001F600 | line sep \u2028 | caf\u00e9"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".txt") as f:
        f.write(sample)
        path = f.name
    with open(path, encoding="utf-8") as f:
        back = f.read()
    os.remove(path)
    report("utf-8 round trip", "PASS" if back == sample else "FAIL", "text with Arabic/emoji/U+2028 survives write+read")


def check_resources(data_dir):
    try:
        import psutil
        ram = psutil.virtual_memory()
        report("RAM", "PASS" if ram.total >= 15e9 else "WARN",
               f"total {ram.total / 1e9:.1f} GB, available now {ram.available / 1e9:.1f} GB")
    except ImportError:
        report("RAM", "WARN", "psutil not installed (pip install psutil)")
    target = data_dir if data_dir and os.path.isdir(data_dir) else os.getcwd()
    du = shutil.disk_usage(target)
    report("disk free", "PASS" if du.free >= 40e9 else "WARN", f"{du.free / 1e9:.1f} GB free on the drive of {target}")
    if data_dir:
        if not os.path.isdir(data_dir):
            report("data dir", "FAIL", f"{data_dir} not found")
            return
        zips = sorted(n for n in os.listdir(data_dir) if n.lower().endswith(".zip"))
        total = sum(os.path.getsize(os.path.join(data_dir, n)) for n in zips)
        report("data dir", "PASS" if len(zips) == 8 else "WARN",
               f"{len(zips)} zip files, {total / 1e9:.2f} GB: {zips}")


def check_gpu():
    try:
        import torch
    except ImportError:
        report("torch", "FAIL", "PyTorch not installed - see install step 4")
        return None
    report("torch", "PASS", f"{torch.__version__} (built for CUDA {torch.version.cuda})")
    if not torch.cuda.is_available():
        report("cuda available", "FAIL",
               "False - either the CPU-only wheel is installed or the NVIDIA driver is missing (run nvidia-smi)")
        return torch
    p = torch.cuda.get_device_properties(0)
    report("gpu", "PASS", f"{p.name}, {p.total_memory / 1e9:.1f} GB VRAM")
    # Correctness, not just 'it runs': the same matrix product on GPU and CPU must agree.
    g = torch.Generator().manual_seed(0)
    a = torch.randn(1024, 1024, generator=g)
    b = torch.randn(1024, 1024, generator=g)
    cpu = a @ b
    gpu = (a.cuda() @ b.cuda()).cpu()
    rel = ((cpu - gpu).norm() / cpu.norm()).item()
    report("gpu matmul agrees with cpu", "PASS" if rel < 1e-3 else "FAIL", f"relative difference {rel:.2e}")
    return torch


def check_embedding(torch):
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        report("embedding model", "WARN", "sentence-transformers not installed - skipped")
        return
    name = "BAAI/bge-small-en-v1.5"  # used only to test the GPU path; NOT a model choice
    texts = ["The unemployment rate fell to 3.5 percent in September.",
             "Joblessness dropped to 3.5% last September.",
             "The recipe needs two cups of flour and an egg."]
    t0 = time.time()
    m_cpu = SentenceTransformer(name, device="cpu")
    e_cpu = m_cpu.encode(texts, normalize_embeddings=True, convert_to_tensor=True)
    sim_para = float(e_cpu[0] @ e_cpu[1])
    sim_unrel = float(e_cpu[0] @ e_cpu[2])
    report("embedding semantics", "PASS" if sim_para > sim_unrel + 0.1 else "FAIL",
           f"cos(paraphrase)={sim_para:.3f} > cos(unrelated)={sim_unrel:.3f}")
    if torch is not None and torch.cuda.is_available():
        m_gpu = SentenceTransformer(name, device="cuda")
        e_gpu = m_gpu.encode(texts, normalize_embeddings=True, convert_to_tensor=True).cpu()
        agree = float((e_cpu.cpu() * e_gpu).sum(dim=1).min())
        report("embedding gpu == cpu", "PASS" if agree > 0.999 else "FAIL", f"min cosine(cpu, gpu) = {agree:.6f}")
        batch = ["word " * 150] * 512
        torch.cuda.reset_peak_memory_stats()
        t1 = time.time()
        m_gpu.encode(batch, batch_size=64)
        dt = time.time() - t1
        report("embedding throughput (rough)", "PASS",
               f"{len(batch) / dt:.0f} passages/s at ~150 words, peak VRAM "
               f"{torch.cuda.max_memory_allocated() / 1e9:.2f} GB (first-run warm-up included)")
    report("embedding total time", "PASS", f"{time.time() - t0:.1f} s incl. model download")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=None, help="folder with the 8 dev300 zip parts")
    ap.add_argument("--skip-embedding", action="store_true")
    ap.add_argument("--out", default=None, help="optional JSON file for the results")
    args = ap.parse_args()
    check_python()
    check_encoding()
    check_resources(args.data_dir)
    torch = check_gpu()
    if not args.skip_embedding:
        check_embedding(torch)
    n_fail = sum(r["status"] == "FAIL" for r in RESULTS)
    print(f"\nSUMMARY: {len(RESULTS)} checks, {n_fail} FAIL, "
          f"{sum(r['status'] == 'WARN' for r in RESULTS)} WARN")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(RESULTS, f, indent=2)
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
