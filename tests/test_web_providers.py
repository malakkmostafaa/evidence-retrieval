"""WS1 tests. No network: ddgs output is a recorded fixture, SearXNG output a hand-built one, time is faked."""
import json
import os

import pytest

from evret.web.netlog import NetLog
from evret.web.providers import (CachedSearch, DdgsProvider, RateLimiter, SearchCache, SearchProvider,
                                 SearxngProvider, with_backoff)
from evret.web.schema import Mode, ReplayMiss, SearchResult

FIX = os.path.join(os.path.dirname(__file__), "web_fixtures")


def load(name):
    return json.load(open(os.path.join(FIX, name), encoding="utf-8"))


class FakeTime:
    def __init__(self):
        self.t, self.sleeps = 100.0, []

    def clock(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


class FakeProvider(SearchProvider):
    name = "fake"

    def __init__(self, backend="b1", version="1.0", fail_first=0):
        self._b, self._v, self.calls, self.fail_first = backend, version, 0, fail_first

    backend = property(lambda s: s._b)
    version = property(lambda s: s._v)

    def search(self, query, n):
        self.calls += 1
        if self.calls <= self.fail_first:
            raise RuntimeError("rate limited")
        return [SearchResult(f"https://x.example/{query}/{i}", "t", "s", self._b, i) for i in range(1, 3)]


def make(tmp_path, provider=None, mode=Mode.LIVE, ft=None):
    ft = ft or FakeTime()
    cs = CachedSearch(provider or FakeProvider(), SearchCache(str(tmp_path / "s.sqlite")), mode=mode,
                      limiter=RateLimiter(3.0, ft.clock, ft.sleep), clock=ft.clock, sleep=ft.sleep)
    return cs, ft


# ------------------------------------------------------------------------------------------------ providers
def test_ddgs_parses_recorded_output_and_records_backend():
    fx = load("ddgs_duckduckgo_eiffel.json")

    class Client:
        def text(self, q, region, max_results, backend):
            assert (region, max_results, backend) == ("us-en", 10, "duckduckgo")
            return fx["raw"]
    res = DdgsProvider("duckduckgo", client_factory=Client).search("q", 10)
    assert [r.url for r in res] == [d["href"] for d in fx["raw"]]          # same order, nothing lost
    assert [r.engine_rank for r in res] == list(range(1, 11))
    assert {r.engine for r in res} == {"duckduckgo"}
    assert res[0].title == fx["raw"][0]["title"] and res[0].snippet == fx["raw"][0]["body"]


def test_ddgs_refuses_auto_backend():
    with pytest.raises(ValueError):
        DdgsProvider("auto")


def test_searxng_drops_empty_and_duplicate_urls_and_renumbers():
    fx = load("searxng_sample.json")
    p = SearxngProvider("http://localhost:8080", http_get=lambda u, params: (
        fx if (u, params["format"], params["q"]) == ("http://localhost:8080/search", "json", "example") else None))
    res = p.search("example", 10)
    assert [(r.url, r.engine, r.engine_rank) for r in res] == [
        ("https://a.example/1", "duckduckgo", 1), ("https://b.example/2", "bing", 2), ("https://c.example/3", "brave", 3)]
    assert res[0].snippet == "snippet a1"


# ------------------------------------------------------------------------------------------------ limiter, backoff
def test_rate_limiter_spaces_calls_three_seconds_apart():
    ft = FakeTime()
    rl = RateLimiter(3.0, ft.clock, ft.sleep)
    rl.wait()                      # first call: no wait
    ft.t += 1.0
    rl.wait()                      # 1 s passed -> must wait 2 s
    ft.t += 10.0
    rl.wait()                      # 10 s passed -> no wait
    assert ft.sleeps == [2.0]


def test_backoff_waits_2_4_8_then_succeeds_and_raises_when_exhausted():
    ft = FakeTime()
    n = {"i": 0}

    def flaky():
        n["i"] += 1
        if n["i"] < 4:
            raise RuntimeError("x")
        return "ok"
    assert with_backoff(flaky, sleep=ft.sleep) == "ok"
    assert ft.sleeps == [2.0, 4.0, 8.0]
    ft2 = FakeTime()
    with pytest.raises(RuntimeError):
        with_backoff(lambda: (_ for _ in ()).throw(RuntimeError("always")), sleep=ft2.sleep)
    assert ft2.sleeps == [2.0, 4.0, 8.0]                    # 4 attempts, 3 waits, then the error


# ------------------------------------------------------------------------------------------------ cache
def test_second_identical_query_comes_from_cache(tmp_path):
    p = FakeProvider()
    cs, _ = make(tmp_path, p)
    a = cs.search("moon")
    b = cs.search("moon")
    assert a == b and p.calls == 1 and cs.netlog.count("search") == 1


def test_cache_key_covers_backend_version_query_and_params(tmp_path):
    ft = FakeTime()
    cache = SearchCache(str(tmp_path / "s.sqlite"))
    for prov in (FakeProvider("b1", "1.0"), FakeProvider("b2", "1.0"), FakeProvider("b1", "2.0")):
        cs = CachedSearch(prov, cache, limiter=RateLimiter(3.0, ft.clock, ft.sleep), clock=ft.clock, sleep=ft.sleep)
        cs.search("moon")
        assert prov.calls == 1                                  # none of the three hits another's entry
    cs = CachedSearch(FakeProvider(), cache, n=5, limiter=RateLimiter(3.0, ft.clock, ft.sleep), clock=ft.clock, sleep=ft.sleep)
    cs.search("moon")
    assert cs.provider.calls == 1                               # n=5 differs from n=10
    assert len(cache.manifest()) == 4


def test_replay_mode_makes_no_call_and_fails_on_a_miss(tmp_path):
    p = FakeProvider()
    cs, ft = make(tmp_path, p)
    cs.search("moon")
    calls_before = p.calls
    rp = CachedSearch(p, cs.cache, mode=Mode.REPLAY)
    assert rp.search("moon") == cs.search("moon")
    with pytest.raises(ReplayMiss):
        rp.search("sun")
    assert p.calls == calls_before


def test_queries_are_spaced_and_failures_are_logged_and_retried(tmp_path):
    p = FakeProvider(fail_first=1)
    cs, ft = make(tmp_path, p)
    cs.search("a")                  # attempt 1 fails, backoff 2 s, attempt 2 (limiter: 2 s passed -> 1 s more)
    cs.search("b")                  # new query right after -> limiter waits the full 3 s
    st = [r["status"] for r in cs.netlog.records]
    assert st == ["error:RuntimeError", "ok", "ok"]
    assert ft.sleeps == [2.0, 1.0, 3.0]
