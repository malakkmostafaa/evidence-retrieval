"""WS4 tests: BM25 with pool statistics by hand, RRF by hand, the per-page passage cache, and the EQUIVALENCE test:
web scoring with corpus statistics == the corpus tool's scoring for the same passages (tiny corpus built by the real pipeline)."""
import math

import numpy as np
import pytest
from test_search import DOCS, FakeEncoder, fake_vec, world  # noqa: F401  (world is a module-scoped fixture)

from evret import bm25 as bm
from evret import chunk as ck
from evret import search as sr
from evret.web.hit import WebHit, stable_id
from evret.web.pagecache import PageCache
from evret.web.select import PassageStore, PoolStats, bm25_scores, rrf, select


class FakeEnc(FakeEncoder):
    def __init__(self):
        self.calls = 0

    def embed_passages(self, texts):
        self.calls += 1
        return np.vstack([fake_vec(t) for t in texts]) if texts else np.zeros((0, 384), np.float32)


H = bm.term_hash


# ------------------------------------------------------------------------------------------------ BM25 by hand
def test_bm25_with_given_pool_statistics_matches_the_closed_form():
    # N = 10 chunks, avgdl = 4, df(alpha) = 2, df(beta) = 5.   Passage "alpha alpha beta gamma": dl = 4, tf(alpha) = 2, tf(beta) = 1
    stats = PoolStats(10, 4.0, {H("alpha"): 2, H("beta"): 5, H("zzz"): 0})
    idf_a, idf_b = math.log(1 + (10 - 2 + 0.5) / (2 + 0.5)), math.log(1 + (10 - 5 + 0.5) / (5 + 0.5))
    norm = 1.5 * (1 - 0.75 + 0.75 * 4 / 4)                                     # = 1.5
    expect = idf_a * 2 * 2.5 / (2 + norm) + idf_b * 1 * 2.5 / (1 + norm)
    sc = bm25_scores("alpha beta alpha zzz", ["alpha alpha beta gamma", "gamma gamma gamma gamma", "alpha"], stats)
    assert abs(sc[0] - expect) < 1e-12                                          # duplicate query term counted once, df=0 term adds 0
    assert sc[1] == 0.0
    assert bm25_scores("zzz", ["zzz zzz zzz"], stats)[0] == 0.0                 # a term absent from the pool (df = 0) has idf 0, not a huge idf
    norm1 = 1.5 * (1 - 0.75 + 0.75 * 1 / 4)                                     # dl = 1
    assert abs(sc[2] - idf_a * 1 * 2.5 / (1 + norm1)) < 1e-12


def test_frozen_stats_roundtrip_and_missing_term_fails_loudly():
    s = PoolStats(10, 4.0, {H("alpha"): 2})
    f = PoolStats.from_frozen(__import__("json").loads(__import__("json").dumps(s.freeze())))
    assert f.idf(H("alpha")) == s.idf(H("alpha")) and (f.N, f.avgdl) == (10, 4.0)
    with pytest.raises(KeyError):
        f.idf(H("beta"))


# ------------------------------------------------------------------------------------------------ RRF by hand
def test_rrf_by_hand_and_tie_order():
    ords = np.arange(4)
    # lists: dense a,b,c = 0,1,2 ; sparse c,b = 2,1.  a = 1/61 ; b = 1/62 + 1/62 ; c = 1/63 + 1/61
    got = rrf([np.array([0, 1, 2]), np.array([2, 1])], ords)
    assert [i for i, _ in got] == [2, 1, 0]
    assert abs(got[0][1] - (1 / 63 + 1 / 61)) < 1e-15 and abs(got[1][1] - 2 / 62) < 1e-15 and abs(got[2][1] - 1 / 61) < 1e-15
    tie = rrf([np.array([0, 1]), np.array([1, 0])], ords)                       # both 1/61 + 1/62 -> lower ordinal first
    assert [i for i, _ in tie] == [0, 1]
    assert [i for i, _ in rrf([np.array([0, 1])], ords, k=1)] == [0, 1] and abs(rrf([np.array([0])], ords, k=1)[0][1] - 0.5) < 1e-15


class QueryEnc:
    """Passage vectors are set by hand; the query vector is e1 (so the answer depends on using embed_queries)."""
    def embed_queries(self, qs):
        v = np.zeros((len(qs), 384), np.float32)
        v[:, 1] = 1.0
        return v

    def embed_passages(self, texts):
        v = np.zeros((len(texts), 384), np.float32)
        v[:, 0] = 1.0
        return v


def test_dense_scores_use_the_query_encoder_and_depth_grows_with_top_n():
    texts = ["aaa", "bbb", "ccc"]
    vecs = np.zeros((3, 384), np.float16)
    vecs[0, 0], vecs[1, 1], vecs[2, 1], vecs[2, 0] = 1.0, 1.0, 0.6, 0.8                # cosines with e1: 0, 1, 0.6
    out = select("qqq", texts, vecs, QueryEnc(), PoolStats(10, 3.0, {H("qqq"): 0}), top_n=3, depth=1)
    assert [o.index for o in out] == [1, 2, 0] or len(out) == 3                      # depth=1 is raised to top_n=3
    assert len(out) == 3 and out[0].index == 1 and abs(out[0].dense - 1.0) < 1e-3 and abs(out[1].dense - 0.6) < 1e-3


def test_select_top_n_cut_zero_bm25_not_a_candidate_and_empty_input():
    enc = FakeEnc()
    texts = ["alpha beta " * 5, "gamma delta " * 5, "alpha gamma " * 5]
    vecs = enc.embed_passages(texts).astype(np.float16)
    stats = PoolStats(10, 10.0, {H("alpha"): 1, H("beta"): 1, H("gamma"): 1, H("delta"): 1})
    out = select("alpha", texts, vecs, enc, stats, top_n=2)
    assert len(out) == 2 and out[0].index == 0                                  # best on both lists
    allr = select("alpha", texts, vecs, enc, stats, top_n=3)
    by = {s.index: s for s in allr}
    assert by[1].bm25 is None and by[0].bm25 > 0 and by[2].bm25 > 0               # 'gamma delta' has no query term: dense-only candidate
    assert select("alpha", [], np.zeros((0, 384), np.float16), enc, stats) == []


# ------------------------------------------------------------------------------------------------ passage cache
def test_page_is_chunked_and_embedded_once_and_tiny_pages_are_skipped(tmp_path):
    enc, count = FakeEnc(), ck.make_counter(ck.tokenizer_file())
    store = PassageStore(PageCache(str(tmp_path / "c")), enc, count, enc_id="fake")
    text = "alpha beta gamma. " * 60
    a = store.get("u|live", text)
    b = store.get("u|live", text)
    assert enc.calls == 1 and a.spans == b.spans and np.array_equal(a.vectors, b.vectors) and a.vectors.dtype == np.float16
    assert len(a.spans) == 1 and text[a.spans[0][0]:a.spans[0][1]].startswith("alpha")
    assert store.get("tiny|live", "x" * 199).spans == [] and enc.calls == 1      # < 200 chars: not chunked, no model call
    PassageStore(store.cache, enc, count, enc_id="other-model").get("u|live", text)
    assert enc.calls == 2                                                       # a different encoder id must not reuse the vectors
    with pytest.raises(KeyError):
        store.get("new|live", text, allow_compute=False)


def test_webhit_extends_hit_and_ids_are_stable():
    h = WebHit(chunk_id=1, doc_id=2, rank=1, score=0.5, retriever="web_hybrid", dense_score=0.1, bm25_score=None, text="t",
               start=0, end=1, url="u", domain="d", is_pdf=False, pub_date="2019-01-01", date_source="htmldate")
    assert isinstance(h, sr.Hit) and h.source == "web" and h.flags == [] and h.vector is None
    assert stable_id("u", "live", 0) == stable_id("u", "live", 0) != stable_id("u", "live", 1)
    assert 0 <= stable_id("x") < 2 ** 63


# ------------------------------------------------------------------------------------------------ equivalence with the corpus tool
QUERIES = ["gamma eta", "alpha beta", "gamma", "omega kappa", "delta", "alpha sealed", "nothing matches here qqq"]


def test_web_scoring_with_corpus_statistics_equals_corpus_hybrid(world, tmp_path):  # noqa: F811
    corpus, hybrid = world["corpus"], world["hybrid"]
    text_by_url = {u: t for u, t in DOCS.values()}
    enc, count = FakeEnc(), ck.make_counter(ck.tokenizer_file())
    store = PassageStore(PageCache(str(tmp_path / "c")), enc, count, enc_id="fake")
    # the web side receives the pages in the corpus document order and chunks them itself
    passages, vecs, urls_of = [], [], []
    for url in corpus.docs["url"]:
        text = text_by_url[url]
        prep = store.get(url + "|live", text)
        passages += [text[s:e] for s, e, *_ in prep.spans]
        vecs.append(prep.vectors)
        urls_of += [url] * len(prep.spans)
    vecs = np.vstack(vecs)
    assert passages == world["texts"]                                           # same chunker -> same passages
    stats = PoolStats.from_index(world["bm25"].index)
    f = sr.Filters(exclude_flags=frozenset())
    for q in QUERIES:
        ref = hybrid.search(q, 7, f)
        got = select(q, passages, vecs, enc, stats, top_n=7)
        assert [urls_of[s.index] for s in got] == [h.url for h in ref], q       # same passages in the same order
        for s, h in zip(got, ref):
            assert abs(s.hybrid - h.score) < 1e-12, q                           # RRF score
            assert abs(s.dense - h.dense_score) < 1e-5, q
            assert (s.bm25 is None) == (h.bm25_score is None), q
            if h.bm25_score is not None:
                assert abs(s.bm25 - h.bm25_score) < 1e-4 * max(1.0, h.bm25_score), q
    # df of the terms we used came from the index offsets: same numbers as the corpus idf
    idx = world["bm25"].index
    hs = idx.query_terms("gamma eta alpha")
    for h, v in idx.idfs(hs).items():
        assert abs(stats.idf(h) - v) < 1e-12
    assert stats.N == idx.N == 7 and abs(stats.avgdl - idx.avgdl) < 1e-12
