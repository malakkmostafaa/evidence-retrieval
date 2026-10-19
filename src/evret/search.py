"""S4 - the corpus search tool: `search(query, k, filters) -> list[Hit]` with three retrievers.

DenseExact  exact inner product over all float16 vectors of the finished bands (streamed in shards, GPU if present)
BM25        see evret.bm25 (disk-backed, per band)
Hybrid      reciprocal rank fusion (k = 60, equal weights) of the top-100 of the two above

Hits carry no claim id and no origin information. Sealed bands never exist in the index (they are never chunked).
Ties are broken by the lower chunk_id everywhere.
"""
from __future__ import annotations

import dataclasses
import json
import os
import sqlite3
from dataclasses import dataclass, field

import numpy as np
import pyarrow.parquet as pq

from evret import bm25 as bm
from evret.chunk import FLAG_FACTCHECK, FLAG_HARD, FLAG_PDF, FLAG_SPLIT
from evret.ingest import decode_text
from evret.urls import canonical

FLAG_NAMES = {FLAG_FACTCHECK: "factcheck", FLAG_PDF: "pdf", FLAG_SPLIT: "split", FLAG_HARD: "hardcap"}
FLAG_BY_NAME = {v: k for k, v in FLAG_NAMES.items()}
RRF_K = 60


@dataclass
class Filters:
    exclude_norm_urls: frozenset = frozenset()              # per query (built by the evaluation layer)
    exclude_flags: frozenset = frozenset({"factcheck", "tiny"})
    domains: frozenset | None = None                         # keep only these hosts (and their subdomains)
    exclude_domains: frozenset = frozenset()
    not_after: str | None = None                             # "YYYY-MM-DD"; undated pages are kept

    def key(self):                                           # everything except the per-query URL list
        return (tuple(sorted(self.exclude_flags)), None if self.domains is None else tuple(sorted(self.domains)),
                tuple(sorted(self.exclude_domains)), self.not_after)


@dataclass
class Hit:
    chunk_id: int
    doc_id: int
    rank: int
    score: float
    retriever: str
    dense_score: float | None
    bm25_score: float | None
    text: str
    start: int
    end: int
    url: str
    domain: str
    is_pdf: bool
    pub_date: str
    date_source: str
    flags: list = field(default_factory=list)


def _earliest(d: str) -> str:
    return d + "-01" * (3 - d.count("-") - 1) if d else ""


class Corpus:
    """Metadata of the chunks and documents of the finished pool bands (no vectors, no postings)."""

    def __init__(self, root: str, bands: list[int] | None = None):
        self.root = root
        man = json.load(open(os.path.join(root, "chunks_manifest.json"), encoding="utf-8"))
        ing = json.load(open(os.path.join(root, "manifest.json"), encoding="utf-8"))
        pool_bands = ing["config"]["pool_bands"]
        files = [e for e in man["files"]
                 if bands is None or int(e["file"].split("band=")[1].split("/")[0]) in bands]
        for e in files:
            if int(e["file"].split("band=")[1].split("/")[0]) >= pool_bands:
                raise RuntimeError("a sealed band is present in the chunk table")
        self.bands = sorted({int(e["file"].split("band=")[1].split("/")[0]) for e in files})
        cols = ["doc_id", "start", "end", "flags"]
        parts = [pq.read_table(os.path.join(root, e["file"]), columns=cols) for e in files]
        self.first_ids = [e["first_chunk_id"] for e in files]
        self.lo = files[0]["first_chunk_id"] if files else 0
        self.n = sum(e["rows"] for e in files)
        for e, nxt in zip(files, files[1:]):
            if e["first_chunk_id"] + e["rows"] != nxt["first_chunk_id"]:
                raise RuntimeError("chunk files are not contiguous (a band is missing)")
        self.doc_id = np.concatenate([t.column("doc_id").to_numpy() for t in parts]).astype(np.int64)
        self.start = np.concatenate([t.column("start").to_numpy() for t in parts])
        self.end = np.concatenate([t.column("end").to_numpy() for t in parts])
        self.flags = np.concatenate([t.column("flags").to_numpy() for t in parts]).astype(np.int16)
        d = pq.read_table(os.path.join(root, "doc_index_pool.parquet"),
                          columns=["doc_id", "norm_url", "url", "host", "is_pdf", "pub_date", "date_source",
                                   "is_factcheck", "is_tiny"]).to_pydict()
        self.docs = d
        self.url_to_docs: dict[str, list[int]] = {}
        for did, u in zip(d["doc_id"], d["norm_url"]):               # a document is found under its stored URL and
            for key in {u, canonical(u)}:                           # under the unwrapped (Wayback) original URL
                self.url_to_docs.setdefault(key, []).append(did)
        self._masks: dict = {}
        self.db = sqlite3.connect(f"file:{os.path.join(root, 'chunk_text.sqlite')}?mode=ro", uri=True,
                                  check_same_thread=False)

    # ------------------------------------------------------------------------------------ filters
    def base_mask(self, f: Filters) -> np.ndarray:
        """bool[n]: chunk allowed by the shared (non per-query) filters; index = chunk_id - lo."""
        key = f.key()
        if key in self._masks:
            return self._masks[key]
        m = np.ones(self.n, dtype=bool)
        for name in f.exclude_flags:
            if name in FLAG_BY_NAME:
                m &= (self.flags & FLAG_BY_NAME[name]) == 0
        need_doc = f.domains is not None or f.exclude_domains or f.not_after
        if need_doc:
            host = self.docs["host"]
            ok = np.ones(len(host), dtype=bool)
            if f.domains is not None:
                ok &= np.array([any(h == x or h.endswith("." + x) for x in f.domains) for h in host])
            if f.exclude_domains:
                ok &= ~np.array([any(h == x or h.endswith("." + x) for x in f.exclude_domains) for h in host])
            if f.not_after:
                pd_ = self.docs["pub_date"]
                ok &= np.array([(not p) or _earliest(p) <= f.not_after for p in pd_])
            m &= ok[self.doc_id]
        self._masks[key] = m
        return m

    def excluded_ranges(self, f: Filters) -> list[tuple[int, int]]:
        """Local chunk index ranges [a, b) of the documents whose normalised URL is excluded."""
        out = []
        for u in f.exclude_norm_urls:
            for did in self.url_to_docs.get(u, ()):
                a = int(np.searchsorted(self.doc_id, did, "left"))
                b = int(np.searchsorted(self.doc_id, did, "right"))
                if b > a:
                    out.append((a, b))
        return out

    def apply_exclusions(self, scores: np.ndarray, ranges, offset: int, value: float):
        """scores covers local indices [offset, offset + len)."""
        for a, b in ranges:
            a, b = max(a, offset) - offset, min(b, offset + len(scores)) - offset
            if b > a:
                scores[a:b] = value

    # ------------------------------------------------------------------------------------ hits
    def texts(self, chunk_ids: list[int]) -> list[str]:
        out = []
        for c in chunk_ids:
            row = self.db.execute("SELECT text FROM chunk_text WHERE chunk_id = ?", (int(c),)).fetchone()
            out.append(decode_text(row[0]))
        return out

    def make_hits(self, ids, scores, retriever, dense=None, bm25=None) -> list[Hit]:
        texts = self.texts(list(ids))
        hits = []
        for r, (cid, sc, tx) in enumerate(zip(ids, scores, texts), start=1):
            li = int(cid) - self.lo
            did = int(self.doc_id[li])
            fl = int(self.flags[li])
            names = [n for bit, n in FLAG_NAMES.items() if fl & bit]
            hits.append(Hit(
                chunk_id=int(cid), doc_id=did, rank=r, score=float(sc), retriever=retriever,
                dense_score=None if dense is None else dense.get(int(cid)),
                bm25_score=None if bm25 is None else bm25.get(int(cid)), text=tx,
                start=int(self.start[li]), end=int(self.end[li]), url=self.docs["url"][did],
                domain=self.docs["host"][did], is_pdf=bool(self.docs["is_pdf"][did]),
                pub_date=self.docs["pub_date"][did], date_source=self.docs["date_source"][did], flags=names))
        return hits


def _topk(ids: np.ndarray, scores: np.ndarray, k: int, floor: float | None = None):
    """Deterministic top-k of (ids, scores): sort by (-score, id). Entries <= floor are dropped."""
    if floor is not None:
        keep = scores > floor
        ids, scores = ids[keep], scores[keep]
    order = np.lexsort((ids, -scores))[:k]
    return ids[order], scores[order]


class Retriever:
    name = "base"

    def __init__(self, corpus: Corpus):
        self.corpus = corpus

    def search(self, query: str, k: int = 10, filters: Filters | None = None) -> list[Hit]:
        return self.search_batch([query], k, [filters or Filters()])[0]

    def candidates_batch(self, queries, k, filters):          # -> list of (ids, scores)
        raise NotImplementedError

    def search_batch(self, queries: list[str], k: int = 10, filters=None) -> list[list[Hit]]:
        filters = self._flist(queries, filters)
        cands = self.candidates_batch(queries, k, filters)
        return [self.corpus.make_hits(ids, sc, self.name) for ids, sc in cands]

    @staticmethod
    def _flist(queries, filters):
        if filters is None:
            return [Filters()] * len(queries)
        if isinstance(filters, Filters):
            return [filters] * len(queries)
        return list(filters)


class DenseExact(Retriever):
    name = "dense"

    def __init__(self, corpus: Corpus, vectors, encoder, device: str | None = None):
        """vectors: [(first_chunk_id, array float16 [rows, 384])] ascending; encoder: fp32 query Encoder."""
        super().__init__(corpus)
        import torch
        self.torch = torch
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.vectors, self.encoder = vectors, encoder

    def candidates_batch(self, queries, k, filters):
        torch, dev = self.torch, self.device
        Q = torch.from_numpy(self.encoder.embed_queries(queries)).to(dev)            # fp32 unit vectors
        masks = [self.corpus.base_mask(f) for f in filters]
        ranges = [self.corpus.excluded_ranges(f) for f in filters]
        same_mask = all(m is masks[0] for m in masks)
        cand_ids = [[] for _ in queries]
        cand_sc = [[] for _ in queries]
        for first, arr in self.vectors:
            V = torch.from_numpy(np.asarray(arr)).to(dev).float()
            S = Q @ V.T                                                                  # [nq, rows]
            off = first - self.corpus.lo
            rows = V.shape[0]
            if same_mask:
                mk = torch.from_numpy(masks[0][off:off + rows]).to(dev)
                S = S.masked_fill(~mk, float("-inf"))
            else:
                for qi, m in enumerate(masks):
                    S[qi] = S[qi].masked_fill(~torch.from_numpy(m[off:off + rows]).to(dev), float("-inf"))
            for qi, rg in enumerate(ranges):
                for a, b in rg:
                    a, b = max(a, off) - off, min(b, off + rows) - off
                    if b > a:
                        S[qi, a:b] = float("-inf")
            kk = min(k, rows)
            vals, idx = torch.topk(S, kk, dim=1)
            thr = vals[:, -1:]
            # exact ties at the boundary: pull in every element equal to the threshold (lower chunk_id wins later)
            extra = (S == thr).sum(1) > (vals == thr).sum(1)
            vals, idx = vals.cpu().numpy(), idx.cpu().numpy()
            for qi in range(len(queries)):
                if bool(extra[qi]):
                    full = S[qi].cpu().numpy()
                    sel = np.nonzero(full >= vals[qi, -1])[0]
                    cand_ids[qi].append(sel + first)
                    cand_sc[qi].append(full[sel])
                else:
                    cand_ids[qi].append(idx[qi] + first)
                    cand_sc[qi].append(vals[qi])
            del S, V
        out = []
        for qi in range(len(queries)):
            ids = np.concatenate(cand_ids[qi]).astype(np.int64)
            sc = np.concatenate(cand_sc[qi]).astype(np.float64)
            out.append(_topk(ids, sc, k, floor=float("-inf")))
        return out


class BM25(Retriever):
    name = "bm25"

    def __init__(self, corpus: Corpus, index: "bm.BM25Index"):
        super().__init__(corpus)
        self.index = index

    def candidates_batch(self, queries, k, filters):
        out = []
        for q, f in zip(queries, filters):
            hashes = self.index.query_terms(q)
            idf = self.index.idfs(hashes)
            mask = self.corpus.base_mask(f)
            rg = self.corpus.excluded_ranges(f)
            ids_all, sc_all = [], []
            for band in self.index.bands:
                s = self.index.score_band(band, hashes, idf)
                off = band["first"] - self.corpus.lo
                s[~mask[off:off + band["n"]]] = 0.0
                self.corpus.apply_exclusions(s, rg, off, 0.0)
                nz = np.nonzero(s > 0)[0]
                if len(nz) > k:                                    # keep everything >= k-th value (tie safety)
                    thr = np.partition(s[nz], len(nz) - k)[len(nz) - k]
                    nz = nz[s[nz] >= thr]
                ids_all.append(nz.astype(np.int64) + band["first"])
                sc_all.append(s[nz].astype(np.float64))
            ids = np.concatenate(ids_all) if ids_all else np.zeros(0, np.int64)
            sc = np.concatenate(sc_all) if sc_all else np.zeros(0)
            out.append(_topk(ids, sc, k))
        return out


class Hybrid(Retriever):
    name = "hybrid"

    def __init__(self, dense: DenseExact, sparse: BM25, depth: int = 100, rrf_k: int = RRF_K):
        super().__init__(dense.corpus)
        self.dense, self.sparse, self.depth, self.rrf_k = dense, sparse, depth, rrf_k

    def candidates_batch(self, queries, k, filters):
        d = self.dense.candidates_batch(queries, self.depth, filters)
        s = self.sparse.candidates_batch(queries, self.depth, filters)
        out = []
        for (di, ds), (si, ss) in zip(d, s):
            fused: dict[int, float] = {}
            for lst in (di, si):
                for r, cid in enumerate(lst, start=1):
                    fused[int(cid)] = fused.get(int(cid), 0.0) + 1.0 / (self.rrf_k + r)
            ids = np.array(list(fused), dtype=np.int64)
            sc = np.array([fused[i] for i in ids])
            out.append((*_topk(ids, sc, k), dict(zip(di.tolist(), ds.tolist())), dict(zip(si.tolist(), ss.tolist()))))
        return out

    def search_batch(self, queries, k=10, filters=None):
        filters = self._flist(queries, filters)
        res = []
        for ids, sc, dmap, smap in self.candidates_batch(queries, k, filters):
            res.append(self.corpus.make_hits(ids, sc, self.name, dense=dmap, bm25=smap))
        return res
