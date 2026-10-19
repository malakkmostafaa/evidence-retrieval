"""S3 - embed chunks with BAAI/bge-small-en-v1.5 (CLS pooling, L2-normalised), band by band, resumable.

Model card (checked 2026-10-19 in the local snapshot): 1_Pooling/config.json has pooling_mode_cls_token = true, 384
dimensions, no Normalize module (we normalise ourselves). For short-query -> long-passage retrieval the card recommends
the query instruction "Represent this sentence for searching relevant passages: "; passages get no prefix.

Passages: fp16 compute, float16 storage, sorted by token length inside a window to reduce padding, max_length 512 with
truncation DISABLED - a sequence longer than 512 raises (the chunker caps at 500, so truncations must be 0).
Queries: fp32 with the instruction.
Shards: <= 50,000 rows, float16 .npy, one directory per band; embed_manifest.json records model, revision, chunk table.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
import sys
import threading
import time
from queue import Queue

import numpy as np
import pyarrow.parquet as pq

from evret import audit
from evret.chunk import MODEL_REVISION, _clean_for_tokenizer
from evret.ingest import decode_text

MODEL_ID = "BAAI/bge-small-en-v1.5"
QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "
MAX_LEN = 512
SHARD_ROWS = 50_000
DIM = 384


def snapshot_dir() -> str:
    d = os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "hub", "models--BAAI--bge-small-en-v1.5",
                     "snapshots", MODEL_REVISION)
    if not os.path.isdir(d):
        raise FileNotFoundError(f"revision {MODEL_REVISION} of {MODEL_ID} is not in the local HF cache")
    return d


class Encoder:
    """Passages (fp16) and queries (fp32) with the same weights. Loads two copies only when both are requested."""

    def __init__(self, device: str = "cuda", dtype: str = "fp16"):
        import torch
        from tokenizers import Tokenizer
        from transformers import AutoModel
        self.torch, self.device = torch, device
        d = snapshot_dir()
        self.tok = Tokenizer.from_file(os.path.join(d, "tokenizer.json"))
        self.tok.no_truncation()
        self.tok.no_padding()
        self.dtype = torch.float16 if dtype == "fp16" else torch.float32
        self.model = AutoModel.from_pretrained(d).to(device=device, dtype=self.dtype).eval()
        self.truncations = 0

    def encode_ids(self, texts: list[str]) -> list[list[int]]:
        encs = self.tok.encode_batch([_clean_for_tokenizer(t) for t in texts])
        ids = [e.ids for e in encs]
        self.truncations += sum(len(x) > MAX_LEN for x in ids)
        if any(len(x) > MAX_LEN for x in ids):
            raise ValueError("a sequence exceeds 512 tokens (truncation is forbidden)")
        return ids

    def embed_ids(self, ids: list[list[int]]) -> np.ndarray:
        torch = self.torch
        L = max(len(x) for x in ids)
        inp = np.zeros((len(ids), L), dtype=np.int64)
        mask = np.zeros((len(ids), L), dtype=np.int64)
        for i, x in enumerate(ids):
            inp[i, :len(x)] = x
            mask[i, :len(x)] = 1
        with torch.inference_mode():
            out = self.model(input_ids=torch.from_numpy(inp).to(self.device),
                             attention_mask=torch.from_numpy(mask).to(self.device)).last_hidden_state[:, 0]
            out = torch.nn.functional.normalize(out.float(), dim=-1)
        return out.cpu().numpy()

    def embed_passages(self, texts: list[str], token_budget: int = 24_000) -> np.ndarray:
        """float32 unit vectors (caller stores float16). Batches are formed from length-sorted sequences."""
        ids = self.encode_ids(texts)
        order = sorted(range(len(ids)), key=lambda i: len(ids[i]))
        out = np.zeros((len(ids), DIM), dtype=np.float32)
        i = 0
        while i < len(order):
            j, longest = i, 0
            while j < len(order) and max(longest, len(ids[order[j]])) * (j - i + 1) <= token_budget:
                longest = max(longest, len(ids[order[j]]))
                j += 1
            j = max(j, i + 1)
            batch = order[i:j]
            try:
                out[batch] = self.embed_ids([ids[k] for k in batch])
                i = j
            except self.torch.cuda.OutOfMemoryError:
                self.torch.cuda.empty_cache()
                token_budget = max(512, token_budget // 2)           # halve the batch and retry
                print(f"CUDA OOM -> token budget {token_budget}", flush=True)
        return out

    def embed_queries(self, queries: list[str]) -> np.ndarray:
        """Queries are encoded in fp32 with the instruction (call on an Encoder created with dtype='fp32')."""
        ids = self.encode_ids([QUERY_INSTRUCTION + q for q in queries])
        return np.vstack([self.embed_ids(ids[i:i + 64]) for i in range(0, len(ids), 64)])


# ------------------------------------------------------------------------------------------ chunk table access
def load_chunk_manifest(corpus: str) -> dict:
    with open(os.path.join(corpus, "chunks_manifest.json"), encoding="utf-8") as f:
        return json.load(f)


def band_of_file(rel: str) -> int:
    return int(re.search(r"band=(\d+)", rel).group(1))


def band_range(man: dict, band: int) -> tuple[int, int]:
    es = [e for e in man["files"] if band_of_file(e["file"]) == band]
    if not es:
        return 0, 0
    return es[0]["first_chunk_id"], es[-1]["first_chunk_id"] + es[-1]["rows"]


def read_chunks(corpus: str, man: dict, lo: int, hi: int):
    """Yield (chunk_id_start, n_tokens array, texts) covering chunk ids [lo, hi) in file/row-group pieces."""
    for e in man["files"]:
        a, b = e["first_chunk_id"], e["first_chunk_id"] + e["rows"]
        if b <= lo or a >= hi:
            continue
        pf = pq.ParquetFile(os.path.join(corpus, e["file"]))
        pos = a
        for g in range(pf.num_row_groups):
            n = pf.metadata.row_group(g).num_rows
            if pos + n <= lo or pos >= hi:
                pos += n
                continue
            t = pf.read_row_group(g, columns=["text_utf8", "n_tokens"])
            s, f = max(lo, pos) - pos, min(hi, pos + n) - pos
            t = t.slice(s, f - s)
            yield pos + s, t.column("n_tokens").to_numpy(), [decode_text(x) for x in t.column("text_utf8").to_pylist()]
            pos += n


def manifest_path(corpus: str) -> str:
    return os.path.join(corpus, "embed_manifest.json")


def chunk_table_sha(man: dict, band: int) -> str:
    """Fingerprint of the chunk files of ONE band (later bands may be added without invalidating earlier ones)."""
    h = hashlib.sha256()
    for e in man["files"]:
        if band_of_file(e["file"]) == band:
            h.update((e["sha256"] + str(e["first_chunk_id"])).encode())
    return h.hexdigest()


def embed_band(corpus: str, band: int, enc: Encoder, budget: int = 24_000, log=print) -> dict:
    man = load_chunk_manifest(corpus)
    lo, hi = band_range(man, band)
    mpath = manifest_path(corpus)
    emb = json.load(open(mpath, encoding="utf-8")) if os.path.exists(mpath) else {
        "model": MODEL_ID, "revision": MODEL_REVISION, "dim": DIM, "dtype": "float16", "pooling": "cls",
        "normalized": True, "max_length": MAX_LEN, "shard_rows": SHARD_ROWS, "bands": {}}
    if (emb["model"], emb["revision"]) != (MODEL_ID, MODEL_REVISION):
        raise RuntimeError("embed manifest was made with a different model/revision")
    if str(band) in emb["bands"] and emb["bands"][str(band)].get("chunk_table_sha") != chunk_table_sha(man, band) and \
            emb["bands"][str(band)].get("complete"):
        raise RuntimeError(f"band {band} was embedded from a different chunk table")
    bdir = os.path.join(corpus, "vectors", f"band={band}")
    os.makedirs(bdir, exist_ok=True)
    shards = emb["bands"].setdefault(str(band), {"first_chunk_id": lo, "rows": hi - lo, "shards": [], "complete": False,
                                                 "chunk_table_sha": chunk_table_sha(man, band)})
    done = {s["file"] for s in shards["shards"]}
    t0, n_done = time.time(), 0
    for k, a in enumerate(range(lo, hi, SHARD_ROWS)):
        name = f"shard_{k:04d}.npy"
        path = os.path.join(bdir, name)
        b = min(a + SHARD_ROWS, hi)
        if name in done and os.path.exists(path):
            continue
        ids_all, texts_all = [], []
        for _, nt, texts in read_chunks(corpus, man, a, b):
            texts_all += texts
        vec = np.zeros((b - a, DIM), dtype=np.float16)
        for i in range(0, len(texts_all), 4096):                     # fp32 -> fp16 once per 4096 rows
            vec[i:i + 4096] = enc.embed_passages(texts_all[i:i + 4096], budget).astype(np.float16)
        tmp = path + ".tmp"
        with open(tmp, "wb") as f:
            np.save(f, vec)
        os.replace(tmp, path)
        shards["shards"] = [s for s in shards["shards"] if s["file"] != name] + [
            {"file": name, "first_chunk_id": a, "rows": b - a, "sha256": audit.sha256_file(path)}]
        shards["shards"].sort(key=lambda s: s["file"])
        n_done += b - a
        rate = n_done / (time.time() - t0)
        remaining = (hi - b) / rate
        log(f"band {band}: shard {k} done ({b - lo:,}/{hi - lo:,} chunks) {rate:.0f} chunks/s, "
            f"ETA {remaining / 60:.0f} min, truncations {enc.truncations}", flush=True)
        with open(mpath, "w", encoding="utf-8") as f:
            json.dump(emb, f, indent=1)
    shards["complete"] = True
    shards["truncations_this_run"] = enc.truncations
    with open(mpath, "w", encoding="utf-8") as f:
        json.dump(emb, f, indent=1)
    return shards


def load_vectors(corpus: str, bands: list[int]) -> list[tuple[int, np.ndarray]]:
    """[(first_chunk_id, memmapped float16 array)] for the finished bands, ascending."""
    emb = json.load(open(manifest_path(corpus), encoding="utf-8"))
    out = []
    for b in sorted(bands):
        info = emb["bands"][str(b)]
        if not info.get("complete"):
            raise RuntimeError(f"band {b} is not fully embedded")
        for s in info["shards"]:
            out.append((s["first_chunk_id"], np.load(os.path.join(corpus, "vectors", f"band={b}", s["file"]),
                                                    mmap_mode="r")))
    return out


def benchmark(corpus: str, n: int = 6000, budgets=(8_000, 16_000, 32_000), seconds: float = 300) -> dict:
    """Short benchmark on a fixed sample of chunks of the first chunked band."""
    man = load_chunk_manifest(corpus)
    texts = []
    for _, nt, tx in read_chunks(corpus, man, 0, min(man["n_chunks"], 400_000)):
        texts += tx
        if len(texts) >= n * 5:
            break
    rng = np.random.default_rng(0)
    sample = [texts[i] for i in rng.choice(len(texts), n, replace=False)]
    enc = Encoder()
    res = {}
    enc.embed_passages(sample[:256], 16_000)                          # warm-up
    t_all = time.time()
    for bud in budgets:
        if time.time() - t_all > seconds:
            break
        enc.torch.cuda.synchronize()
        t0 = time.time()
        enc.embed_passages(sample, bud)
        enc.torch.cuda.synchronize()
        res[f"fp16_budget_{bud}"] = round(n / (time.time() - t0), 1)
    t0 = time.time()
    ids = enc.encode_ids(sample)
    res["tokenize_only_chunks_per_s"] = round(n / (time.time() - t0), 1)
    res["mean_tokens"] = round(float(np.mean([len(x) for x in ids])), 1)
    res["peak_vram_gb"] = round(enc.torch.cuda.max_memory_allocated() / 1e9, 2)
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--bands", type=int, nargs="*", default=[])
    ap.add_argument("--benchmark", action="store_true")
    ap.add_argument("--budget", type=int, default=24_000)
    a = ap.parse_args(argv)
    if a.benchmark:
        print(json.dumps(benchmark(a.corpus), indent=1))
        return
    enc = Encoder()
    for b in a.bands:
        embed_band(a.corpus, b, enc, a.budget)


if __name__ == "__main__":
    sys.exit(main())
