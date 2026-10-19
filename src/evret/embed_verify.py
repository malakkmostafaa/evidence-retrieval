"""S3 verification: self-retrieval, stored vs freshly computed vectors, truncations.

Usage: python -m evret.embed_verify --corpus data/corpus_v1 --bands 0 --n 300 --out outputs/corpus_v1
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np
import pyarrow.parquet as pq

from evret import embed as em


def verify(corpus: str, bands: list[int], n: int = 300, seed: int = 0) -> dict:
    import torch
    man = em.load_chunk_manifest(corpus)
    vecs = em.load_vectors(corpus, bands)
    lo = vecs[0][0]
    total = sum(a.shape[0] for _, a in vecs)
    rng = np.random.default_rng(seed)
    pick = np.sort(rng.choice(total, n, replace=False)) + lo
    # stored vectors and text hashes of the picked chunks
    stored = np.zeros((n, em.DIM), dtype=np.float32)
    for first, arr in vecs:
        m = (pick >= first) & (pick < first + arr.shape[0])
        stored[m] = np.asarray(arr[pick[m] - first], dtype=np.float32)
    hashes, texts = {}, {}
    for e in man["files"]:
        a, b = e["first_chunk_id"], e["first_chunk_id"] + e["rows"]
        sel = pick[(pick >= a) & (pick < b)]
        if not len(sel):
            continue
        t = pq.read_table(os.path.join(corpus, e["file"]), columns=["text_hash", "text_utf8", "n_tokens"])
        for c in sel:
            hashes[int(c)] = t.column("text_hash")[int(c) - a].as_py()
            texts[int(c)] = em.decode_text(t.column("text_utf8")[int(c) - a].as_py())
    # (1) exact search over every vector of the bands, in batches on the GPU
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    Q = torch.from_numpy(stored).to(dev)
    best_v = torch.full((n,), -2.0, device=dev)
    best_i = torch.zeros(n, dtype=torch.long, device=dev)
    all_ties = [[] for _ in range(n)]
    for first, arr in vecs:
        for s in range(0, arr.shape[0], 100_000):
            V = torch.from_numpy(np.asarray(arr[s:s + 100_000])).to(dev).float()
            S = Q @ V.T
            v, i = S.max(dim=1)
            upd = v > best_v
            best_v = torch.where(upd, v, best_v)
            best_i = torch.where(upd, i + first + s, best_i)
    best_i = best_i.cpu().numpy()
    # an exact duplicate = another chunk with the same text hash; look at the top-1 hash
    ok = 0
    dup_ok = 0
    need_hash = {int(b) for b in best_i if int(b) not in hashes}
    for e in man["files"]:
        a, b = e["first_chunk_id"], e["first_chunk_id"] + e["rows"]
        sel = [c for c in need_hash if a <= c < b]
        if sel:
            t = pq.read_table(os.path.join(corpus, e["file"]), columns=["text_hash"])
            for c in sel:
                hashes[c] = t.column("text_hash")[c - a].as_py()
    for j, c in enumerate(pick):
        if int(best_i[j]) == int(c):
            ok += 1
        elif hashes[int(best_i[j])] == hashes[int(c)]:
            ok += 1
            dup_ok += 1
    # (2) fresh recomputation (different batch composition) vs stored
    enc = em.Encoder()
    fresh = enc.embed_passages([texts[int(c)] for c in pick[::-1]])[::-1]
    cos = (fresh * stored).sum(1)
    nt = []
    for e in man["files"]:
        if em.band_of_file(e["file"]) in bands:
            nt.append(int(pq.read_table(os.path.join(corpus, e["file"]), columns=["n_tokens"]).column(0).to_numpy().max()))
    return {"bands": bands, "sampled": n, "self_retrieval_rate": round(ok / n, 4), "of_which_exact_duplicate": dup_ok,
            "cosine_stored_vs_fresh": {"median": float(np.median(cos)), "min": float(cos.min()),
                                       "p01": float(np.percentile(cos, 1))},
            "max_n_tokens_in_bands": max(nt), "truncations_in_verification": enc.truncations,
            "criteria": {"self_retrieval>=0.99": ok / n >= 0.99, "median_cosine>=0.999": float(np.median(cos)) >= 0.999,
                         "truncations==0": enc.truncations == 0 and max(nt) <= em.MAX_LEN}}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--bands", type=int, nargs="+", required=True)
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    res = verify(a.corpus, a.bands, a.n)
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "embed_verify_" + "_".join(map(str, a.bands)) + ".json"), "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    sys.exit(main())
