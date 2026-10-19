"""BM25 against closed-form numbers on a 3-chunk corpus (worked out by hand).

chunks: d0 = "a b"  (dl 2)   d1 = "a a c" (dl 3)   d2 = "b c c c" (dl 4)   N = 3, avgdl = 3, k1 = 1.5, b = 0.75
df: a 2, b 2, c 2  ->  idf = ln(1 + (3 - 2 + 0.5) / (2 + 0.5)) = ln 1.6 = 0.4700036
query "a":   d0: tf 1, dl 2: norm = 1.5 (0.25 + 0.75 * 2/3) = 1.125; 1 * 2.5 / 2.125 = 1.176471 -> 0.552945
             d1: tf 2, dl 3: norm = 1.5;                        2 * 2.5 / 3.5   = 1.428571 -> 0.671434; d2: 0
query "b c": d2: b: norm = 1.5 (0.25 + 0.75 * 4/3) = 1.875; 2.5 / 2.875 = 0.869565
                 c: tf 3: 7.5 / 4.875 = 1.538462                          -> (0.869565 + 1.538462) * 0.4700036 = 1.131772
             d1: c: 2.5 / 2.5 = 1 -> 0.470004;   d0: b: 1.176471 -> 0.552945
"""
import math

import numpy as np
import pytest

from evret import bm25 as bm


@pytest.fixture()
def index(tmp_path):
    texts = ["a b", "a a c", "b c c c"]
    out = str(tmp_path / "band")
    bm.build_band(out, 10, [bm.postings_from_texts(texts, 10)])
    return bm.BM25Index([out])


def scores(index, q):
    h = index.query_terms(q)
    return index.score_band(index.bands[0], h, index.idfs(h))


def test_toy_scores_match_closed_form(index):
    assert index.N == 3 and index.avgdl == 3.0
    s = scores(index, "a")
    np.testing.assert_allclose(s, [0.552945, 0.671434, 0.0], atol=2e-5)
    s = scores(index, "b c")
    np.testing.assert_allclose(s, [0.552945, 0.470004, 1.131772], atol=2e-5)
    assert math.isclose(index.idfs(index.query_terms("a"))[index.query_terms("a")[0]], math.log(1.6), rel_tol=1e-12)


def test_repeated_and_unknown_terms(index):
    np.testing.assert_allclose(scores(index, "a a A"), scores(index, "a"))     # unique terms, lower-cased
    assert scores(index, "zzz").sum() == 0.0


def test_postings_structure():
    t, c, f, dl = bm.postings_from_texts(["a b", "a a c"], 5)
    assert dl.tolist() == [2, 3]
    assert sorted(c.tolist()) == [5, 5, 6, 6]                       # postings: (a,5) (b,5) (a,6) (c,6)
    ha = bm.term_hash("a")
    assert sorted(f[(t == np.uint64(ha))].tolist()) == [1, 2]       # tf of "a": 1 in chunk 5, 2 in chunk 6
