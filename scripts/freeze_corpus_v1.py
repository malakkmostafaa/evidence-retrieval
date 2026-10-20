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
json.dump(out, open("docs/corpus_v1_freeze.json", "w"), indent=1)
print(json.dumps({k: v for k, v in out.items() if k != "chunk_params"}, indent=1))
