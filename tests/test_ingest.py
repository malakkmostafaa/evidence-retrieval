"""Ingest tests on the 6-claim fixture of tests/ks_fixture.py; band_size=2, pool_bands=2 -> ranks 0-3 pool, 4-5 sealed.

Hand-computed expectations (min_rank(doc) = smallest rank among claims whose store contains it, r(c) = rank of claim c):
  A  : min(r0, r3)   B : r1   C : min(r2, r4)   D : r5   E : min(r0, r1)   A2 : r3   F : r2   G : r1
Documents = 8 keys (A and A2 differ in text, same URL). Non-empty = 7. Records = 3+3+2+2+1+1 = 12.
"""
import ast
import glob
import json
import os
import re

import pyarrow.parquet as pq
import pytest

from evret import ingest as ing
from ks_fixture import STORES, TEXT, URL, build, joined

KEYS = ["A", "B", "C", "D", "E", "A2", "F", "G"]


def minrank(doc, r):
    return min(r[c] for c, ds in STORES.items() if doc in ds)


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    root = str(tmp_path_factory.mktemp("ks"))
    zdir, dev, sub = build(root)
    out = os.path.join(root, "out")
    man = ing.ingest(zdir, dev, sub, out, band_size=2, pool_bands=2, workers=2, verbose=False)
    r = {int(k): v for k, v in json.load(open(os.path.join(out, "ranks.json"))).items()}
    return {"zdir": zdir, "dev": dev, "sub": sub, "out": out, "man": man, "ranks": r}


def all_docs(out):
    rows = []
    for name in ("doc_index_pool.parquet", "doc_index_sealed.parquet"):
        rows += pq.read_table(os.path.join(out, name)).to_pylist()
    return sorted(rows, key=lambda x: x["doc_id"])


def doc_of(rows, key):
    k = (ing.normalize_url(URL[key]), ing.content_hash(joined(key)))
    return next(r for r in rows if (r["norm_url"], r["content_hash"]) == k)


def shard_texts(out):
    texts = {}
    for f in glob.glob(out + "/documents/*/*.parquet"):
        for r in pq.read_table(f).to_pylist():
            texts[r["doc_id"]] = ing.decode_text(r["text_utf8"])
    return texts


def test_counts(run):
    c = run["man"]["counts"]
    assert c["records"] == 12 and c["documents"] == 8 and c["documents_nonempty"] == 7
    assert c["max_n_chars"] == max(len(joined(k)) for k in KEYS)


def test_min_rank_and_shared_attribution(run):
    rows = all_docs(run["out"])
    r = run["ranks"]
    for key in KEYS:
        assert doc_of(rows, key)["min_rank"] == minrank(key, r), key
    o = pq.read_table(os.path.join(run["out"], "origins.parquet")).to_pylist()
    a = doc_of(rows, "A")["doc_id"]
    assert sorted({x["claim_id"] for x in o if x["doc_id"] == a}) == [0, 3]      # both claims kept as origins
    assert len(o) == 12


def test_ordering_and_bands(run):
    rows = all_docs(run["out"])
    assert [r["doc_id"] for r in rows] == list(range(8))
    mr = [r["min_rank"] for r in rows]
    assert mr == sorted(mr)                                     # documents are numbered in rank order
    for r in rows:
        assert r["band"] == r["min_rank"] // 2                  # band boundaries at ranks 2 and 4
    pool = pq.read_table(os.path.join(run["out"], "doc_index_pool.parquet")).to_pylist()
    assert all(x["min_rank"] < 4 for x in pool)
    assert sorted(x["doc_id"] for x in pool) == list(range(len(pool)))         # pool ids come first, contiguous
    d = {k: doc_of(rows, k)["doc_id"] for k in KEYS}
    r = run["ranks"]
    if minrank("A", r) == r[0] and minrank("E", r) == r[0]:     # claim 0 lists A before E
        assert d["A"] < d["E"]
    if minrank("B", r) == r[1] and minrank("G", r) == r[1]:     # claim 1 lists B, E, G
        assert d["B"] < d["G"]


def test_sealed_has_no_text(run):
    out = run["out"]
    sealed = pq.read_table(os.path.join(out, "doc_index_sealed.parquet"))
    assert "text_utf8" not in sealed.column_names and sealed.num_rows >= 1
    ranks_in_shards = {int(re.search(r"rank_(\d+)", f).group(1)) for f in glob.glob(out + "/documents/*/*.parquet")}
    assert ranks_in_shards and max(ranks_in_shards) < 4
    assert not set(shard_texts(out)) & set(sealed.column("doc_id").to_pylist())


def test_text_byte_exact_with_specials(run):
    rows = all_docs(run["out"])
    texts = shard_texts(run["out"])
    for key in ("A", "A2", "B", "C", "E", "F", "G"):
        did = doc_of(rows, key)["doc_id"]
        if did in texts:
            assert texts[did] == joined(key), key
    assert doc_of(rows, "C")["doc_id"] in texts               # C is also in claim 2 or 4; one of them is pool
    t = texts[doc_of(rows, "C")["doc_id"]]
    assert " " in t and "\x00" in t and "\U0001F600" in t and "\ud800" in t
    c = next(r for f in glob.glob(run["out"] + "/documents/*/*.parquet") for r in pq.read_table(f).to_pylist()
             if r["doc_id"] == doc_of(rows, "C")["doc_id"])
    assert (c["n_u2028"], c["n_nul"], c["n_nonbmp"], c["has_surrogate"]) == (10, 10, 10, True)


def test_flags(run):
    rows = all_docs(run["out"])
    e, g, f, c = (doc_of(rows, k) for k in ("E", "G", "F", "C"))
    assert e["is_empty"] and not e["is_tiny"]
    assert g["is_tiny"] and g["is_factcheck"] and not g["is_empty"]
    assert f["is_pdf"]
    assert c["date_source"] == "none" and c["pub_date"] == ""


def test_resume_gives_identical_hashes(run):
    out = run["out"]
    before = {s["file"]: s["sha256"] for s in run["man"]["shards"]}
    tables = dict(run["man"]["tables"])
    os.remove(os.path.join(out, sorted(before)[0]))                         # simulate a kill: lost shard,
    os.remove(sorted(glob.glob(out + "/work/pass1/*.pkl"))[1])              # lost pass-1 cache,
    with open(os.path.join(out, "documents", "stray.parquet.tmp"), "wb") as f:   # half-written temp file
        f.write(b"half")
    man = ing.ingest(run["zdir"], run["dev"], run["sub"], out, band_size=2, pool_bands=2, workers=2, verbose=False)
    assert {s["file"]: s["sha256"] for s in man["shards"]} == before
    assert man["tables"] == tables


# ------------------------------------------------------------------------------------------------ guard
FORBIDDEN = re.compile(r"origins|claim_id|claim_rank|qtype|^type$|^query_type$", re.I)
ALLOWED_PREFIXES = ("ingest", "eval", "pool", "audit", "metrics_cov")        # the only modules that may know claims/origins


def offenders_in(source: str, fn: str = "x.py"):
    out = []
    for node in ast.walk(ast.parse(source)):
        names = []
        if isinstance(node, ast.Name):
            names = [node.id]
        elif isinstance(node, ast.Attribute):
            names = [node.attr]
        elif isinstance(node, ast.arg):
            names = [node.arg]
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and len(node.value) < 40:
            names = [node.value]
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] + [getattr(node, "module", None) or ""]
        out += [(fn, getattr(node, "lineno", 0), n) for n in names if FORBIDDEN.search(n)]
    return out


def test_guard_no_origin_access_outside_ingest_eval():
    src = os.path.join(os.path.dirname(__file__), "..", "src", "evret")
    offenders = []
    for fn in sorted(os.listdir(src)):
        if fn.endswith(".py") and fn != "__init__.py" and not fn.startswith(ALLOWED_PREFIXES):
            with open(os.path.join(src, fn), encoding="utf-8") as f:
                offenders += offenders_in(f.read(), fn)
    assert not offenders, offenders


def test_guard_detects_violations():
    assert offenders_in("import pyarrow.parquet as pq\nx = pq.read_table('origins.parquet')\n")
    assert offenders_in("def f(claim_id): pass\n")
    assert offenders_in("row['type']\n")
    assert not offenders_in("def search(query, k): return [query]\n")
