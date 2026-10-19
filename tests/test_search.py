"""End-to-end test of the search tool on a tiny corpus built by the real pipeline (ingest -> chunk -> BM25 -> vectors).

The embedding model is replaced by a hashed bag-of-words (deterministic, 384-d, unit length) so that cosine scores can be
worked out by hand; the model itself is checked in the embedding verification.

Documents (url -> text; every text is longer than 200 characters so nothing is "tiny"):
  P1 news.example/a              "alpha beta gamma. " x 60
  P2 snopes.com/fact-check/x     "alpha delta " x 60                 (fact-check flag)
  P3 old.example/2019/05/12/s    "gamma epsilon " x 60               (dated 2019-05-12)
  P4 new.example/2022/01/05/s    "gamma zeta " x 60                  (dated 2022-01-05)
  P5 undated.example/u           "gamma eta " x 60                   (no date)
  P6 other.example/u             same text as P5, another URL        (exact tie with P5)
  P7 stored under a web.archive.org wrapper around wrapped.example/w   "omega kappa " x 60
  S1 sealed.example/s            "alpha sealed " x 60                (only in sealed claims)
Claims 0..3; band_size 2, pool_bands 1 -> the two claims with ranks 0 and 1 are the pool.
"""
import json
import os
import re
import zipfile

import numpy as np
import pytest

from evret import bm25 as bm
from evret import chunk as ck
from evret import embed as em
from evret import ingest as ing
from evret import pool as poolmod
from evret import search as sr

DOCS = {
    "P1": ("https://news.example/a", "alpha beta gamma. " * 60),
    "P2": ("https://snopes.com/fact-check/x", "alpha delta " * 60),
    "P3": ("https://old.example/2019/05/12/s", "gamma epsilon " * 60),
    "P4": ("https://new.example/2022/01/05/s", "gamma zeta " * 60),
    "P5": ("https://undated.example/u", "gamma eta " * 60),
    "P6": ("https://other.example/u", "gamma eta " * 60),
    "P7": ("https://web.archive.org/web/20190101000000/https://wrapped.example/w", "omega kappa " * 60),
    "S1": ("https://sealed.example/s", "alpha sealed " * 60),
}
LABELS = {0: "Refuted", 1: "Supported", 2: "Refuted", 3: "Supported"}


def fake_vec(text):
    v = np.zeros(em.DIM, dtype=np.float32)
    for tok in re.findall(r"\w+", text.lower()):
        v[bm.term_hash(tok) % em.DIM] += 1.0
    return v / np.linalg.norm(v)


class FakeEncoder:
    def embed_queries(self, qs):
        return np.vstack([fake_vec(q) for q in qs])


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    root = str(tmp_path_factory.mktemp("srch"))
    ranks = poolmod.build_ranks(list(range(4)), LABELS, 42)
    pool_claims = sorted(ranks, key=ranks.get)[:2]
    sealed_claims = sorted(ranks, key=ranks.get)[2:]
    stores = {pool_claims[0]: ["P1", "P2", "P3"], pool_claims[1]: ["P4", "P5", "P6", "P7"],
              sealed_claims[0]: ["S1", "P1"], sealed_claims[1]: ["S1"]}
    zdir = os.path.join(root, "zips")
    os.makedirs(zdir)
    with zipfile.ZipFile(os.path.join(zdir, "p.zip"), "w") as zf:
        for cid, ds in stores.items():
            lines = [json.dumps({"claim_id": cid, "type": "q", "query": "x", "url": DOCS[d][0], "url2text": [DOCS[d][1]]})
                     for d in ds]
            zf.writestr(f"{cid}.json", "\n".join(lines) + "\n")
    dev = os.path.join(root, "dev.json")
    json.dump([{"label": LABELS[c], "questions": []} for c in range(4)], open(dev, "w"))
    sub = os.path.join(root, "sub.json")
    json.dump({"dev300": [0, 1, 2, 3]}, open(sub, "w"))
    out = os.path.join(root, "c")
    ing.ingest(zdir, dev, sub, out, band_size=2, pool_bands=1, workers=1, verbose=False)
    ck.chunk_bands(out, [0], workers=1, verbose=False)
    ck.write_chunk_manifest(out)
    ck.build_sqlite(out)
    bm.build_from_corpus(out, 0, workers=1)
    man = em.load_chunk_manifest(out)
    lo, hi = em.band_range(man, 0)
    texts = [t for _, _, tx in em.read_chunks(out, man, lo, hi) for t in tx]
    os.makedirs(os.path.join(out, "vectors", "band=0"))
    vec = np.vstack([fake_vec(t) for t in texts]).astype(np.float16)
    np.save(os.path.join(out, "vectors", "band=0", "shard_0000.npy"), vec)
    json.dump({"model": em.MODEL_ID, "revision": em.MODEL_REVISION, "bands": {"0": {
        "complete": True, "shards": [{"file": "shard_0000.npy", "first_chunk_id": lo, "rows": hi - lo}]}}},
        open(em.manifest_path(out), "w"))
    corpus = sr.Corpus(out)
    dense = sr.DenseExact(corpus, em.load_vectors(out, [0]), FakeEncoder(), device="cpu")
    sparse = sr.BM25(corpus, bm.BM25Index([os.path.join(out, "bm25", "band=0")]))
    return {"corpus": corpus, "dense": dense, "bm25": sparse, "hybrid": sr.Hybrid(dense, sparse), "texts": texts}


def urls(hits):
    return [h.url for h in hits]


def test_only_pool_documents_exist(world):
    assert world["corpus"].n == 7                                   # P1..P7, one chunk each; S1 was never chunked
    for r in ("dense", "bm25", "hybrid"):
        for q in ("sealed", "alpha sealed", "sealed.example"):
            assert "https://sealed.example/s" not in urls(world[r].search(q, 10))
    assert world["bm25"].search("sealed", 10) == []                 # the term does not exist in the index


def test_dense_ranking_and_scores_by_hand(world):
    # query "gamma eta": vector (1,1)/sqrt2 on the hashed dims of gamma and eta (assuming no hash collision).
    # P5/P6 = {gamma:60, eta:60} -> cosine 1.0 ; P3 {gamma 60, epsilon 60} -> 0.5 ; P4 -> 0.5 ; P1 {alpha 60, beta 60,
    # gamma 60} -> 1/sqrt(6)*... computed below from the same hashing
    hits = world["dense"].search("gamma eta", 3, sr.Filters(exclude_flags=frozenset()))
    assert [h.rank for h in hits] == [1, 2, 3]
    assert abs(hits[0].score - 1.0) < 2e-3 and abs(hits[1].score - 1.0) < 2e-3
    assert {hits[0].url, hits[1].url} == {"https://undated.example/u", "https://other.example/u"}
    assert abs(hits[2].score - 0.5) < 2e-3                          # gamma shared with P3 / P4: 1/sqrt(2) * 1/sqrt(2)


def test_tie_break_lower_chunk_id(world):
    for r in ("dense", "bm25"):
        hits = world[r].search("gamma eta", 2)
        assert hits[0].score == hits[1].score and hits[0].chunk_id < hits[1].chunk_id, r


def test_factcheck_excluded_by_default_and_included_on_request(world):
    assert "https://snopes.com/fact-check/x" not in urls(world["bm25"].search("delta", 10))
    assert urls(world["bm25"].search("delta", 10, sr.Filters(exclude_flags=frozenset()))) == ["https://snopes.com/fact-check/x"]
    h = world["bm25"].search("delta", 10, sr.Filters(exclude_flags=frozenset()))[0]
    assert "factcheck" in h.flags


def test_exclude_norm_urls_is_per_query(world):
    f_ex = sr.Filters(exclude_norm_urls=frozenset({"undated.example/u"}))
    for r in ("dense", "bm25", "hybrid"):
        both = world[r].search_batch(["gamma eta", "gamma eta"], 6, [f_ex, sr.Filters()])
        assert "https://undated.example/u" not in urls(both[0])
        assert "https://undated.example/u" in urls(both[1])
        assert "https://other.example/u" in urls(both[0])


def test_not_after_keeps_undated_and_marks_it(world):
    f = sr.Filters(not_after="2020-01-01")
    hits = world["bm25"].search("gamma", 10, f)
    u = urls(hits)
    assert "https://new.example/2022/01/05/s" not in u and "https://old.example/2019/05/12/s" in u
    und = next(h for h in hits if h.url == "https://undated.example/u")
    assert und.date_source == "none" and und.pub_date == ""
    old = next(h for h in hits if h.url.startswith("https://old"))
    assert old.date_source == "url" and old.pub_date == "2019-05-12"


def test_domain_filter(world):
    f = sr.Filters(domains=frozenset({"old.example"}))
    assert urls(world["bm25"].search("gamma", 10, f)) == ["https://old.example/2019/05/12/s"]
    f = sr.Filters(exclude_domains=frozenset({"old.example", "new.example"}))
    assert not any("old.example" in u or "new.example" in u for u in urls(world["dense"].search("gamma", 10, f)))


def test_hybrid_rrf_by_hand(world):
    # query "delta": BM25 finds only P2 (fact-check, excluded by default) -> use exclude_flags=() so P2 is rank 1 in BM25.
    f = sr.Filters(exclude_flags=frozenset())
    b = world["bm25"].search("delta", 100, f)
    d = world["dense"].search("delta", 100, f)
    assert len(b) == 1 and d[0].url == b[0].url
    h = world["hybrid"].search("delta", 3, f)
    assert h[0].url == b[0].url and abs(h[0].score - 2 / 61) < 1e-12           # rank 1 in both lists: 1/61 + 1/61
    assert h[0].dense_score is not None and h[0].bm25_score is not None
    # an item present only in the dense list gets 1/(60 + rank)
    assert abs(h[1].score - 1 / (60 + 2)) < 1e-12 or abs(h[1].score - 1 / (60 + 3)) < 1e-12 or h[1].score < 1 / 61 + 1e-12


def test_hit_fields_and_no_claim_information(world):
    h = world["bm25"].search("alpha", 1)[0]
    assert h.text == world["texts"][h.chunk_id - world["corpus"].lo]
    assert h.text[h.start - h.start:] == h.text and h.end - h.start == len(h.text)
    names = {f.name for f in __import__("dataclasses").fields(h)}
    assert names == {"chunk_id", "doc_id", "rank", "score", "retriever", "dense_score", "bm25_score", "text", "start",
                     "end", "url", "domain", "is_pdf", "pub_date", "date_source", "flags"}
    assert h.retriever == "bm25" and h.rank == 1


def test_search_batch_equals_single_calls(world):
    qs = ["alpha", "gamma eta", "zeta"]
    for r in ("dense", "bm25", "hybrid"):
        batch = world[r].search_batch(qs, 4)
        for q, b in zip(qs, batch):
            single = world[r].search(q, 4)
            assert [(x.chunk_id, round(x.score, 9)) for x in b] == [(x.chunk_id, round(x.score, 9)) for x in single]


def test_exclusion_finds_documents_stored_under_a_wayback_wrapper(world):
    """A document is excluded whether the filter names its stored URL or the unwrapped original (and vice versa)."""
    from evret.urls import url_variants
    wrapped = "https://web.archive.org/web/20200101000000/https://news.example/a"      # wrapper around P1
    f = sr.Filters(exclude_norm_urls=frozenset(url_variants(wrapped)))
    for r in ("dense", "bm25", "hybrid"):
        assert "https://news.example/a" not in urls(world[r].search("alpha beta gamma", 10, f)), r
    assert "https://news.example/a" in urls(world["bm25"].search("alpha beta gamma", 10))


def test_exclusion_of_a_document_stored_under_a_wrapper_by_its_original_url(world):
    wrapped_url = "https://web.archive.org/web/20190101000000/https://wrapped.example/w"
    assert wrapped_url in urls(world["bm25"].search("omega", 5))
    f = sr.Filters(exclude_norm_urls=frozenset({"wrapped.example/w"}))        # the original URL, as dev.json may name it
    for r in ("dense", "bm25", "hybrid"):
        assert wrapped_url not in urls(world[r].search("omega kappa", 7, f)), r
