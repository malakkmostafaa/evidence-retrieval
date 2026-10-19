"""S2 verification on the real chunk files: spans, hashes, coverage, caps, counts by band and web/PDF.

Usage: python -m evret.chunk_verify --corpus data/corpus_v1 --bands 0 --docs 300 --out outputs/corpus_v1
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import random
import sys
from collections import defaultdict

import numpy as np
import pyarrow.parquet as pq

from evret.chunk import FLAG_PDF, FLAG_SPLIT, MAX_CHARS, MAX_TOKENS, _hash64, make_counter, tokenizer_file
from evret.ingest import decode_text


def counts(corpus: str, bands: list[int]) -> dict:
    out = {}
    for b in bands:
        c = defaultdict(int)
        for f in sorted(glob.glob(os.path.join(corpus, "chunks", f"band={b}", "rank_*.parquet"))):
            t = pq.read_table(f, columns=["flags", "n_tokens", "start", "end"])
            fl = t.column("flags").to_numpy()
            nt = t.column("n_tokens").to_numpy()
            ln = t.column("end").to_numpy() - t.column("start").to_numpy()
            pdf = (fl & FLAG_PDF) != 0
            c["chunks"] += len(fl)
            c["chunks_pdf"] += int(pdf.sum())
            c["chunks_web"] += int((~pdf).sum())
            c["chunks_split"] += int(((fl & FLAG_SPLIT) != 0).sum())
            c["tokens_sum"] += int(nt.sum())
            c["chars_sum"] += int(ln.sum())
            c["max_tokens"] = max(c["max_tokens"], int(nt.max()) if len(nt) else 0)
            c["max_chars"] = max(c["max_chars"], int(ln.max()) if len(ln) else 0)
            c["over_500_tokens"] += int((nt > MAX_TOKENS).sum())
            c["over_5000_chars"] += int((ln > MAX_CHARS).sum())
        c = dict(c)
        c["mean_tokens"] = round(c["tokens_sum"] / max(c["chunks"], 1), 1)
        c["mean_chars"] = round(c["chars_sum"] / max(c["chunks"], 1), 1)
        out[b] = c
    return out


def check_docs(corpus: str, band: int, n_docs: int, n_recount: int, seed: int = 0) -> dict:
    rng = random.Random(seed)
    shards = sorted(glob.glob(os.path.join(corpus, "documents", f"band={band}", "rank_*.parquet")))
    count = make_counter(tokenizer_file())
    res = {"docs_checked": 0, "chunks_checked": 0, "span_errors": 0, "hash_errors": 0, "coverage_errors": 0,
           "token_recount_checked": 0, "token_recount_mismatch": 0, "docs_without_chunks_but_nonempty_nontiny": 0}
    recount_pool = []
    per_shard = max(1, n_docs // max(len(shards), 1))
    for sh in shards:
        cf = sh.replace("documents", "chunks")
        docs = pq.read_table(sh, columns=["doc_id", "text_utf8", "is_empty", "is_tiny"])
        chunks = pq.read_table(cf, columns=["doc_id", "start", "end", "n_tokens", "text_hash"]).to_pydict()
        by_doc = defaultdict(list)
        for i, d in enumerate(chunks["doc_id"]):
            by_doc[d].append(i)
        ids = docs.column("doc_id").to_pylist()
        order = list(range(len(ids)))
        order.sort(key=lambda i: -len(docs.column("text_utf8")[i].as_py()) if rng.random() < 0.3 else rng.random())
        for i in order[:per_shard]:
            did = ids[i]
            if docs.column("is_empty")[i].as_py() or docs.column("is_tiny")[i].as_py():
                continue
            text = decode_text(docs.column("text_utf8")[i].as_py())
            rows = by_doc.get(did, [])
            res["docs_checked"] += 1
            if not rows:
                res["docs_without_chunks_but_nonempty_nontiny"] += 1
                continue
            spans = []
            for r in rows:
                s, e = chunks["start"][r], chunks["end"][r]
                res["chunks_checked"] += 1
                if not (0 <= s < e <= len(text)):
                    res["span_errors"] += 1
                    continue
                if _hash64(text[s:e]) != chunks["text_hash"][r]:
                    res["hash_errors"] += 1
                spans.append((s, e))
                if len(recount_pool) < 20 * n_recount and rng.random() < 0.02:
                    recount_pool.append((text[s:e], chunks["n_tokens"][r]))
            spans.sort()
            pos, bad = 0, False
            for s, e in spans:
                if s > pos and text[pos:s].strip():
                    bad = True
                    break
                pos = max(pos, e)
            if text[pos:].strip():
                bad = True
            res["coverage_errors"] += bad
    for txt, n in recount_pool[:n_recount]:
        res["token_recount_checked"] += 1
        res["token_recount_mismatch"] += count([txt])[0] != n
    return res


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--bands", type=int, nargs="+", required=True)
    ap.add_argument("--docs", type=int, default=300)
    ap.add_argument("--recount", type=int, default=2000)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    res = {"counts": counts(a.corpus, a.bands), "checks": {b: check_docs(a.corpus, b, a.docs, a.recount) for b in a.bands}}
    os.makedirs(a.out, exist_ok=True)
    name = "chunk_verify_" + "_".join(map(str, a.bands)) + ".json"
    with open(os.path.join(a.out, name), "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    sys.exit(main())
