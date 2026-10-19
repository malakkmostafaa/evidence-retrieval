"""WS1 - search providers, rate limit / backoff, and the search cache (WD1, WD6, WD7).

A provider only turns (query, n) into a list of SearchResult. Caching, spacing between queries and retries are done
by `CachedSearch`, so every provider gets the same behaviour and the same tests.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
import uuid
from abc import ABC, abstractmethod

from evret.web.netlog import NetLog
from evret.web.schema import Mode, ReplayMiss, SearchResult

MIN_INTERVAL = 3.0          # WD7: at most 1 query per 3 s per provider
BACKOFF_BASE = 2.0          # seconds; waits are 2, 4, 8, ... between attempts
MAX_ATTEMPTS = 4


class EmptyResult(RuntimeError):
    """The engine answered with no result at all. Scraping engines do this when they throttle or block, so an empty answer is
    treated as a failure (retried, never cached) rather than as 'the web has nothing'."""


class RecordedFailure(RuntimeError):
    """REPLAY: this search failed when the cache was recorded (engine error / empty answer); the failure is part of the snapshot."""


class SearchProvider(ABC):
    name: str = "base"
    empty_is_failure = True        # scraping engines answer "nothing" when they block; an API's empty list is a real answer
    min_interval: float | None = None

    @property
    @abstractmethod
    def backend(self) -> str: ...

    @property
    @abstractmethod
    def version(self) -> str: ...

    @property
    def params(self) -> dict:
        return {}

    @abstractmethod
    def search(self, query: str, n: int) -> list[SearchResult]: ...


def _rank(rows: list[SearchResult], n: int) -> list[SearchResult]:
    """Drop empty and repeated URLs (first occurrence wins), keep n, number 1..n."""
    seen, out = set(), []
    for r in rows:
        if r.url and r.url not in seen:
            seen.add(r.url)
            out.append(r)
    return [SearchResult(r.url, r.title, r.snippet, r.engine, i) for i, r in enumerate(out[:n], start=1)]


class DdgsProvider(SearchProvider):
    """ddgs text search with an explicit backend (never 'auto'), region us-en."""
    name = "ddgs"

    def __init__(self, backend: str, region: str = "us-en", client_factory=None):
        if backend in ("auto", "", None):
            raise ValueError("the ddgs backend must be explicit (not 'auto')")
        self._backend, self.region, self._factory = backend, region, client_factory

    @property
    def backend(self) -> str:
        return self._backend

    @property
    def version(self) -> str:
        from importlib.metadata import version
        return version("ddgs")

    @property
    def params(self) -> dict:
        return {"region": self.region}

    def _client(self):
        if self._factory:
            return self._factory()
        from ddgs import DDGS
        return DDGS()

    def search(self, query: str, n: int) -> list[SearchResult]:
        raw = self._client().text(query, region=self.region, max_results=n, backend=self._backend)
        rows = [SearchResult((d.get("href") or "").strip(), d.get("title") or "", d.get("body") or "", self._backend, 0)
                for d in raw]
        return _rank(rows, n)


class SearxngProvider(SearchProvider):
    """Self-hosted SearXNG with the JSON format enabled (settings.yml: search.formats: [html, json])."""
    name = "searxng"

    def __init__(self, base_url: str, language: str = "en-US", http_get=None, version: str = "unknown"):
        self.base_url, self.language, self._get, self._version = base_url.rstrip("/"), language, http_get, version

    @property
    def backend(self) -> str:
        return "searxng-default-engines"        # the engine of each result is stored per result

    @property
    def version(self) -> str:
        return self._version

    @property
    def params(self) -> dict:
        return {"language": self.language}

    def search(self, query: str, n: int) -> list[SearchResult]:
        get = self._get
        if get is None:
            import httpx

            def get(u, p):
                return httpx.get(u, params=p, timeout=20, headers={"User-Agent": "evret-thesis-bot/0.1"}).json()
        data = get(f"{self.base_url}/search", {"q": query, "format": "json", "language": self.language})
        rows = [SearchResult((d.get("url") or "").strip(), d.get("title") or "", d.get("content") or "",
                             d.get("engine") or "searxng", 0) for d in data.get("results", [])]
        return _rank(rows, n)


class NonRetryable(RuntimeError):
    """An answer that retrying cannot fix (bad key, no credit, bad request): stop at once, spend no further credits."""


class BudgetExceeded(NonRetryable):
    pass


class QueryBudget:
    """Persisted counter of live queries sent to a paid/limited API (one JSON file per provider, shared by all worktrees).

    warn at `warn_at`, refuse at `refuse_at` unless `override`. Every request that is SENT is counted (conservative: a failed
    request may or may not be billed). The key is never stored here."""

    def __init__(self, path: str, provider: str, warn_at: int = 1500, refuse_at: int = 2300, override: bool = False, warn=print):
        self.path, self.provider, self.warn_at, self.refuse_at, self.override, self._warn = path, provider, warn_at, refuse_at, override, warn
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    def used(self) -> int:
        try:
            return int(json.load(open(self.path, encoding="utf-8")).get(self.provider, {}).get("queries", 0))
        except (OSError, ValueError):
            return 0

    def spend(self, n: int = 1) -> int:
        """Count n queries about to be sent; raise BudgetExceeded when that would pass the refuse limit."""
        with self._lock:
            try:
                data = json.load(open(self.path, encoding="utf-8"))
            except (OSError, ValueError):
                data = {}
            cur = int(data.get(self.provider, {}).get("queries", 0))
            if cur + n > self.refuse_at and not self.override:
                raise BudgetExceeded(f"{self.provider} query budget: {cur} used, limit {self.refuse_at} (override needed)")
            new = cur + n
            if cur < self.warn_at <= new:
                self._warn(f"WARNING: {self.provider} queries used: {new} (warn level {self.warn_at}, refuse level {self.refuse_at})")
            data[self.provider] = {"queries": new, "updated": time.strftime("%Y-%m-%d %H:%M:%S")}
            tmp = f"{self.path}.{uuid.uuid4().hex}.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f)
            os.replace(tmp, self.path)
            return new


def default_budget_path() -> str:
    return os.path.join(os.environ.get("EVRET_BUDGET_DIR") or os.path.join(os.path.expanduser("~"), ".evret"), "query_budget.json")


class SerperProvider(SearchProvider):
    """Google results through serper.dev (the engine family of AVeriTeC's annotation and baseline).

    POST https://google.serper.dev/search, header X-API-KEY (from the environment, never logged or stored), JSON body
    {q, gl, hl, num, autocorrect=false}. `autocorrect` is switched off so that the engine does not silently rewrite the claim text.
    1 credit per query with num <= 10. An empty organic list is a genuine answer (cached, not retried)."""
    name = "serper"
    empty_is_failure = False
    min_interval = 1.0
    ENDPOINT = "https://google.serper.dev/search"

    def __init__(self, budget: QueryBudget | None = None, gl: str = "us", hl: str = "en", api_key: str | None = None,
                 http_post=None, env_var: str = "SERPER_API_KEY", netlog=None):
        self.gl, self.hl, self._key, self._env, self._post = gl, hl, api_key, env_var, http_post
        self.budget = budget if budget is not None else QueryBudget(default_budget_path(), "serper",
                                                                    override=bool(os.environ.get("EVRET_BUDGET_OVERRIDE")))
        self.netlog, self.last_credits = netlog, None

    @property
    def backend(self) -> str:
        return "google"

    @property
    def version(self) -> str:
        return "serper-search-v1"                # the API has no version number; bump when the request/response contract changes

    @property
    def params(self) -> dict:
        return {"gl": self.gl, "hl": self.hl, "autocorrect": False}

    def _api_key(self) -> str:
        key = self._key or os.environ.get(self._env)
        if not key:
            raise NonRetryable(f"environment variable {self._env} is not set")
        return key

    def search(self, query: str, n: int) -> list[SearchResult]:
        key = self._api_key()
        if n > 10:
            raise ValueError("num > 10 costs 2 credits per query; not used")
        self.budget.spend(1)
        post = self._post
        if post is None:
            import httpx

            def post(url, headers, body):
                r = httpx.post(url, headers=headers, json=body, timeout=30)
                return r.status_code, (r.json() if r.status_code == 200 else {"message": r.text[:120]})
        status, data = post(self.ENDPOINT, {"X-API-KEY": key, "Content-Type": "application/json"},
                            {"q": query, "gl": self.gl, "hl": self.hl, "num": n, "autocorrect": False})
        if status != 200:
            msg = f"serper http {status}: {str(data.get('message', ''))[:100]}"
            if status in (400, 401, 402, 403):
                raise NonRetryable(msg)
            raise RuntimeError(msg)
        self.last_credits = data.get("credits")
        rows = [SearchResult((d.get("link") or "").strip(), d.get("title") or "", d.get("snippet") or "", "google", 0)
                for d in sorted(data.get("organic", []), key=lambda d: d.get("position", 0))]
        return _rank(rows, n)


class RateLimiter:
    """Spaces calls at least `interval` seconds apart; clock and sleep are injectable for tests."""

    def __init__(self, interval: float = MIN_INTERVAL, clock=time.monotonic, sleep=time.sleep):
        self.interval, self.clock, self.sleep, self._last = interval, clock, sleep, None

    def wait(self):
        if self._last is not None:
            gap = self.interval - (self.clock() - self._last)
            if gap > 0:
                self.sleep(gap)
        self._last = self.clock()


def with_backoff(fn, attempts: int = MAX_ATTEMPTS, base: float = BACKOFF_BASE, sleep=time.sleep):
    """Call fn(); on an exception wait base * 2**i and retry; re-raise after the last attempt."""
    for i in range(attempts):
        try:
            return fn()
        except NonRetryable:
            raise
        except Exception:
            if i == attempts - 1:
                raise
            sleep(base * 2 ** i)


class SearchCache:
    """SQLite cache: key = hash of (provider, backend, version, query, params) -> results + timestamp."""

    def __init__(self, path: str):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("CREATE TABLE IF NOT EXISTS search (key TEXT PRIMARY KEY, provider TEXT, backend TEXT, "
                        "version TEXT, query TEXT, params TEXT, results TEXT, ts REAL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS failures (key TEXT PRIMARY KEY, error TEXT, ts REAL)")
        self.db.commit()

    @staticmethod
    def key(provider: str, backend: str, version: str, query: str, params: dict) -> str:
        blob = json.dumps([provider, backend, version, query, params], sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def get(self, key: str):
        row = self.db.execute("SELECT results, ts FROM search WHERE key=?", (key,)).fetchone()
        if not row:
            return None
        return [SearchResult(**d) for d in json.loads(row[0])], row[1]

    def put(self, key, provider, backend, version, query, params, results, ts):
        self.db.execute("INSERT OR REPLACE INTO search VALUES (?,?,?,?,?,?,?,?)",
                        (key, provider, backend, version, query, json.dumps(params, sort_keys=True),
                         json.dumps([r.__dict__ for r in results], ensure_ascii=False), ts))
        self.db.execute("DELETE FROM failures WHERE key=?", (key,))             # a later success replaces a recorded failure
        self.db.commit()

    def put_failure(self, key: str, error: str, ts: float):
        self.db.execute("INSERT OR REPLACE INTO failures VALUES (?,?,?)", (key, error, ts))
        self.db.commit()

    def get_failure(self, key: str):
        row = self.db.execute("SELECT error FROM failures WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def manifest(self) -> list[tuple]:
        """(key, results-json) of every entry in key order. Timestamps are left out so re-fetching identical results keeps the hash."""
        rows = self.db.execute("SELECT key, results FROM search ORDER BY key").fetchall()
        return rows + [(k, "FAILED:" + e) for k, e in self.db.execute("SELECT key, error FROM failures ORDER BY key")]


class CachedSearch:
    """provider + cache + spacing + backoff + call log. `search(query)` is what the web tool calls."""

    def __init__(self, provider: SearchProvider, cache: SearchCache, mode: Mode = Mode.LIVE, n: int = 10,
                 limiter: RateLimiter | None = None, netlog: NetLog | None = None, clock=time.time, sleep=time.sleep):
        self.provider, self.cache, self.mode, self.n = provider, cache, mode, n
        self.limiter = limiter or RateLimiter(provider.min_interval or MIN_INTERVAL, sleep=sleep)
        self.netlog, self.clock, self.sleep = netlog or NetLog(), clock, sleep

    def search(self, query: str) -> list[SearchResult]:
        p = self.provider
        params = {**p.params, "n": self.n}
        key = SearchCache.key(p.name, p.backend, p.version, query, params)
        hit = self.cache.get(key)
        if hit is not None:
            return hit[0]
        if self.mode == Mode.REPLAY:
            err = self.cache.get_failure(key)
            if err is not None:
                raise RecordedFailure(err)
            raise ReplayMiss(f"search not in cache: {p.name}/{p.backend} {query!r}")

        def call():
            self.limiter.wait()                       # every attempt is a network call, so every attempt is spaced
            t0 = self.clock()
            try:
                res = p.search(query, self.n)
            except Exception as e:
                self.netlog.log("search", f"{p.name}/{p.backend}: {query}", f"error:{type(e).__name__}", self.clock() - t0)
                raise
            if not res and p.empty_is_failure:
                self.netlog.log("search", f"{p.name}/{p.backend}: {query}", "error:EmptyResult", self.clock() - t0)
                raise EmptyResult(f"{p.name}/{p.backend} returned no results")
            self.netlog.log("search", f"{p.name}/{p.backend}: {query}", "ok", self.clock() - t0, n=len(res))
            return res
        try:
            res = with_backoff(call, sleep=self.sleep)
        except NonRetryable:
            raise                                   # missing key / no credit / budget: a setup problem, not a property of the query
        except Exception as e:
            self.cache.put_failure(key, f"{type(e).__name__}: {str(e)[:120]}", self.clock())
            raise
        self.cache.put(key, p.name, p.backend, p.version, query, params, res, self.clock())
        return res
