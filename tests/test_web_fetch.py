"""WS2 tests. httpx.MockTransport plays the web; no network, no real sleeping. One live smoke test (skipped by default)."""
import json
import os
import threading
import time

import httpx
import pytest

from evret.web.fetch import USER_AGENT, Fetcher, Wayback, parse_cdx, snapshot_url
from evret.web.netlog import NetLog
from evret.web.pagecache import PageCache
from evret.web.schema import Mode, ReplayMiss

FIX = os.path.join(os.path.dirname(__file__), "web_fixtures")
HELLO_SHA = "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"      # sha256(b"hello"), known value


def fx(name):
    return open(os.path.join(FIX, name), "rb").read()


class Web:
    """Scripted web: routes[(host, path)] -> callable(request) or (status, headers, body)."""

    def __init__(self, routes):
        self.routes, self.requests, self.lock = routes, [], threading.Lock()

    def __call__(self, req: httpx.Request):
        with self.lock:
            self.requests.append(req)
        r = self.routes.get((req.url.host, req.url.path))
        if r is None:
            return httpx.Response(404)
        if callable(r):
            return r(req)
        status, headers, body = r
        return httpx.Response(status, headers=headers, content=body)

    def n(self, path):
        return sum(1 for r in self.requests if r.url.path == path)


def make(tmp_path, routes, mode=Mode.LIVE, **kw):
    web = Web(routes)
    sleeps = []
    f = Fetcher(PageCache(str(tmp_path / "wc")), mode=mode, client=httpx.Client(transport=httpx.MockTransport(web), follow_redirects=True),
                sleep=sleeps.append, netlog=NetLog(), **kw)
    return f, web, sleeps


OPEN = {("a.example", "/robots.txt"): (404, {}, b"")}


# ------------------------------------------------------------------------------------------------ fetching
def test_ok_fetch_stores_hash_body_and_sends_honest_user_agent(tmp_path):
    f, web, _ = make(tmp_path, {**OPEN, ("a.example", "/p"): (200, {"content-type": "text/html"}, b"hello")})
    rec, body = f.get("https://a.example/p")
    assert (rec.status, rec.http_status, rec.raw_hash, rec.size, body) == ("ok", 200, HELLO_SHA, 5, b"hello")
    assert f.cache.get_body(HELLO_SHA) == b"hello"
    assert web.requests[-1].headers["user-agent"] == USER_AGENT and "evret-thesis-bot" in USER_AGENT


def test_cache_hit_makes_no_request_and_replay_miss_raises(tmp_path):
    f, web, _ = make(tmp_path, {**OPEN, ("a.example", "/p"): (200, {}, b"hello")})
    f.get("https://a.example/p")
    n = len(web.requests)
    rec, body = f.get("https://a.example/p")
    assert body == b"hello" and len(web.requests) == n
    r = Fetcher(f.cache, Mode.REPLAY, client=httpx.Client(transport=httpx.MockTransport(lambda q: pytest.fail("network!"))))
    assert r.get("https://a.example/p")[1] == b"hello"
    with pytest.raises(ReplayMiss):
        r.get("https://a.example/other")


def test_robots_disallow_blocks_without_requesting_the_page(tmp_path):
    f, web, _ = make(tmp_path, {("a.example", "/robots.txt"): (200, {}, b"User-agent: *\nDisallow: /private\n"),
                                ("a.example", "/private/x"): (200, {}, b"secret"), ("a.example", "/public"): (200, {}, b"hello")})
    rec, body = f.get("https://a.example/private/x")
    assert rec.status == "robots_blocked" and body is None and web.n("/private/x") == 0
    assert f.get("https://a.example/public")[0].status == "ok"
    assert web.n("/robots.txt") == 1                                       # robots.txt fetched once per host


def test_robots_5xx_means_disallowed_but_404_means_allowed(tmp_path):
    f, web, _ = make(tmp_path, {("bad.example", "/robots.txt"): (503, {}, b""), ("bad.example", "/p"): (200, {}, b"x"),
                                ("good.example", "/robots.txt"): (404, {}, b""), ("good.example", "/p"): (200, {}, b"x")})
    assert f.get("https://bad.example/p")[0].status == "robots_blocked"
    assert f.get("https://good.example/p")[0].status == "ok"


def test_404_is_recorded_without_retry_and_503_is_retried_with_backoff(tmp_path):
    calls = {"n": 0}

    def flaky(req):
        calls["n"] += 1
        return httpx.Response(200, content=b"hello") if calls["n"] == 3 else httpx.Response(503)
    f, web, sleeps = make(tmp_path, {**OPEN, ("a.example", "/gone"): (404, {}, b""), ("a.example", "/flaky"): flaky,
                                     ("a.example", "/down"): (503, {}, b"")})
    assert f.get("https://a.example/gone")[0].status == "http_404" and web.n("/gone") == 1
    rec, body = f.get("https://a.example/flaky")
    assert rec.status == "ok" and body == b"hello" and calls["n"] == 3 and sleeps == [1.0, 2.0]
    rec, _ = f.get("https://a.example/down")
    assert rec.status == "http_503" and web.n("/down") == 3                  # three attempts, then recorded


def test_size_cap_boundary_exact_ok_one_byte_more_too_large(tmp_path):
    f, web, _ = make(tmp_path, {**OPEN, ("a.example", "/ok"): (200, {}, b"x" * 1000), ("a.example", "/big"): (200, {}, b"x" * 1001),
                                ("a.example", "/declared"): (200, {"content-length": "5000"}, b"x" * 5000)}, max_bytes=1000)
    assert f.get("https://a.example/ok")[0].status == "ok"
    rec, body = f.get("https://a.example/big")
    assert (rec.status, body, rec.raw_hash) == ("too_large", None, None)
    assert f.get("https://a.example/declared")[0].status == "too_large"


def test_size_cap_without_content_length_is_enforced_while_streaming(tmp_path):
    def chunked(n):                                   # an iterator body has no Content-Length: only the byte count can stop it
        return lambda req: httpx.Response(200, content=iter([b"x" * (n // 2), b"x" * (n - n // 2)]))
    f, web, _ = make(tmp_path, {**OPEN, ("a.example", "/ok"): chunked(1000), ("a.example", "/big"): chunked(1001)}, max_bytes=1000)
    assert "content-length" not in web(httpx.Request("GET", "https://a.example/ok")).headers
    assert f.get("https://a.example/ok")[0].status == "ok"
    assert f.get("https://a.example/big")[0].status == "too_large"


def test_timeout_is_recorded(tmp_path):
    def slow(req):
        raise httpx.ReadTimeout("slow", request=req)
    f, web, sleeps = make(tmp_path, {**OPEN, ("a.example", "/slow"): slow})
    assert f.get("https://a.example/slow")[0].status == "timeout" and web.n("/slow") == 3


def test_one_request_at_a_time_per_host_but_hosts_run_in_parallel(tmp_path):
    active, peak, lock = {}, {"host": 0, "all": 0}, threading.Lock()

    def handler(req):
        h = req.url.host
        with lock:
            active[h] = active.get(h, 0) + 1
            peak["host"] = max(peak["host"], active[h])
            peak["all"] = max(peak["all"], sum(active.values()))
        time.sleep(0.05)
        with lock:
            active[h] -= 1
        return httpx.Response(200, content=b"x")
    routes = {}
    for h in ("a.example", "b.example"):
        routes[(h, "/robots.txt")] = (404, {}, b"")
        for i in range(4):
            routes[(h, f"/p{i}")] = handler
    f, web, _ = make(tmp_path, routes)
    out = f.get_many([(f"https://{h}/p{i}", None) for i in range(4) for h in ("a.example", "b.example")])
    assert [r.status for r, _ in out] == ["ok"] * 8
    assert peak["host"] == 1 and peak["all"] == 2


def test_html_and_pdf_fixtures_roundtrip_bytes(tmp_path):
    html, pdf = fx("pages/article_before.html"), b"%PDF-1.4\n" + bytes(range(256)) * 4
    f, _, _ = make(tmp_path, {**OPEN, ("a.example", "/a.html"): (200, {"content-type": "text/html"}, html),
                              ("a.example", "/a.pdf"): (200, {"content-type": "application/pdf"}, pdf)})
    assert f.get("https://a.example/a.html")[1] == html
    rec, body = f.get("https://a.example/a.pdf")
    assert body == pdf and rec.content_type == "application/pdf" and rec.raw_hash == PageCache.sha256(pdf)


def test_wayback_snapshot_fetch_uses_raw_form_and_skips_robots(tmp_path):
    snap = "/web/20180615235409id_/https://www.bbc.com/news"
    f, web, _ = make(tmp_path, {("web.archive.org", snap): (200, {"content-type": "text/html"}, b"hello")})
    rec, body = f.get("https://www.bbc.com/news", wayback_ts="20180615235409")
    assert rec.status == "ok" and rec.wayback_ts == "20180615235409" and body == b"hello"
    assert snapshot_url("20180615235409", "https://www.bbc.com/news").endswith("20180615235409id_/https://www.bbc.com/news")
    assert all(r.url.host == "web.archive.org" for r in web.requests)           # no robots.txt of bbc.com, nothing live
    assert f.cache.get_page("https://www.bbc.com/news|20180615235409") is not None
    assert f.cache.get_page("https://www.bbc.com/news|live") is None             # snapshot and live are different cache keys


def test_archive_host_is_spaced_one_second(tmp_path):
    t = {"now": 0.0}
    sleeps = []
    web = Web({("web.archive.org", f"/web/2018061500000{i}id_/https://x.example/{i}"): (200, {}, b"x") for i in range(3)})
    f = Fetcher(PageCache(str(tmp_path / "wc")), client=httpx.Client(transport=httpx.MockTransport(web)),
                sleep=lambda s: (sleeps.append(s), t.__setitem__("now", t["now"] + s)), clock=lambda: t["now"])
    for i in range(3):
        f.get(f"https://x.example/{i}", wayback_ts=f"2018061500000{i}")
    assert sleeps == [1.0, 1.0]


# ------------------------------------------------------------------------------------------------ wayback lookup
def test_parse_cdx_takes_last_row_and_ignores_header_and_empty():
    assert parse_cdx(fx("cdx_bbc_news_limit-1.json"), "2018-06-15") == ("20180615235409", "https://www.bbc.com/news")
    assert parse_cdx(fx("cdx_bbc_news_limit2.json"), "2018-06-15") == ("20081122001113", "http://bbc.com/news/")   # last = newest
    assert parse_cdx(fx("cdx_empty.json"), "2018-06-15") is None
    assert parse_cdx(b"", "2018-06-15") is None


def test_parse_cdx_rechecks_the_date_bound():
    assert parse_cdx(fx("cdx_bbc_news_limit-1.json"), "2018-06-14") is None          # snapshot is 15 June > bound 14 June


def test_lookup_sends_to_bound_filter_and_limit_and_caches_both_answers(tmp_path):
    seen = {}

    def cdx(req):
        seen.update(dict(req.url.params))
        return httpx.Response(200, content=fx("cdx_bbc_news_limit-1.json") if "bbc" in seen["url"] else fx("cdx_empty.json"))
    f, web, _ = make(tmp_path, {("web.archive.org", "/cdx/search/cdx"): cdx})
    wb = Wayback(f)
    assert wb.closest_before("https://www.bbc.com/news", "2018-06-15") == ("20180615235409", "https://www.bbc.com/news")
    assert (seen["to"], seen["filter"], seen["limit"], seen["output"]) == ("20180615235959", "statuscode:200", "-1", "json")
    assert wb.closest_before("https://nothing.example/x", "2018-06-15") is None
    n = len(web.requests)
    wb.closest_before("https://www.bbc.com/news", "2018-06-15")
    wb.closest_before("https://nothing.example/x", "2018-06-15")                      # 'no snapshot' is cached too
    assert len(web.requests) == n
    rp = Wayback(Fetcher(f.cache, Mode.REPLAY))
    assert rp.closest_before("https://nothing.example/x", "2018-06-15") is None
    with pytest.raises(ReplayMiss):
        rp.closest_before("https://other.example/", "2018-06-15")


def test_failed_lookup_is_an_error_and_is_not_cached_as_no_snapshot(tmp_path):
    f, web, _ = make(tmp_path, {("web.archive.org", "/cdx/search/cdx"): (503, {}, b"")})
    with pytest.raises(RuntimeError):
        Wayback(f).closest_before("https://x.example/", "2018-06-15")
    assert f.cache.get_lookup("https://x.example/", "2018-06-15")[0] is False


@pytest.mark.live
def test_live_smoke_wayback_and_fetch(tmp_path):
    """Network. Run with: pytest -m live --run-live"""
    f = Fetcher(PageCache(str(tmp_path / "wc")))
    hit = Wayback(f).closest_before("https://www.bbc.com/news", "2018-06-15")
    assert hit and hit[0] <= "20180615235959"
    rec, body = f.get("https://www.bbc.com/news", wayback_ts=hit[0])
    assert rec.status == "ok" and body and b"<html" in body[:2000].lower()
