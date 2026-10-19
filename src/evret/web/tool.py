"""search_web(query, k, filters, claim_context) -> list[WebHit]  (WS5 assembly of WS1-WS4).

Pipeline: provider search -> URL filters (own article, fact-check, domains) -> Wayback lookup -> fetch (snapshot, else live)
-> extract -> date filter -> chunk -> embed -> dense + BM25 (pool statistics) -> RRF -> top-N.
A page removed by an early step is never downloaded. Every URL gets a record (`last_report`) so that each filter's effect,
Wayback coverage and the seconds per step can be counted. The search code never sees gold labels.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from urllib.parse import urlparse

from evret.web.extract import EXTRACTOR_VERSION, Extracted, extract
from evret.web.fetch import ARCHIVE_HOST, Fetcher, Wayback
from evret.web.filters import date_reason, url_reason
from evret.web.hit import WebHit, stable_id
from evret.web.pagecache import page_key
from evret.web.providers import CachedSearch
from evret.web.schema import ClaimContext, Mode, ReplayMiss
from evret.web.select import PassageStore, PoolStats, select

STEPS = ("search", "wayback", "fetch", "extract", "chunk", "embed", "select")
_SNAP_TS = re.compile(r"/web/(\d{14})")


@dataclass
class UrlRecord:
    url: str
    engine_rank: int
    engine: str
    removed: str | None = None            # why the page left the pipeline (None = it supplied passages)
    stage: str = ""                       # url | fetch | date | text
    wayback: str = "not_looked_up"        # found | none | error | not_looked_up
    fetched_from: str = ""
    wayback_ts: str = ""
    fetch_status: str = ""
    pub_date: str = ""
    date_source: str = ""
    date_class: str = ""
    html_date: str = ""
    kind: str = ""
    n_chars: int = 0
    n_chunks: int = 0
    final_url: str = ""


@dataclass
class QueryReport:
    query: str
    claim_date: str | None
    urls: list = field(default_factory=list)
    seconds: dict = field(default_factory=lambda: {s: 0.0 for s in STEPS})
    n_passages: int = 0
    search_error: str = ""

    def counts(self) -> dict:
        c: dict = {"returned": len(self.urls)}
        for u in self.urls:
            if u.removed:
                c[f"removed:{u.removed}"] = c.get(f"removed:{u.removed}", 0) + 1
        c["wayback_found"] = sum(u.wayback == "found" for u in self.urls)
        c["wayback_none"] = sum(u.wayback == "none" for u in self.urls)
        c["wayback_error"] = sum(u.wayback == "error" for u in self.urls)
        for dc in ("dated_le", "dated_after", "unknown"):
            c[dc] = sum(u.date_class == dc for u in self.urls)
        c["kept"] = sum(u.removed is None for u in self.urls)
        c["search_failed"] = int(bool(self.search_error))
        return c


class _Timed:
    """Encoder proxy that adds its seconds to the report's 'embed' bucket."""

    def __init__(self, enc, sink):
        self.enc, self.sink = enc, sink

    def embed_passages(self, texts, *a, **k):
        t = time.perf_counter()
        try:
            return self.enc.embed_passages(texts, *a, **k)
        finally:
            self.sink["embed"] += time.perf_counter() - t

    def embed_queries(self, qs):
        t = time.perf_counter()
        try:
            return self.enc.embed_queries(qs)
        finally:
            self.sink["embed"] += time.perf_counter() - t


class WebSearchTool:
    def __init__(self, search: CachedSearch, fetcher: Fetcher, wayback: Wayback, enc, count, stats: PoolStats,
                 max_pages: int = 10, top_n: int = 50, enc_id: str | None = None):
        self.search, self.fetcher, self.wayback, self.stats = search, fetcher, wayback, stats
        self.max_pages, self.top_n = max_pages, top_n
        self.cache = fetcher.cache
        self._sink = {s: 0.0 for s in STEPS}
        self.enc = _Timed(enc, self._sink)
        kw = {"enc_id": enc_id} if enc_id else {}
        self.store = PassageStore(self.cache, self.enc, count, **kw)
        self.cache.ensure_table("CREATE TABLE IF NOT EXISTS extracts (key TEXT PRIMARY KEY, text TEXT, kind TEXT, title TEXT, "
                                "pub_date TEXT, date_source TEXT, html_date TEXT, note TEXT)")
        self.last_report: QueryReport | None = None

    @contextmanager
    def _t(self, step):
        t = time.perf_counter()
        try:
            yield
        finally:
            self._sink[step] += time.perf_counter() - t

    # ---------------------------------------------------------------------------------------------- extraction cache
    def _extract(self, rec, body) -> Extracted:
        key = f"{rec.key}|{EXTRACTOR_VERSION}"
        rows = self.cache.execute("SELECT text, kind, title, pub_date, date_source, html_date, note FROM extracts WHERE key=?", (key,))
        if rows:
            return Extracted(*rows[0])
        e = extract(body, rec.content_type, rec.url, rec.wayback_ts)
        self.cache.execute("INSERT OR REPLACE INTO extracts VALUES (?,?,?,?,?,?,?,?)",
                           (key, e.text, e.kind, e.title, e.pub_date, e.date_source, e.html_date, e.note))
        return e

    # ---------------------------------------------------------------------------------------------- the tool
    def search_web(self, query: str, k: int | None = None, filters=None, claim_context: ClaimContext | None = None
                   ) -> list[WebHit]:
        ctx = claim_context or ClaimContext()
        k = k or self.top_n
        norm_ex = set(getattr(filters, "exclude_norm_urls", ()) or ())
        if filters is not None and "factcheck" not in getattr(filters, "exclude_flags", {"factcheck"}):
            ctx = dataclasses.replace(ctx, include_factcheck=True)
        if norm_ex:
            ctx = dataclasses.replace(ctx, exclude_urls=frozenset(ctx.exclude_urls | norm_ex))
        dom_in = getattr(filters, "domains", None)
        dom_out = getattr(filters, "exclude_domains", frozenset()) or frozenset()
        claim_date = ctx.claim_date or getattr(filters, "not_after", None)
        ctx = dataclasses.replace(ctx, claim_date=claim_date)
        for s in STEPS:
            self._sink[s] = 0.0
        self.store.t_chunk = 0.0
        rep = QueryReport(query, claim_date)
        self.last_report = rep

        with self._t("search"):
            try:
                results = self.search.search(query)[: self.max_pages]
            except ReplayMiss:
                raise
            except Exception as e:                       # engine blocked / "No results found" after all retries: not cached, counted
                rep.search_error = f"{type(e).__name__}: {str(e)[:120]}"
                results = []
        recs = [UrlRecord(r.url, r.engine_rank, r.engine) for r in results]
        rep.urls = recs

        # 1. URL-level filters: nothing is downloaded for these
        live = []
        for r in recs:
            host = (urlparse(r.url).hostname or "").lower()
            why = url_reason(r.url, ctx)
            if why is None and dom_in is not None and not any(host == d or host.endswith("." + d) for d in dom_in):
                why = "domain"
            if why is None and any(host == d or host.endswith("." + d) for d in dom_out):
                why = "domain"
            if why:
                r.removed, r.stage = why, "url"
            else:
                live.append(r)

        # 2. Wayback lookup (only when the claim has a date)
        snap: dict[str, str] = {}
        if claim_date:
            with self._t("wayback"):
                for r in live:
                    try:
                        hit = self.wayback.closest_before(r.url, claim_date)
                    except RuntimeError:
                        r.wayback = "error"
                        continue
                    r.wayback = "found" if hit else "none"
                    if hit:
                        snap[r.url] = hit[0]

        # 3. fetch: snapshot where there is one, else live; a failed snapshot falls back to live
        with self._t("fetch"):
            got = self.fetcher.get_many([(r.url, snap.get(r.url)) for r in live])
            bound = (claim_date or "").replace("-", "") + "235959"
            redo = []
            for i, (r, (rec, body)) in enumerate(zip(live, got)):
                late = rec.wayback_ts and (m := _SNAP_TS.search(rec.final_url)) and m.group(1) > bound
                if rec.wayback_ts and (rec.status != "ok" or late):
                    redo.append(i)
            if redo:
                again = self.fetcher.get_many([(live[i].url, None) for i in redo])
                for i, res in zip(redo, again):
                    got[i] = res

        # 4. per page: status, URL filter after redirects, extract, date filter
        pages = []                                  # (record, page record, extracted)
        for r, (rec, body) in zip(live, got):
            r.fetched_from = "wayback" if rec.wayback_ts else "live"
            r.wayback_ts, r.fetch_status, r.final_url = rec.wayback_ts or "", rec.status, rec.final_url
            if rec.status != "ok" or body is None:
                r.removed, r.stage = f"fetch_{rec.status}", "fetch"
                continue
            why = url_reason(r.url, ctx, final_url=rec.final_url if not rec.wayback_ts else None)
            if why:
                r.removed, r.stage = why, "url"
                continue
            with self._t("extract"):
                ex = self._extract(rec, body)
            r.pub_date, r.date_source, r.html_date, r.kind, r.n_chars = ex.pub_date, ex.date_source, ex.html_date, ex.kind, len(ex.text)
            r.date_class, why = date_reason(ex.pub_date, ex.date_source, ctx)
            if why:
                r.removed, r.stage = why, "date"
                continue
            if len(ex.text) < 200:
                r.removed, r.stage = "no_text" if not ex.text.strip() else "tiny", "text"
                continue
            pages.append((r, rec, ex))

        # 5. chunk + embed (cached per page), 6. first-pass selection
        passages, vecs, owner = [], [], []
        for r, rec, ex in pages:
            prep = self.store.get(rec.key, ex.text)
            r.n_chunks = len(prep.spans)
            for (s, e, ntok, split, hard), v in zip(prep.spans, prep.vectors):
                passages.append((s, e, ntok, split, hard))
                vecs.append(v)
                owner.append((r, rec, ex))
        self._sink["chunk"] += self.store.t_chunk
        rep.n_passages = len(passages)
        texts = [owner[i][2].text[p[0]:p[1]] for i, p in enumerate(passages)]
        import numpy as np
        V = np.vstack(vecs) if vecs else np.zeros((0, 384), np.float16)
        t0 = time.perf_counter()
        emb0 = self._sink["embed"]
        scored = select(query, texts, V, self.enc, self.stats, top_n=max(k, 1))
        self._sink["select"] += (time.perf_counter() - t0) - (self._sink["embed"] - emb0)
        hits = []
        for rank, sc in enumerate(scored[:k], start=1):
            r, rec, ex = owner[sc.index]
            s, e, ntok, split, hard = passages[sc.index]
            flags = ([] if not ex.kind == "pdf" else ["pdf"]) + (["undated"] if r.date_class == "unknown" else []) \
                + (["factcheck"] if ctx.include_factcheck and url_reason(r.url, dataclasses.replace(ctx, include_factcheck=False)) == "factcheck" else [])
            hits.append(WebHit(
                chunk_id=stable_id(rec.key, s), doc_id=stable_id(rec.key), rank=rank, score=sc.hybrid, retriever="web_hybrid",
                dense_score=sc.dense, bm25_score=sc.bm25, text=texts[sc.index], start=s, end=e, url=r.url,
                domain=(urlparse(r.url).hostname or "").lower(), is_pdf=ex.kind == "pdf", pub_date=ex.pub_date,
                date_source=ex.date_source, flags=flags, fetched_from=r.fetched_from, wayback_timestamp=r.wayback_ts,
                engine=r.engine, engine_rank=r.engine_rank, fetch_status=rec.status, page_hash=rec.raw_hash or "",
                fetch_time=rec.fetch_time, hybrid_score=sc.hybrid, n_tokens=ntok, html_date=ex.html_date, vector=V[sc.index]))
        for s in STEPS:
            rep.seconds[s] = self._sink[s]
        return hits

    # ---------------------------------------------------------------------------------------------- reproducibility
    def manifest_hash(self) -> str:
        """Hash of everything a REPLAY depends on: search entries, page records, Wayback lookups, extractions, chunks, pool statistics."""
        h = hashlib.sha256()
        for key, res in self.search.cache.manifest():
            h.update(f"S|{key}|{res}\n".encode())
        for table, cols in (("pages", "key,status,raw_hash"), ("lookups", "key,timestamp,original"),
                            ("extracts", "key,pub_date,date_source,length(text)"), ("chunks", "key,spans,n")):
            for row in self.cache.execute(f"SELECT {cols} FROM {table} ORDER BY key"):
                h.update(f"{table}|{row}\n".encode())
        for key, vecs in self.cache.execute("SELECT key, vecs FROM chunks ORDER BY key"):
            h.update(f"vec|{key}|{hashlib.sha256(vecs).hexdigest()}\n".encode())
        h.update(json.dumps(self.stats.freeze(), sort_keys=True).encode())
        return h.hexdigest()
