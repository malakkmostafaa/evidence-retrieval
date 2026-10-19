"""S1 verification: reconcile the ingest output with the Block 1b audit, read back sampled documents from the ZIPs,
and print 50 random flagged fact-check URLs for manual judgement.

Usage: python -m evret.ingest_verify --corpus data/corpus_v1 --audit outputs/block01_audit --report outputs/corpus_v1
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import random
import sys

import pyarrow.compute as pc
import pyarrow.parquet as pq

from evret.audit import FailureLog
from evret.ingest import decode_text, iter_records, list_stores, record_meta


def reconcile(corpus: str, audit_dir: str) -> dict:
    fu = json.load(open(os.path.join(audit_dir, "audit_followup.json"), encoding="utf-8"))["size_after_dedup"]
    su = json.load(open(os.path.join(audit_dir, "audit_summary.json"), encoding="utf-8"))
    man = json.load(open(os.path.join(corpus, "manifest.json"), encoding="utf-8"))
    c = man["counts"]
    checks = {
        "records": (c["records"], su["reading"]["records"]),
        "unique_keys": (c["documents"], fu["unique_keys_(url,text)"]),
        "unique_nonempty_keys": (c["documents_nonempty"], fu["unique_nonempty_keys"]),
        "unique_chars": (c["unique_chars"], fu["unique_chars"]),
        "max_n_chars": (c["max_n_chars"], su["text"]["chars_percentiles_all"]["max"]),
    }
    return {k: {"ingest": a, "audit": b, "ok": a == b} for k, (a, b) in checks.items()}


def readback(corpus: str, zip_dir: str, dev_unused=None, n: int = 200, seed: int = 0) -> dict:
    """Sample n pool documents (oversampling U+2028 / NUL / non-BMP / surrogate / PDF / tiny) and compare each with a
    fresh, independent read of the original ZIP record of its min_rank claim."""
    rng = random.Random(seed)
    ranks = {int(v): int(k) for k, v in json.load(open(os.path.join(corpus, "ranks.json"))).items()}  # rank -> claim
    shards = sorted(glob.glob(os.path.join(corpus, "documents", "band=*", "rank_*.parquet")))
    meta = []
    for f in shards:
        t = pq.read_table(f, columns=["doc_id", "norm_url", "content_hash", "min_rank", "n_u2028", "n_nul", "n_nonbmp",
                                      "has_surrogate", "is_pdf", "n_chars"])
        for r in t.to_pylist():
            r["file"] = f
            meta.append(r)
    special = [m for m in meta if m["n_u2028"] or m["n_nul"] or m["n_nonbmp"] or m["has_surrogate"]]
    picks = {m["doc_id"]: m for m in rng.sample(special, min(len(special), n // 2))}
    for m in rng.sample(meta, len(meta)):
        if len(picks) >= n:
            break
        picks.setdefault(m["doc_id"], m)
    stores = list_stores(zip_dir)
    by_rank: dict[int, list] = {}
    for m in picks.values():
        by_rank.setdefault(m["min_rank"], []).append(m)
    ok = bad = 0
    covered = {"u2028": 0, "nul": 0, "nonbmp": 0, "surrogate": 0, "pdf": 0}
    problems = []
    for rank, ms in sorted(by_rank.items()):
        zp, member = stores[ranks[rank]]
        want = {(m["norm_url"], m["content_hash"]): m for m in ms}
        originals = {}
        for _, obj, text, _n in iter_records(zp, member, member, FailureLog()):
            mm = record_meta(obj, text)
            k = (mm["norm_url"], mm["content_hash"])
            if k in want and k not in originals:
                originals[k] = text
        for f in {m["file"] for m in ms}:
            tbl = pq.read_table(f, columns=["doc_id", "text_utf8"])
            texts = {d: decode_text(b) for d, b in zip(tbl.column("doc_id").to_pylist(), tbl.column("text_utf8").to_pylist())
                     if d in {m["doc_id"] for m in ms}}
            for m in ms:
                if m["doc_id"] not in texts:
                    continue
                orig = originals.get((m["norm_url"], m["content_hash"]))
                same = orig is not None and orig == texts[m["doc_id"]] and \
                    orig.encode("utf-8", "surrogatepass") == texts[m["doc_id"]].encode("utf-8", "surrogatepass")
                ok += same
                bad += not same
                if not same:
                    problems.append(m["doc_id"])
                else:
                    covered["u2028"] += bool(m["n_u2028"])
                    covered["nul"] += bool(m["n_nul"])
                    covered["nonbmp"] += bool(m["n_nonbmp"])
                    covered["surrogate"] += bool(m["has_surrogate"])
                    covered["pdf"] += bool(m["is_pdf"])
    return {"sampled": len(picks), "identical": ok, "different": bad, "problems": problems[:10],
            "documents_with_feature_in_sample": covered, "special_docs_in_pool": len(special)}


def factcheck_sample(corpus: str, n: int = 50, seed: int = 0) -> dict:
    t = pq.read_table(os.path.join(corpus, "doc_index_pool.parquet"), columns=["norm_url", "is_factcheck", "is_empty"])
    fc = t.filter(pc.field("is_factcheck")).column("norm_url").to_pylist()
    rng = random.Random(seed)
    return {"pool_documents": t.num_rows, "flagged": len(fc), "sample": sorted(rng.sample(fc, min(n, len(fc))))}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--audit", required=True)
    ap.add_argument("--zips", required=True)
    ap.add_argument("--report", required=True)
    a = ap.parse_args(argv)
    os.makedirs(a.report, exist_ok=True)
    res = {"reconciliation": reconcile(a.corpus, a.audit)}
    print(json.dumps(res["reconciliation"], indent=1))
    res["readback"] = readback(a.corpus, a.zips)
    print(json.dumps(res["readback"], indent=1))
    res["factcheck"] = factcheck_sample(a.corpus)
    with open(os.path.join(a.report, "ingest_verify.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1)
    with open(os.path.join(a.report, "factcheck_sample50.txt"), "w", encoding="utf-8") as f:
        f.write(f"flagged {res['factcheck']['flagged']} of {res['factcheck']['pool_documents']} pool documents\n")
        f.write("\n".join(res["factcheck"]["sample"]) + "\n")
    print("flagged:", res["factcheck"]["flagged"], "of", res["factcheck"]["pool_documents"])


if __name__ == "__main__":
    sys.exit(main())
