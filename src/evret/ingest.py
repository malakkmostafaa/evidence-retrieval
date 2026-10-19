"""S1 - ingest the knowledge-store ZIPs into a de-duplicated, rank-ordered document table.

Pass 1 streams the stores (no text kept): key = (normalised URL, content hash) -> min_rank, flags, n_chars, plus one
origin row per record. Pass 2 re-reads the POOL stores in rank order and writes each document once, from the store of
its min_rank claim, into one Parquet shard per store. Sealed bands get metadata only (see docs/plans).

Layout under --out:
    work/pass1/rank_NNN.pkl           per-store pass-1 result (resume cache; deleted by --clean)
    doc_index_pool.parquet            metadata, no text, documents of pool bands
    doc_index_sealed.parquet          metadata, no text, documents of sealed bands (never read outside ingest)
    origins.parquet                   one row per record (doc_id, claim_rank, claim_id, type, query, url_raw, line_no)
    documents/band=B/rank_NNN.parquet text shards, one per store whose claim owns documents (pool bands only)
    ranks.json                        claim_id -> rank
    manifest.json                     config, sha256 per shard, code hash, counts
Text is stored byte-exact as UTF-8 in a binary column ('surrogatepass' so lone surrogates survive).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing as mp
import os
import pickle
import re
import sys
import time
import zipfile
from collections import Counter, deque

import pyarrow as pa
import pyarrow.parquet as pq

from evret import pool as poolmod
from evret.audit import (TINY_CHARS, FailureLog, content_hash, git_commit, host_of, is_factcheck, is_pdf,
                         iter_store_lines, load_dev, normalize_url, parse_record, record_text, sha256_file, url_date)

DOC_COLUMNS = ["doc_id", "norm_url", "url", "host", "content_hash", "n_chars", "n_items", "is_pdf", "is_empty",
               "is_tiny", "is_factcheck", "pub_date", "date_source", "min_rank", "band"]


# --------------------------------------------------------------------------------------------- helpers
def encode_text(text: str) -> bytes:
    return text.encode("utf-8", "surrogatepass")


def decode_text(b: bytes) -> str:
    return b.decode("utf-8", "surrogatepass")


def list_stores(zip_dir: str) -> dict[int, tuple[str, str]]:
    """claim_id -> (zip path, member name)."""
    out: dict[int, tuple[str, str]] = {}
    for n in sorted(os.listdir(zip_dir)):
        if not n.lower().endswith(".zip"):
            continue
        zp = os.path.join(zip_dir, n)
        with zipfile.ZipFile(zp) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                stem, ext = os.path.splitext(info.filename.replace("\\", "/").rsplit("/", 1)[-1])
                if ext.lower() in (".json", ".jsonl") and stem.isdigit() and int(stem) not in out:
                    out[int(stem)] = (zp, info.filename)
    return out


def iter_records(zip_path: str, member: str, where: str, fails: FailureLog):
    """Yield (line_no, obj, text, n_items) for every record of one store; lines split ONLY at b'\\n'."""
    stats: Counter = Counter()
    with zipfile.ZipFile(zip_path) as zf, zf.open(member) as raw:
        for line_no, line in iter_store_lines(raw):
            obj = parse_record(line, f"{where}:{line_no}", fails)
            if obj == "blank":
                stats["blank"] += 1
                continue
            if obj is None:
                stats["bad"] += 1
                continue
            text, n_items = record_text(obj, f"{where}:{line_no}", fails, stats)
            yield line_no, obj, text, n_items


def record_meta(obj: dict, text: str) -> dict:
    url = obj.get("url") or ""
    nurl = normalize_url(url)
    empty = not text.strip()
    d = url_date(url)
    return {"norm_url": nurl, "url": url, "host": host_of(nurl), "content_hash": content_hash(text),
            "n_chars": len(text), "is_pdf": bool(is_pdf(url, text)), "is_empty": empty,
            "is_tiny": (not empty) and len(text) < TINY_CHARS, "is_factcheck": bool(nurl) and is_factcheck(nurl),
            "pub_date": d, "date_source": "url" if d else "none"}


# --------------------------------------------------------------------------------------------- pass 1
def pass1_store(task: dict) -> int:
    path = task["cache"]
    if os.path.exists(path):
        return task["rank"]
    fails = FailureLog()
    keys: dict[tuple[str, str], int] = {}
    docs: list[dict] = []
    origins: list[tuple] = []
    lines = records = 0
    stats: Counter = Counter()
    for line_no, obj, text, n_items in iter_records(task["zip"], task["member"], f"{task['member']}", fails):
        records += 1
        m = record_meta(obj, text)
        k = (m["norm_url"], m["content_hash"])
        idx = keys.get(k)
        if idx is None:
            idx = keys[k] = len(docs)
            m["n_items"] = n_items
            docs.append(m)
        origins.append((idx, str(obj.get("type")), str(obj.get("query")), m["url"], line_no))
    res = {"rank": task["rank"], "claim_id": task["claim_id"], "docs": docs, "origins": origins,
           "records": records, "fails": dict(fails.counts)}
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        pickle.dump(res, f, protocol=4)
    os.replace(tmp, path)
    return task["rank"]


# --------------------------------------------------------------------------------------------- pass 2
_NONBMP = None


def doc_row_extras(text: str) -> dict:
    nb = 0
    if not text.isascii():
        nb = len(text.encode("utf-16-le", "surrogatepass")) // 2 - len(text)
    return {"n_nul": text.count("\x00"), "n_u2028": text.count(" "), "n_nonbmp": nb,
            "has_surrogate": bool(re.search("[\ud800-\udfff]", text)) if not text.isascii() else False}


SHARD_SCHEMA = pa.schema([
    ("doc_id", pa.int64()), ("norm_url", pa.string()), ("url", pa.string()), ("host", pa.string()),
    ("content_hash", pa.string()), ("text_utf8", pa.large_binary()), ("n_chars", pa.int64()),
    ("n_items", pa.int32()), ("is_pdf", pa.bool_()), ("is_empty", pa.bool_()), ("is_tiny", pa.bool_()),
    ("is_factcheck", pa.bool_()), ("pub_date", pa.string()), ("date_source", pa.string()),
    ("min_rank", pa.int32()), ("band", pa.int32()), ("n_nul", pa.int32()), ("n_u2028", pa.int32()),
    ("n_nonbmp", pa.int32()), ("has_surrogate", pa.bool_()),
])


def pass2_store(task: dict) -> dict:
    """Write the documents owned by this store (their min_rank is this store's rank) into one shard."""
    out = task["out"]
    if os.path.exists(out):
        return {"rank": task["rank"], "path": out, "skipped": True}
    wanted: dict[tuple[str, str], int] = {k: v for k, v in task["wanted"]}      # key -> doc_id
    rows: dict[str, list] = {c: [] for c in SHARD_SCHEMA.names}
    done: set[tuple[str, str]] = set()
    fails = FailureLog()
    for line_no, obj, text, n_items in iter_records(task["zip"], task["member"], task["member"], fails):
        m = record_meta(obj, text)
        k = (m["norm_url"], m["content_hash"])
        if k not in wanted or k in done:
            continue
        done.add(k)
        ex = doc_row_extras(text)
        row = {**m, **ex, "doc_id": wanted[k], "text_utf8": encode_text(text), "n_items": n_items,
               "min_rank": task["rank"], "band": task["band"]}
        for c in SHARD_SCHEMA.names:
            rows[c].append(row[c])
    if len(done) != len(wanted):
        raise RuntimeError(f"rank {task['rank']}: expected {len(wanted)} documents, found {len(done)}")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    tmp = out + ".tmp"
    pq.write_table(pa.table(rows, schema=SHARD_SCHEMA), tmp, compression="zstd", compression_level=6,
                   row_group_size=64)
    os.replace(tmp, out)
    return {"rank": task["rank"], "path": out, "skipped": False, "n_docs": len(done)}


# --------------------------------------------------------------------------------------------- driver
def code_hash() -> str:
    h = hashlib.sha256()
    here = os.path.dirname(os.path.abspath(__file__))
    for n in ("ingest.py", "pool.py", "audit.py"):
        with open(os.path.join(here, n), "rb") as f:
            h.update(f.read())
    return h.hexdigest()


def windowed(pool: mp.pool.Pool, fn, tasks: list, window: int):
    """Ordered results with a bounded number of tasks in flight (texts are large)."""
    pending: deque = deque()
    it = iter(tasks)
    for t in it:
        pending.append(pool.apply_async(fn, (t,)))
        if len(pending) >= window:
            yield pending.popleft().get()
    while pending:
        yield pending.popleft().get()


def ingest(zip_dir: str, dev_path: str, subsets_path: str, out: str, old_split: str | None = None,
           seed: int = poolmod.SEED, band_size: int = poolmod.BAND_SIZE, pool_bands: int = poolmod.POOL_BANDS,
           workers: int = 4, include_sealed_text: bool = False, verbose: bool = True) -> dict:
    log = print if verbose else (lambda *a, **k: None)
    t0 = time.time()
    os.makedirs(os.path.join(out, "work", "pass1"), exist_ok=True)
    dev = load_dev(dev_path)
    from evret.audit import load_subsets
    claim_ids = sorted(load_subsets(subsets_path)["dev300"])
    labels = {c["claim_id"]: c["label"] for c in dev}
    op, oh = poolmod.load_old_split(old_split) if old_split else (None, None)
    ranks = poolmod.build_ranks(claim_ids, labels, seed, op, oh)
    stores = list_stores(zip_dir)
    missing = [c for c in claim_ids if c not in stores]
    if missing:
        raise FileNotFoundError(f"no store for claims {missing[:10]}")
    with open(os.path.join(out, "ranks.json"), "w", encoding="utf-8") as f:
        json.dump({str(c): r for c, r in sorted(ranks.items(), key=lambda kv: kv[1])}, f)
    by_rank = sorted(claim_ids, key=lambda c: ranks[c])
    pool_ranks = pool_bands * band_size

    # ---- pass 1
    tasks = [{"rank": ranks[c], "claim_id": c, "zip": stores[c][0], "member": stores[c][1],
              "cache": os.path.join(out, "work", "pass1", f"rank_{ranks[c]:03d}.pkl")} for c in by_rank]
    ctx = mp.get_context("spawn")
    with ctx.Pool(workers) as pl:
        for i, r in enumerate(pl.imap(pass1_store, tasks)):
            if verbose and (i + 1) % 25 == 0:
                log(f"  pass 1: {i + 1}/{len(tasks)} stores  {time.time() - t0:.0f}s")
    # ---- merge in rank order
    doc_key: dict[tuple[str, str], int] = {}
    doc_rows: list[dict] = []
    origin_cols: dict[str, list] = {c: [] for c in ("doc_id", "claim_rank", "claim_id", "type", "query",
                                                     "url_raw", "line_no")}
    records = 0
    for t in tasks:
        with open(t["cache"], "rb") as f:
            res = pickle.load(f)
        records += res["records"]
        local_to_global = []
        for d in res["docs"]:
            k = (d["norm_url"], d["content_hash"])
            gid = doc_key.get(k)
            if gid is None:
                gid = doc_key[k] = len(doc_rows)
                d = dict(d, doc_id=gid, min_rank=res["rank"], band=poolmod.band_of(res["rank"], band_size),
                         _store_rank=res["rank"])
                doc_rows.append(d)
            local_to_global.append(gid)
        for (idx, typ, q, url, ln) in res["origins"]:
            origin_cols["doc_id"].append(local_to_global[idx])
            origin_cols["claim_rank"].append(res["rank"])
            origin_cols["claim_id"].append(res["claim_id"])
            origin_cols["type"].append(typ)
            origin_cols["query"].append(q)
            origin_cols["url_raw"].append(url)
            origin_cols["line_no"].append(ln)
    log(f"pass 1 merged: {records:,} records, {len(doc_rows):,} documents, {time.time() - t0:.0f}s")

    # ---- indexes (no text)
    def idx_table(rows):
        return pa.table({c: [r[c] for r in rows] for c in DOC_COLUMNS})
    pool_rows = [r for r in doc_rows if r["min_rank"] < pool_ranks]
    sealed_rows = [r for r in doc_rows if r["min_rank"] >= pool_ranks]
    pq.write_table(idx_table(pool_rows), os.path.join(out, "doc_index_pool.parquet"), compression="zstd")
    pq.write_table(idx_table(sealed_rows), os.path.join(out, "doc_index_sealed.parquet"), compression="zstd")
    pq.write_table(pa.table(origin_cols), os.path.join(out, "origins.parquet"), compression="zstd")

    # ---- pass 2
    owned: dict[int, list] = {}
    for r in doc_rows:
        owned.setdefault(r["min_rank"], []).append(((r["norm_url"], r["content_hash"]), r["doc_id"]))
    t2 = []
    last_rank = len(by_rank) if include_sealed_text else pool_ranks
    for c in by_rank:
        r = ranks[c]
        if r >= last_rank or r not in owned:
            continue
        b = poolmod.band_of(r, band_size)
        t2.append({"rank": r, "zip": stores[c][0], "member": stores[c][1], "wanted": owned[r], "band": b,
                   "out": os.path.join(out, "documents", f"band={b}", f"rank_{r:03d}.parquet")})
    shards = []
    with ctx.Pool(workers) as pl:
        for i, res in enumerate(windowed(pl, pass2_store, t2, workers + 1)):
            shards.append(res)
            if verbose and (i + 1) % 20 == 0:
                log(f"  pass 2: {i + 1}/{len(t2)} stores  {time.time() - t0:.0f}s")
    shard_info = [{"rank": s["rank"], "file": os.path.relpath(s["path"], out).replace("\\", "/"),
                   "sha256": sha256_file(s["path"]), "bytes": os.path.getsize(s["path"])} for s in shards]

    n_nonempty = sum(not r["is_empty"] for r in doc_rows)
    manifest = {
        "created_seconds": round(time.time() - t0, 1), "code_sha256": code_hash(), "git_commit": git_commit(),
        "config": {"seed": seed, "band_size": band_size, "pool_bands": pool_bands, "old_split": old_split,
                   "include_sealed_text": include_sealed_text, "zip_dir": zip_dir},
        "inputs": {"dev_sha256": sha256_file(dev_path), "subsets_sha256": sha256_file(subsets_path)},
        "versions": {"pyarrow": pa.__version__, "python": sys.version.split()[0]},
        "counts": {"records": records, "documents": len(doc_rows), "documents_nonempty": n_nonempty,
                   "documents_pool": len(pool_rows), "documents_sealed": len(sealed_rows),
                   "unique_chars": sum(r["n_chars"] for r in doc_rows if not r["is_empty"]),
                   "max_n_chars": max(r["n_chars"] for r in doc_rows)},
        "shards": shard_info,
        "tables": {n: sha256_file(os.path.join(out, n)) for n in
                   ("doc_index_pool.parquet", "doc_index_sealed.parquet", "origins.parquet", "ranks.json")},
    }
    with open(os.path.join(out, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=1)
    log(f"ingest done in {time.time() - t0:.0f}s")
    return manifest


def read_shard(path: str) -> pa.Table:
    return pq.read_table(path)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--zips", required=True)
    ap.add_argument("--dev", required=True)
    ap.add_argument("--subsets", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--old-split", default=None)
    ap.add_argument("--seed", type=int, default=poolmod.SEED)
    ap.add_argument("--pool-bands", type=int, default=poolmod.POOL_BANDS)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--include-sealed-text", action="store_true")
    a = ap.parse_args(argv)
    ingest(a.zips, a.dev, a.subsets, a.out, a.old_split, a.seed, pool_bands=a.pool_bands, workers=a.workers,
           include_sealed_text=a.include_sealed_text)


if __name__ == "__main__":
    sys.exit(main())
