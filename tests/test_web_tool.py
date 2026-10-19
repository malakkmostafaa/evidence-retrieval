"""WS5 assembly test: the whole pipeline on a scripted web (no network): filters, Wayback, dates, replay, manifest hash."""
import dataclasses
import os

import httpx
import numpy as np
import pytest
from test_search import fake_vec

from evret import chunk as ck
from evret.web.fetch import Fetcher, Wayback
from evret.web.netlog import NetLog
from evret.web.pagecache import PageCache
from evret.web.providers import CachedSearch, RateLimiter, SearchCache, SearchProvider
from evret.web.schema import ClaimContext, Mode, ReplayMiss, SearchResult
from evret.web.select import PoolStats
from evret.web.tool import WebSearchTool

FIX = os.path.join(os.path.dirname(__file__), "web_fixtures", "pages")
BEFORE, AFTER, UNDATED = (open(os.path.join(FIX, f"article_{n}.html"), "rb").read() for n in ("before", "after", "undated"))
SNOPES = "https://www.snopes.com/fact-check/bike-lanes/"
OWN = "https://example.com/fc/article-1/"
URLS = ["https://news.example/ok-before", "https://news.example/late", "https://undated.example/u", SNOPES, OWN,
        "https://wb.example/page", "https://gone.example/x"]
SNAP = "20190102030405"
CLAIM = ClaimContext(claim_date="2020-03-10",
                     exclude_urls=frozenset({"https://web.archive.org/web/20200101120000/https://www.example.com/fc/article-1/"}))
QUERY = "city council bike lanes"


class Prov(SearchProvider):
    name, backend, version = "fake", "fake", "1"
    urls = URLS

    def search(self, query, n):
        return [SearchResult(u, "t", "s", "fake", i) for i, u in enumerate(self.urls, start=1)]


class Enc:
    def embed_passages(self, texts):
        return np.vstack([fake_vec(t) for t in texts])

    def embed_queries(self, qs):
        return np.vstack([fake_vec(q) for q in qs])


def web(requests):
    html = {"news.example": {"/ok-before": BEFORE, "/late": AFTER}, "undated.example": {"/u": UNDATED},
            "wb.example": {"/page": AFTER}, "www.snopes.com": {"/fact-check/bike-lanes/": BEFORE}}

    def handler(req: httpx.Request):
        requests.append(req)
        h, p = req.url.host, req.url.path
        if p == "/robots.txt":
            return httpx.Response(404)
        if h == "web.archive.org" and p == "/cdx/search/cdx":
            u = req.url.params["url"]
            rows = [["timestamp", "original", "statuscode", "mimetype", "digest"]]
            if "wb.example" in u or "wb2.example" in u:
                rows.append([SNAP, u, "200", "text/html", "X"])
            return httpx.Response(200, json=rows if len(rows) > 1 else [])
        if h == "web.archive.org" and p.startswith("/web/" + SNAP) and "wb2.example" in p:
            return httpx.Response(302, headers={"location": "https://web.archive.org/web/20210101000000id_/https://wb2.example/page"})
        if h == "web.archive.org":
            return httpx.Response(200, content=AFTER, headers={"content-type": "text/html"})     # the snapshot text
        if h == "short.example" and p == "/r":
            return httpx.Response(302, headers={"location": OWN})
        if h == "example.com":
            return httpx.Response(200, content=BEFORE, headers={"content-type": "text/html"})
        if h == "tiny.example":
            return httpx.Response(200, content=b"<html><body><p>Too short to chunk.</p></body></html>", headers={"content-type": "text/html"})
        body = html.get(h, {}).get(p)
        return httpx.Response(200, content=body, headers={"content-type": "text/html"}) if body else httpx.Response(404)
    return handler


def build(tmp_path, mode=Mode.LIVE, requests=None, root="wc"):
    requests = [] if requests is None else requests
    client = httpx.Client(transport=httpx.MockTransport(web(requests) if mode == Mode.LIVE else (lambda r: pytest.fail("network in replay"))),
                          follow_redirects=True)
    cache = PageCache(str(tmp_path / root))
    f = Fetcher(cache, mode, client=client, sleep=lambda s: None, netlog=NetLog())
    cs = CachedSearch(Prov(), SearchCache(str(tmp_path / root / "search.sqlite")), mode=mode,
                      limiter=RateLimiter(0, sleep=lambda s: None), sleep=lambda s: None)
    stats = PoolStats(1000, 60.0, {})
    stats.index = None
    # frozen df for every term we can meet: give each query/passage term df = 3 (the statistics are not under test here)
    from evret import bm25 as bm
    for t in bm.tokenize(QUERY):
        stats.df[bm.term_hash(t)] = 3
    tool = WebSearchTool(cs, f, Wayback(f), Enc(), ck.make_counter(ck.tokenizer_file()), stats, enc_id="fake")
    return tool, requests


def hosts(requests):
    return {r.url.host for r in requests}


def test_main_condition_filters_each_page_for_the_stated_reason(tmp_path):
    tool, reqs = build(tmp_path)
    hits = tool.search_web(QUERY, claim_context=CLAIM)
    rep = tool.last_report
    why = {u.url: (u.removed, u.stage) for u in rep.urls}
    assert why[SNOPES] == ("factcheck", "url") and why[OWN] == ("own_article", "url")
    assert why["https://news.example/late"] == ("dated_after", "date")
    assert why["https://undated.example/u"] == ("date_unknown", "date")
    assert why["https://gone.example/x"] == ("fetch_http_404", "fetch")
    assert why["https://news.example/ok-before"][0] is None and why["https://wb.example/page"][0] is None
    assert "www.snopes.com" not in hosts(reqs) and "example.com" not in hosts(reqs)      # removed before any download
    assert {h.url for h in hits} == {"https://news.example/ok-before", "https://wb.example/page"}
    c = rep.counts()
    assert (c["returned"], c["kept"], c["wayback_found"], c["wayback_none"]) == (7, 2, 1, 4)
    assert (c["dated_le"], c["dated_after"], c["unknown"]) == (2, 1, 1)


def test_hit_fields_wayback_page_is_dated_by_its_snapshot_not_its_html(tmp_path):
    tool, _ = build(tmp_path)
    by = {h.url: h for h in tool.search_web(QUERY, claim_context=CLAIM)}
    w, o = by["https://wb.example/page"], by["https://news.example/ok-before"]
    assert (w.fetched_from, w.wayback_timestamp, w.date_source, w.pub_date, w.html_date) == ("wayback", SNAP, "wayback", "2019-01-02", "2021-05-10")
    assert (o.fetched_from, o.wayback_timestamp, o.date_source, o.pub_date) == ("live", "", "htmldate", "2019-03-01")
    for h in (w, o):
        assert h.source == "web" and h.engine == "fake" and h.fetch_status == "ok" and len(h.page_hash) == 64
        assert h.vector.dtype == np.float16 and h.vector.shape == (384,) and h.hybrid_score == h.score and h.retriever == "web_hybrid"
        assert h.domain.endswith(".example") and h.text and h.rank in (1, 2) and h.dense_score is not None
    assert w.engine_rank == 6 and o.engine_rank == 1
    from evret.web.hit import stable_id
    from evret.web.pagecache import page_key
    assert w.chunk_id == stable_id(page_key("https://wb.example/page", SNAP), w.start)      # a snapshot and the live page are different documents
    assert w.doc_id == stable_id(page_key("https://wb.example/page", SNAP)) != stable_id(page_key("https://wb.example/page", None))


def test_lenient_ablation_keeps_undated_pages_flagged_and_factcheck_ablation_keeps_factcheck(tmp_path):
    tool, reqs = build(tmp_path)
    lenient = tool.search_web(QUERY, claim_context=dataclasses.replace(CLAIM, lenient_dates=True))
    und = [h for h in lenient if h.url == "https://undated.example/u"]
    assert und and und[0].date_source == "none" and "undated" in und[0].flags
    fc = tool.search_web(QUERY, claim_context=dataclasses.replace(CLAIM, include_factcheck=True))
    s = [h for h in fc if h.url == SNOPES]
    assert s and "factcheck" in s[0].flags
    assert not [h for h in fc if h.url == OWN]                                   # the own article stays excluded in every ablation


def test_without_a_claim_date_there_is_no_wayback_lookup_and_no_date_filter(tmp_path):
    tool, reqs = build(tmp_path)
    hits = tool.search_web(QUERY, claim_context=ClaimContext(exclude_urls=CLAIM.exclude_urls))
    assert not [r for r in reqs if r.url.path.startswith("/cdx")]
    assert {"https://news.example/late", "https://undated.example/u"} <= {h.url for h in hits}


def test_late_snapshot_redirect_falls_back_to_live(tmp_path):
    tool, reqs = build(tmp_path)
    tool.search.provider.__class__.urls = ["https://wb2.example/page"]
    try:
        tool.search_web(QUERY, claim_context=CLAIM)
    finally:
        tool.search.provider.__class__.urls = URLS
    r = tool.last_report.urls[0]
    # CDX says snapshot 2019, the archive redirects to a 2021 copy -> the snapshot is refused and the live page is used instead
    assert r.wayback == "found" and r.fetched_from == "live"
    assert any(q.url.host == "wb2.example" for q in reqs) and r.final_url.startswith("https://wb2.example")


def test_tiny_pages_and_redirects_to_the_own_article_are_removed(tmp_path):
    tool, reqs = build(tmp_path)
    cls = tool.search.provider.__class__
    cls.urls = ["https://tiny.example/t", "https://short.example/r"]
    try:
        tool.search_web(QUERY, claim_context=dataclasses.replace(CLAIM, claim_date=None))
    finally:
        cls.urls = URLS
    why = {u.url: (u.removed, u.stage) for u in tool.last_report.urls}
    assert why["https://tiny.example/t"] == ("tiny", "text")
    assert why["https://short.example/r"] == ("own_article", "url") and "example.com" in hosts(reqs)   # found only after the redirect


def test_filters_object_supplies_the_date_bound_and_exclusions(tmp_path):
    from evret.search import Filters
    tool, _ = build(tmp_path)
    f = Filters(not_after="2020-03-10", exclude_norm_urls=frozenset({"news.example/ok-before"}), exclude_domains=frozenset({"gone.example"}))
    hits = tool.search_web(QUERY, filters=f, claim_context=ClaimContext(exclude_urls=CLAIM.exclude_urls))
    why = {u.url: u.removed for u in tool.last_report.urls}
    assert why["https://news.example/late"] == "dated_after"                    # bound came from Filters.not_after
    assert why["https://news.example/ok-before"] == "own_article" and why["https://gone.example/x"] == "domain"
    assert {h.url for h in hits} == {"https://wb.example/page"}
    assert why[SNOPES] == "factcheck"
    got = tool.search_web(QUERY, filters=Filters(exclude_flags=frozenset()), claim_context=CLAIM)
    assert SNOPES in {h.url for h in got}                                       # Filters without the 'factcheck' flag = fact-check ablation


def test_replay_reproduces_the_hits_without_network_and_manifest_hash_tracks_the_cache(tmp_path):
    tool, _ = build(tmp_path)
    first = tool.search_web(QUERY, claim_context=CLAIM)
    h1 = tool.manifest_hash()
    assert tool.manifest_hash() == h1
    rtool, _ = build(tmp_path, mode=Mode.REPLAY)
    again = rtool.search_web(QUERY, claim_context=CLAIM)
    assert [(h.url, h.chunk_id, round(h.score, 12), h.dense_score, h.bm25_score) for h in first] == \
           [(h.url, h.chunk_id, round(h.score, 12), h.dense_score, h.bm25_score) for h in again]
    assert rtool.manifest_hash() == h1
    with pytest.raises(ReplayMiss):
        rtool.search_web("a query that was never run", claim_context=CLAIM)
    tool.search_web(QUERY, claim_context=dataclasses.replace(CLAIM, lenient_dates=True))   # fetches/processes more pages
    assert tool.manifest_hash() != h1


def test_report_has_all_seven_step_timers(tmp_path):
    tool, _ = build(tmp_path)
    tool.search_web(QUERY, claim_context=CLAIM)
    assert set(tool.last_report.seconds) == {"search", "wayback", "fetch", "extract", "chunk", "embed", "select"}
    assert all(v >= 0 for v in tool.last_report.seconds.values()) and tool.last_report.seconds["embed"] > 0


def test_manifest_hash_changes_when_only_a_stored_vector_changes(tmp_path):
    tool, _ = build(tmp_path)
    tool.search_web(QUERY, claim_context=CLAIM)
    h1 = tool.manifest_hash()
    key, vecs = tool.cache.execute("SELECT key, vecs FROM chunks ORDER BY key")[0]
    tool.cache.execute("UPDATE chunks SET vecs=? WHERE key=?", (bytes(len(vecs)), key))
    assert tool.manifest_hash() != h1


def test_a_failing_engine_gives_no_hits_and_a_recorded_error_but_replay_miss_still_raises(tmp_path):
    class Broken(Prov):
        def search(self, query, n):
            raise RuntimeError("No results found.")
    tool, reqs = build(tmp_path)
    tool.search.provider = Broken()
    tool.search.sleep = lambda s: None
    assert tool.search_web(QUERY, claim_context=CLAIM) == []
    assert tool.last_report.search_error.startswith("RuntimeError") and tool.last_report.counts()["search_failed"] == 1
    assert not reqs                                                              # nothing else was attempted
    assert len(tool.search.cache.manifest()) == 1 and tool.search.cache.manifest()[0][1].startswith("FAILED:")   # failure is recorded, not a result
    assert tool.search.cache.db.execute("SELECT count(*) FROM search").fetchone()[0] == 0                       # ... and never as 'no results'
    rtool, _ = build(tmp_path, mode=Mode.REPLAY)
    assert rtool.search_web(QUERY, claim_context=CLAIM) == []                     # replay reproduces the failure
    assert rtool.last_report.search_error.startswith("RecordedFailure: RuntimeError")
    with pytest.raises(ReplayMiss):
        rtool.search_web("a query that was never run", claim_context=CLAIM)


def know_terms(tool, *queries):
    from evret import bm25 as bm
    for q in queries:
        for t in bm.tokenize(q):
            tool.stats.df.setdefault(bm.term_hash(t), 3)


URLS_2 = [SearchResult(u, 't', 's', 'fake', i) for i, u in enumerate(URLS[:2], start=1)]


class QuoteProv(Prov):
    """Returns nothing for a query that contains double quotes (as Google does for a long exact phrase), 3 results otherwise."""
    calls = []
    empty_is_failure = False                       # like an API: an empty list is a real answer

    def search(self, query, n):
        QuoteProv.calls.append(query)
        if "fewer" in query:
            return URLS_2 if '"' in query else URLS_2[:1]
        if any(c in query for c in '"\u201c\u201d'):
            return [] if "zero" in query else [SearchResult("https://news.example/ok-before", "t", "s", "fake", 1)]
        return [SearchResult(u, "t", "s", "fake", i) for i, u in enumerate(URLS[:3], start=1)]


def test_strip_quotes_removes_only_double_quote_characters():
    from evret.web.tool import strip_quotes
    assert strip_quotes('He said \u201cit\'s  here\u201d and "now"') == "He said it's here and now"
    assert strip_quotes("no quotes here") == "no quotes here"


def test_quote_fallback_requeries_once_keeps_both_in_the_cache_and_replays(tmp_path):
    QuoteProv.calls = []
    tool, _ = build(tmp_path)
    tool.search.provider = QuoteProv()
    tool.search.limiter = RateLimiter(0, sleep=lambda s: None)
    q = 'He said "bike lanes" zero'
    know_terms(tool, q, "plain query without marks", "zero results but no quote marks", 'off "bike"', 'He said "bike lanes"')
    tool.search.provider.params                                                                # (touch)
    hits = tool.search_web(q, claim_context=CLAIM)
    rep = tool.last_report
    assert QuoteProv.calls == [q, "He said bike lanes zero"]                                   # exactly one re-query
    assert rep.fallback == "tried_no_gain" or rep.fallback == "used"
    q2 = 'He said "bike lanes"'                                                                 # first query: 1 result < 3 -> stripped query: 3 results
    tool.search_web(q2, claim_context=CLAIM)
    assert tool.last_report.fallback == "used" and tool.last_report.query_used == "He said bike lanes"
    assert len(tool.last_report.urls) == 3
    n = len(QuoteProv.calls)
    tool.search_web(q2, claim_context=CLAIM)                                                   # both forms are cached: no new query
    assert len(QuoteProv.calls) == n
    r = build(tmp_path, mode=Mode.REPLAY)[0]
    know_terms(r, q2)
    r.search.provider = QuoteProv()
    r.search_web(q2, claim_context=CLAIM)
    assert r.last_report.fallback == "used" and len(QuoteProv.calls) == n                      # replay: same decision, no query


def test_no_fallback_when_enough_results_or_no_quotes_or_disabled(tmp_path):
    QuoteProv.calls = []
    tool, _ = build(tmp_path)
    tool.search.provider = QuoteProv()
    tool.search.limiter = RateLimiter(0, sleep=lambda s: None)
    know_terms(tool, "plain query without marks", "zero results but no quote marks", 'off "bike"')
    tool.search_web("plain query without marks", claim_context=CLAIM)
    assert QuoteProv.calls == ["plain query without marks"] and tool.last_report.fallback == "not_needed"      # 3 results: enough
    QuoteProv.calls = []
    tool.search_web("zero results but no quote marks", claim_context=CLAIM)
    tool.quote_fallback = False
    tool.search_web('off "bike"', claim_context=CLAIM)
    assert QuoteProv.calls == ["zero results but no quote marks", 'off "bike"'] and tool.last_report.fallback == "not_needed"


def test_fallback_keeps_the_first_answer_when_the_stripped_query_is_not_better(tmp_path):
    QuoteProv.calls = []
    tool, _ = build(tmp_path)
    tool.search.provider = QuoteProv()
    tool.search.limiter = RateLimiter(0, sleep=lambda s: None)
    know_terms(tool, 'fewer "x"', "zero results but no quote marks")
    tool.search_web('fewer "x"', claim_context=CLAIM)
    assert tool.last_report.fallback == "tried_no_gain" and tool.last_report.query_used == 'fewer "x"' and len(tool.last_report.urls) == 2
    know_terms(tool, "fewer plain")
    tool.search_web("fewer plain", claim_context=CLAIM)                           # 1 result, nothing to strip
    assert tool.last_report.fallback == "not_applicable"
