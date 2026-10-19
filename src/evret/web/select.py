"""WS4 - first-pass passage selection (WD5): chunk -> embed (cached per page) -> dense cosine + BM25 with POOL statistics -> RRF.

Everything that defines a score is the corpus tool's definition:
  chunker      evret.chunk.chunk_document (pack_200_250, 500-token / 5,000-char caps), documents < 200 chars are not chunked (D8)
  embedding    evret.embed.Encoder: BGE-small, pinned revision, CLS pooling, L2-normalised, queries with the instruction (D10).
               Passages are COMPUTED here in fp32 on the CPU (the GPU belongs to another job) and STORED as float16 like the corpus.
  BM25         k1 = 1.5, b = 0.75, regex \\w+ on lower-cased text, Lucene idf; N, avgdl and df come from the corpus pool (D11, D13),
               so a web passage gets the score it would get if it were part of the pool.
  fusion       RRF k = 60, equal weights, top-100 of each list (evret.search.Hybrid); ties -> lower ordinal (input order).
The cross-encoder is NOT here (separate shared block).
"""
from __future__ import annotations

import json
import math
import time
from collections import Counter
from dataclasses import dataclass

import numpy as np

from evret import bm25 as bm
from evret.chunk import chunk_document
from evret.embed import MODEL_REVISION
from evret.search import RRF_K
from evret.web.pagecache import PageCache

CHUNKER_VERSION = "pack_200_250/v1"
TINY_CHARS = 200
TOP_N = 50
DEPTH = 100


# ------------------------------------------------------------------------------------------------ pool statistics
class PoolStats:
    """N, avgdl and document frequencies of the corpus pool. df of a term is looked up in the index (term offsets only; no
    postings are read) the first time it is needed and remembered, so a run can freeze exactly what it used."""

    def __init__(self, N: int, avgdl: float, df: dict | None = None, index: "bm.BM25Index | None" = None):
        self.N, self.avgdl, self.df, self.index = N, avgdl, dict(df or {}), index

    @classmethod
    def from_index(cls, index: "bm.BM25Index") -> "PoolStats":
        return cls(index.N, index.avgdl, {}, index)

    @classmethod
    def from_frozen(cls, d: dict) -> "PoolStats":
        return cls(d["N"], d["avgdl"], {int(k): v for k, v in d["df"].items()}, None)

    def freeze(self) -> dict:
        return {"N": self.N, "avgdl": self.avgdl, "df": {str(k): v for k, v in sorted(self.df.items())}}

    def _df(self, h: int) -> int:
        if h not in self.df:
            if self.index is None:
                raise KeyError(f"term {h} not in the frozen statistics")
            n = 0
            for band in self.index.bands:
                s = self.index._slice(band, h)
                if s:
                    n += int(s[1] - s[0])
            self.df[h] = n
        return self.df[h]

    def idf(self, h: int) -> float:
        df = self._df(h)
        return math.log(1.0 + (self.N - df + 0.5) / (df + 0.5)) if df else 0.0


def bm25_scores(query: str, passages: list[str], stats: PoolStats, k1: float = bm.K1, b: float = bm.B) -> np.ndarray:
    """score(d) = sum_t idf(t) * tf (k1+1) / (tf + k1 (1 - b + b dl / avgdl)) over the UNIQUE query terms (same as evret.bm25)."""
    hashes = sorted({bm.term_hash(t) for t in bm.tokenize(query)})
    idf = {h: stats.idf(h) for h in hashes}
    by_tok = {t: bm.term_hash(t) for t in sorted(set(bm.tokenize(query)))}      # sorted: float sums must not depend on set order / PYTHONHASHSEED
    out = np.zeros(len(passages))
    for i, text in enumerate(passages):
        toks = bm.tokenize(text)
        cnt = Counter(toks)
        norm = k1 * (1.0 - b + b * len(toks) / stats.avgdl)
        s = 0.0
        for t, h in by_tok.items():
            tf = cnt.get(t, 0)
            if tf and idf[h]:
                s += idf[h] * tf * (k1 + 1.0) / (tf + norm)
        out[i] = s
    return out


# ------------------------------------------------------------------------------------------------ chunk + embed per page
@dataclass
class Prepared:
    spans: list            # [(start, end, n_tokens, split, hard)]
    vectors: np.ndarray    # float16 [n, 384]


class PassageStore:
    """Chunks and vectors per page, cached so that a page is processed only once (WD6)."""

    def __init__(self, cache: PageCache, enc, count, enc_id: str = MODEL_REVISION):
        self.cache, self.enc, self.count, self.enc_id = cache, enc, count, enc_id
        self.t_chunk = 0.0          # seconds spent in the chunker (the encoder is timed by its caller)
        cache.ensure_table("CREATE TABLE IF NOT EXISTS chunks (key TEXT PRIMARY KEY, spans TEXT, vecs BLOB, n INTEGER)")

    def _key(self, page_key: str) -> str:
        return f"{page_key}|{CHUNKER_VERSION}|{self.enc_id}"

    def get(self, page_key: str, text: str, allow_compute: bool = True) -> Prepared:
        key = self._key(page_key)
        rows = self.cache.execute("SELECT spans, vecs, n FROM chunks WHERE key=?", (key,))
        if rows:
            spans, vecs, n = rows[0]
            arr = np.frombuffer(vecs, dtype=np.float16).reshape(n, -1).copy() if n else np.zeros((0, 384), np.float16)
            return Prepared([tuple(s) for s in json.loads(spans)], arr)
        if not allow_compute:
            raise KeyError(f"passages not cached: {key}")
        t0 = time.perf_counter()
        spans = [] if len(text) < TINY_CHARS else list(chunk_document(text, self.count))
        self.t_chunk += time.perf_counter() - t0
        vecs = (self.enc.embed_passages([text[s:e] for s, e, *_ in spans]).astype(np.float16)
                if spans else np.zeros((0, 384), np.float16))
        self.cache.execute("INSERT OR REPLACE INTO chunks VALUES (?,?,?,?)",
                           (key, json.dumps(spans), vecs.tobytes(), len(spans)))
        return Prepared(spans, vecs)


# ------------------------------------------------------------------------------------------------ ranking and fusion
def _order(scores: np.ndarray, ords: np.ndarray, keep: np.ndarray | None, depth: int) -> np.ndarray:
    """Indices sorted by (-score, ord), restricted to `keep`, first `depth`."""
    idx = np.nonzero(keep)[0] if keep is not None else np.arange(len(scores))
    o = np.lexsort((ords[idx], -scores[idx]))[:depth]
    return idx[o]


def rrf(lists: list[np.ndarray], ords: np.ndarray, k: int = RRF_K) -> list[tuple[int, float]]:
    fused: dict[int, float] = {}
    for lst in lists:
        for r, i in enumerate(lst, start=1):
            fused[int(i)] = fused.get(int(i), 0.0) + 1.0 / (k + r)
    return sorted(fused.items(), key=lambda kv: (-kv[1], ords[kv[0]]))


@dataclass
class Scored:
    index: int                 # position in the candidate list
    hybrid: float
    dense: float
    bm25: float | None


def select(query: str, passages: list[str], vectors: np.ndarray, enc, stats: PoolStats, top_n: int = TOP_N,
           depth: int = DEPTH, rrf_k: int = RRF_K) -> list[Scored]:
    """passages/vectors: all candidate chunks of all kept pages, in a fixed input order (= tie-break order)."""
    if not passages:
        return []
    depth = max(depth, top_n)
    ords = np.arange(len(passages))
    q = enc.embed_queries([query])[0].astype(np.float32)
    dense = vectors.astype(np.float32) @ q
    sparse = bm25_scores(query, passages, stats)
    d_list = _order(dense, ords, None, depth)
    s_list = _order(sparse, ords, sparse > 0, depth)             # like the corpus: zero-score chunks are not candidates
    fused = rrf([d_list, s_list], ords, rrf_k)[:top_n]
    return [Scored(i, sc, float(dense[i]), float(sparse[i]) if sparse[i] > 0 else None) for i, sc in fused]
