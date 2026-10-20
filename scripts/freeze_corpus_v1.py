"""Write docs/corpus_v1_freeze.json: hashes that identify corpus v1 (documents, chunks, vectors, BM25 index)."""
import glob
import hashlib
import json
import os
import subprocess

from evret.audit import sha256_file

R = "data/corpus_v1"


def digest(pairs):
    h = hashlib.sha256()
    for k, v in sorted(pairs):
        h.update(f"{k}\t{v}\n".encode())
    return h.hexdigest()


cm = json.load(open(f"{R}/chunks_manifest.json"))
em = json.load(open(f"{R}/embed_manifest.json"))
im = json.load(open(f"{R}/manifest.json"))
vec = [(f"band={b}/{s['file']}", s["sha256"]) for b, v in em["bands"].items() for s in v["shards"]]
bm = [(os.path.relpath(f, R).replace(os.sep, "/"), sha256_file(f)) for f in sorted(glob.glob(f"{R}/bm25/band=*/*"))]
out = {
    "frozen": "2026-10-20",
    "git_commit_at_freeze": subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip(),
    "ingest_manifest_sha256": sha256_file(f"{R}/manifest.json"),
    "documents_shards_digest": digest([(s["file"], s["sha256"]) for s in im["shards"]]),
    "n_document_shards": len(im["shards"]),
    "chunks_manifest_sha256": sha256_file(f"{R}/chunks_manifest.json"),
    "chunks_digest": digest([(e["file"], e["sha256"]) for e in cm["files"]]),
    "n_chunks": cm["n_chunks"], "n_chunk_files": len(cm["files"]),
    "embed_manifest_sha256": sha256_file(f"{R}/embed_manifest.json"),
    "vectors_digest": digest(vec), "n_vector_shards": len(vec),
    "bm25_digest": digest(bm), "n_bm25_files": len(bm),
    "ranks_sha256": sha256_file(f"{R}/ranks.json"),
    "doc_index_pool_sha256": sha256_file(f"{R}/doc_index_pool.parquet"),
    "model": em["model"], "model_revision": em["revision"], "chunk_params": cm["params"],
}
import platform
import sys

import numpy
import pyarrow
import tokenizers
import torch
import transformers

from evret import eval_pool as ev
from evret import metrics_cov as mc

status = subprocess.run(["git", "status", "--porcelain", "--", "src", "tests", "scripts"], capture_output=True, text=True).stdout
out["code"] = {"repo_git_commit": out.pop("git_commit_at_freeze"), "src_tests_scripts_clean": status.strip() == "",
               "sha256": {f: sha256_file(f"src/evret/{f}") for f in
                          ("chunk.py", "embed.py", "bm25.py", "search.py", "ingest.py", "pool.py", "urls.py",
                           "metrics_cov.py", "stats.py", "eval_pool.py", "eval_labels.py", "eval_removal.py")}}
out["environment"] = {
    "python": sys.version.split()[0], "platform": platform.platform(), "numpy": numpy.__version__,
    "torch": torch.__version__, "cuda": torch.version.cuda, "transformers": transformers.__version__,
    "tokenizers": tokenizers.__version__, "pyarrow": pyarrow.__version__,
    "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
    "note": "passages embedded on the GPU in fp16 and stored as float16; a fresh recomputation of 300 stored vectors differs "
            "by cosine >= 0.99984 (median 1.000001, outputs/corpus_v1/embed_verify_0_1_2_3_4_5.json) and fp16 vs fp32 by "
            "cosine > 0.999 (tests/test_embed.py), i.e. device/precision changes vectors at the 1e-3 level, so the "
            "environment is part of the freeze"}
# metric version and claim sets
ing = json.load(open(f"{R}/manifest.json"))
claims = ev.load_claims("C:/Users/malak/Desktop/thesis/data/raw/averitec/dev.json", f"{R}/ranks.json",
                        ing["config"]["band_size"], list(range(6)))
from evret import search as sr
corpus = sr.Corpus(R, list(range(6)))
reach = [any(ev.reachable_flags(corpus, c)) for c in claims]
anch = ev.anchored_answers(R, claims)
elig = [c["claim_id"] for c in claims if anch[c["claim_id"]]]
novel = [c["claim_id"] for c in claims if anch[c["claim_id"]] and
         mc.novel_answers(anch[c["claim_id"]], frozenset(mc.content_tokens(c["text"])))]
out["metrics"] = {
    "module": "evret.metrics_cov", "metrics_cov_sha256": out["code"]["sha256"]["metrics_cov.py"],
    "stats_sha256": out["code"]["sha256"]["stats.py"], "budget_tokens": ev.COV_BUDGET,
    "constants": {"THETA": mc.THETA, "MIN_ANSWER_TOKENS": mc.MIN_ANSWER_TOKENS, "ANCHOR_WINDOW": mc.ANCHOR_WINDOW,
                  "ANCHOR_THETA": mc.ANCHOR_THETA},
    "claim_sets": {
        "evaluated_pool_claims": {"n": len(claims), "ids": sorted(c["claim_id"] for c in claims)},
        "reachable_gold_SourceHit_GoldRecall": {"n": int(sum(reach)), "ids": sorted(c["claim_id"] for c, r in zip(claims, reach) if r)},
        "anchored_answer_CovUnion_AnswerRecall": {"n": len(elig), "ids": sorted(elig)},
        "CovNovel_defined": {"n": len(novel), "ids": sorted(novel)}}}
json.dump(out, open("docs/corpus_v1_freeze.json", "w"), indent=1)
print(json.dumps({k: v for k, v in out.items() if k not in ("chunk_params", "code", "metrics")}, indent=1)); print(out["environment"]); print({k: v["n"] for k, v in out["metrics"]["claim_sets"].items()}, out["code"]["repo_git_commit"], out["code"]["src_tests_scripts_clean"])
