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


def test_empty_answer_is_a_failure_that_is_retried_and_never_cached(tmp_path):
    from evret.web.providers import EmptyResult

    class Empty(FakeProvider):
        def search(self, query, n):
            self.calls += 1
            return []
    p = Empty()
    cs, ft = make(tmp_path, p)
    with pytest.raises(EmptyResult):
        cs.search("moon")
    assert p.calls == 4 and cs.cache.db.execute("SELECT count(*) FROM search").fetchone()[0] == 0   # 4 attempts, no result stored
    assert [r["status"] for r in cs.netlog.records] == ["error:EmptyResult"] * 4


def test_failure_is_remembered_for_replay_and_cleared_by_a_later_success(tmp_path):
    from evret.web.providers import RecordedFailure
    p = FakeProvider(fail_first=4)
    cs, ft = make(tmp_path, p)
    with pytest.raises(RuntimeError):
        cs.search("moon")
    rp = CachedSearch(p, cs.cache, mode=Mode.REPLAY)
    with pytest.raises(RecordedFailure):
        rp.search("moon")                                                       # recorded failure, not ReplayMiss
    with pytest.raises(ReplayMiss):
        rp.search("sun")
    cs.search("moon")                                                           # 5th call succeeds
    assert rp.search("moon") and cs.cache.get_failure(SearchCache.key("fake", "b1", "1.0", "moon", {"n": 10})) is None


# ------------------------------------------------------------------------------------------------ Serper
SECRET = "sk-test-SECRET-123"


def serper(tmp_path, post, **kw):
    from evret.web.providers import QueryBudget, SerperProvider
    warns = []
    b = QueryBudget(str(tmp_path / "b" / "budget.json"), "serper", warn_at=3, refuse_at=5, warn=warns.append, **kw)
    return SerperProvider(budget=b, api_key=SECRET, http_post=post), b, warns


def test_serper_parses_documented_shape_orders_by_position_and_sends_the_exact_request(tmp_path):
    fx = load("serper_sample.json")
    seen = {}

    def post(url, headers, body):
        seen.update(url=url, headers=headers, body=body)
        return 200, fx
    p, b, _ = serper(tmp_path, post)
    res = p.search("a claim text", 10)
    assert [(r.url, r.engine, r.engine_rank) for r in res] == [("https://a.example/1", "google", 1), ("https://b.example/2", "google", 2),
                                                                ("https://c.example/3", "google", 3)]      # by position, duplicate dropped
    assert seen["url"] == "https://google.serper.dev/search" and seen["headers"]["X-API-KEY"] == SECRET
    assert seen["body"] == {"q": "a claim text", "gl": "us", "hl": "en", "num": 10, "autocorrect": False}    # no silent query rewriting
    assert p.last_credits == 1 and b.used() == 1
    assert (p.name, p.backend, p.params) == ("serper", "google", {"gl": "us", "hl": "en", "autocorrect": False})


def test_serper_missing_key_fails_before_any_request_or_budget_use(tmp_path, monkeypatch):
    from evret.web.providers import NonRetryable, QueryBudget, SerperProvider
    monkeypatch.delenv("SERPER_API_KEY", raising=False)
    calls = []
    b = QueryBudget(str(tmp_path / "b.json"), "serper")
    p = SerperProvider(budget=b, http_post=lambda *a: calls.append(a))
    with pytest.raises(NonRetryable, match="SERPER_API_KEY"):
        p.search("q", 10)
    assert not calls and b.used() == 0
    monkeypatch.setenv("SERPER_API_KEY", SECRET)
    p2 = SerperProvider(budget=b, http_post=lambda u, h, body: (200, {"organic": []}))
    assert p2.search("q", 10) == [] and b.used() == 1


def test_serper_key_never_reaches_log_cache_or_error_text(tmp_path):
    def post(url, headers, body):
        return 500, {"message": "server error"}
    p, b, _ = serper(tmp_path, post)
    ft = FakeTime()
    cs = CachedSearch(p, SearchCache(str(tmp_path / "s.sqlite")), limiter=RateLimiter(1.0, ft.clock, ft.sleep), clock=ft.clock, sleep=ft.sleep)
    with pytest.raises(RuntimeError) as e:
        cs.search("moon")
    blob = json.dumps(cs.netlog.records) + str(e.value) + json.dumps(cs.cache.manifest()) + json.dumps(cs.cache.db.execute("SELECT * FROM failures").fetchall())
    assert SECRET not in blob


def test_serper_http_errors_5xx_are_retried_but_401_402_are_not_and_not_recorded_as_query_failures(tmp_path):
    from evret.web.providers import NonRetryable
    n = {"i": 0}

    def flaky(url, headers, body):
        n["i"] += 1
        return (503, {}) if n["i"] < 3 else (200, load("serper_sample.json"))
    p, b, _ = serper(tmp_path, flaky)
    ft = FakeTime()
    cs = CachedSearch(p, SearchCache(str(tmp_path / "s.sqlite")), limiter=RateLimiter(1.0, ft.clock, ft.sleep), clock=ft.clock, sleep=ft.sleep)
    assert len(cs.search("moon")) == 3 and n["i"] == 3 and b.used() == 3          # every SENT request is counted
    p2, b2, _ = serper(tmp_path / "x", lambda u, h, body: (402, {"message": "Not enough credits"}))
    cs2 = CachedSearch(p2, SearchCache(str(tmp_path / "s2.sqlite")), limiter=RateLimiter(1.0, ft.clock, ft.sleep), clock=ft.clock, sleep=ft.sleep)
    with pytest.raises(NonRetryable):
        cs2.search("moon")
    assert b2.used() == 1 and cs2.cache.db.execute("SELECT count(*) FROM failures").fetchone()[0] == 0    # one request, not four; not a query failure


def test_serper_empty_answer_is_cached_as_a_real_result_without_retry(tmp_path):
    p, b, _ = serper(tmp_path, lambda u, h, body: (200, {"organic": []}))
    ft = FakeTime()
    cs = CachedSearch(p, SearchCache(str(tmp_path / "s.sqlite")), limiter=RateLimiter(1.0, ft.clock, ft.sleep), clock=ft.clock, sleep=ft.sleep)
    assert cs.search("moon") == [] and cs.search("moon") == [] and b.used() == 1       # second call is a cache hit: zero credits


def test_budget_counter_persists_warns_at_threshold_and_refuses_unless_overridden(tmp_path):
    from evret.web.providers import BudgetExceeded, QueryBudget
    warns = []
    path = str(tmp_path / "b.json")
    b = QueryBudget(path, "serper", warn_at=3, refuse_at=5, warn=warns.append)
    for _ in range(2):
        b.spend()
    assert warns == [] and b.used() == 2
    b2 = QueryBudget(path, "serper", warn_at=3, refuse_at=5, warn=warns.append)            # new object = new process: count persists
    assert b2.used() == 2
    b2.spend()
    assert len(warns) == 1 and "3" in warns[0]
    b2.spend()
    b2.spend()                                                                              # 5th is allowed (limit is 'more than 5')
    assert b2.used() == 5 and len(warns) == 1                                               # warned once only
    with pytest.raises(BudgetExceeded):
        b2.spend()
    assert b2.used() == 5                                                                   # refused query is not counted
    ov = QueryBudget(path, "serper", warn_at=3, refuse_at=5, override=True, warn=warns.append)
    assert ov.spend() == 6
    assert QueryBudget(path, "other", warn_at=3, refuse_at=5).used() == 0                  # providers are counted separately


def test_replay_of_serper_cache_costs_no_credit_and_budget_default_levels():
    import inspect

    from evret.web.providers import QueryBudget
    d = inspect.signature(QueryBudget.__init__).parameters
    assert (d["warn_at"].default, d["refuse_at"].default) == (1500, 2300)


def test_serper_refuses_more_than_ten_results_per_query_because_that_costs_two_credits(tmp_path):
    p, b, _ = serper(tmp_path, lambda u, h, body: (200, {"organic": []}))
    with pytest.raises(ValueError):
        p.search("q", 11)
    assert b.used() == 0


def test_a_cache_directory_is_locked_to_one_provider(tmp_path):
    from evret.web.eval_web import lock_provider
    lock_provider(str(tmp_path), "serper/google")
    lock_provider(str(tmp_path), "serper/google")                       # same provider again: fine
    with pytest.raises(RuntimeError, match="never mix providers"):
        lock_provider(str(tmp_path), "ddgs/duckduckgo")
