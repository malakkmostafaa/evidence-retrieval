"""BM25 on disk, per band (see docs/plans/corpus_tool_plan.md, change 2).

Tokens: lower-cased text, regex \\w+ , no stemming, no stop-word removal. A term is identified by a 64-bit blake2b hash
of its UTF-8 bytes (collision probability for ~5e7 distinct terms is ~1e-4 in total; no vocabulary dictionary is kept).
Postings of a band are split into 16 partitions by the top 4 hash bits; each partition stores sorted unique terms,
offsets, chunk ids (uint32, global) and term frequencies (uint16). Document lengths (token counts) are per chunk.

Score of chunk d for query q (unique query terms t; Robertson-Sparck Jones idf with +1, as in Lucene):
    idf(t)  = ln(1 + (N - df + 0.5) / (df + 0.5))
    score   = sum_t idf(t) * tf * (k1 + 1) / (tf + k1 * (1 - b + b * dl / avgdl))
N, df and avgdl are computed over all chunks of the loaded bands (so they change when more bands are added).
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
from collections import Counter

import numpy as np

K1, B = 1.5, 0.75
NPART = 16
_TOKEN = re.compile(r"\w+")


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def term_hash(tok: str) -> int:
    return int.from_bytes(hashlib.blake2b(tok.encode("utf-8", "surrogatepass"), digest_size=8).digest(), "big")


def postings_from_texts(texts: list[str], first_id: int, cache: dict | None = None):
    """-> (terms uint64, chunk ids uint32, tf uint16, doclen uint32) for consecutive chunks first_id, first_id+1, ..."""
    cache = {} if cache is None else cache
    if len(cache) > 2_000_000:
        cache.clear()
    t_l, c_l, f_l, dl = [], [], [], np.zeros(len(texts), dtype=np.uint32)
    for i, text in enumerate(texts):
        toks = tokenize(text)
        dl[i] = len(toks)
        cnt = Counter(toks)
        hs = []
        for tok in cnt:
            h = cache.get(tok)
            if h is None:
                h = cache[tok] = term_hash(tok)
            hs.append(h)
        t_l.append(np.array(hs, dtype=np.uint64))
        f_l.append(np.minimum(np.fromiter(cnt.values(), dtype=np.int64, count=len(cnt)), 65535).astype(np.uint16))
        c_l.append(np.full(len(cnt), first_id + i, dtype=np.uint32))
    if not t_l:
        return (np.zeros(0, np.uint64), np.zeros(0, np.uint32), np.zeros(0, np.uint16), dl)
    return np.concatenate(t_l), np.concatenate(c_l), np.concatenate(f_l), dl


def build_band(out_dir: str, first_id: int, parts) -> dict:
    """parts: iterable of (terms, chunk_ids, tf, doclen) in chunk order. Writes out_dir atomically."""
    tmp = out_dir + ".tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    handles = {}
    dls = []
    n_post = 0
    for t, c, f, dl in parts:
        dls.append(dl)
        n_post += len(t)
        p = (t >> np.uint64(60)).astype(np.int64)
        for q in range(NPART):
            m = p == q
            if not m.any():
                continue
            for nm, arr in (("t", t[m]), ("c", c[m]), ("f", f[m])):
                if (q, nm) not in handles:
                    handles[(q, nm)] = open(os.path.join(tmp, f"raw{q}_{nm}.bin"), "ab")
                arr.tofile(handles[(q, nm)])
    for h in handles.values():
        h.close()
    np.save(os.path.join(tmp, "doclen.npy"), np.concatenate(dls) if dls else np.zeros(0, np.uint32))
    n_terms = 0
    for q in range(NPART):
        paths = {nm: os.path.join(tmp, f"raw{q}_{nm}.bin") for nm in "tcf"}
        if not os.path.exists(paths["t"]):
            for nm, dt in (("terms", np.uint64), ("offsets", np.int64), ("chunks", np.uint32), ("tfs", np.uint16)):
                np.save(os.path.join(tmp, f"p{q}_{nm}.npy"), np.zeros(0 if nm != "offsets" else 1, dt))
            continue
        t = np.fromfile(paths["t"], np.uint64)
        c = np.fromfile(paths["c"], np.uint32)
        f = np.fromfile(paths["f"], np.uint16)
        order = np.lexsort((c, t))
        t, c, f = t[order], c[order], f[order]
        del order
        ut, first = np.unique(t, return_index=True)
        offsets = np.append(first, len(t)).astype(np.int64)
        for nm, arr in (("terms", ut), ("offsets", offsets), ("chunks", c), ("tfs", f)):
            np.save(os.path.join(tmp, f"p{q}_{nm}.npy"), arr)
        n_terms += len(ut)
        for p_ in paths.values():
            os.remove(p_)
    meta = {"first_id": first_id, "n_chunks": int(sum(len(d) for d in dls)), "n_postings": int(n_post),
            "n_terms_sum_over_partitions": int(n_terms)}
    with open(os.path.join(tmp, "meta.json"), "w", encoding="utf-8") as f_:
        json.dump(meta, f_)
    shutil.rmtree(out_dir, ignore_errors=True)
    os.replace(tmp, out_dir)
    return meta


class BM25Index:
    def __init__(self, band_dirs: list[str], k1: float = K1, b: float = B):
        self.k1, self.b = k1, b
        self.bands = []
        for d in band_dirs:
            meta = json.load(open(os.path.join(d, "meta.json"), encoding="utf-8"))
            parts = []
            for q in range(NPART):
                parts.append({nm: np.load(os.path.join(d, f"p{q}_{nm}.npy"), mmap_mode="r")
                              for nm in ("terms", "offsets", "chunks", "tfs")})
            self.bands.append({"first": meta["first_id"], "n": meta["n_chunks"], "parts": parts,
                               "dl": np.load(os.path.join(d, "doclen.npy"), mmap_mode="r")})
        self.bands.sort(key=lambda x: x["first"])
        self.N = sum(x["n"] for x in self.bands)
        tot = sum(int(np.asarray(x["dl"], dtype=np.int64).sum()) for x in self.bands)
        self.avgdl = tot / self.N if self.N else 1.0

    def _slice(self, band, h: int):
        part = band["parts"][h >> 60]
        terms = part["terms"]
        i = int(np.searchsorted(terms, np.uint64(h)))
        if i < len(terms) and int(terms[i]) == h:
            return part["offsets"][i], part["offsets"][i + 1], part
        return None

    def query_terms(self, query: str):
        return sorted({term_hash(t) for t in tokenize(query)})

    def idfs(self, hashes):
        out = {}
        for h in hashes:
            df = 0
            for band in self.bands:
                s = self._slice(band, h)
                if s:
                    df += int(s[1] - s[0])
            out[h] = math.log(1.0 + (self.N - df + 0.5) / (df + 0.5)) if df else 0.0
        return out

    def score_band(self, band, hashes, idf) -> np.ndarray:
        """Dense float32 score vector over the chunks of one band (0 where no query term occurs)."""
        scores = np.zeros(band["n"], dtype=np.float32)
        dl = band["dl"]
        for h in hashes:
            if idf[h] == 0.0:
                continue
            s = self._slice(band, h)
            if not s:
                continue
            ids = np.asarray(s[2]["chunks"][s[0]:s[1]]).astype(np.int64) - band["first"]
            tf = np.asarray(s[2]["tfs"][s[0]:s[1]]).astype(np.float32)
            norm = self.k1 * (1.0 - self.b + self.b * np.asarray(dl[ids], dtype=np.float32) / self.avgdl)
            scores[ids] += (idf[h] * tf * (self.k1 + 1.0) / (tf + norm)).astype(np.float32)
        return scores
