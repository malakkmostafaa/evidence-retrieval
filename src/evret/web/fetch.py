"""WS2 - polite fetcher (WD4, WD7) and Wayback lookup (WD2).

Rules implemented here: honest User-Agent, robots.txt, one request at a time per host (a few hosts in parallel),
minimum spacing per host (1 s for archive.org), timeouts, retries with backoff on transient errors, 25 MB cap
(`too_large` is recorded, a page is never silently cut), every network call logged, cache first, REPLAY = no network.

robots.txt: 4xx -> no restrictions (RFC 9309); 5xx or unreachable -> treated as disallowed (RFC 9309). robots is NOT applied to
web.archive.org (the snapshot is a copy that the archive serves under its own policy).
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.robotparser
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import httpx

from evret.web.netlog import NetLog
from evret.web.pagecache import PageCache, PageRecord, page_key
from evret.web.providers import RateLimiter
from evret.web.schema import Mode, ReplayMiss

UA_TOKEN = "evret-thesis-bot"
USER_AGENT = f"{UA_TOKEN}/0.1 (academic research, bachelor thesis; non-commercial; polite: 1 request at a time per host)"
MAX_BYTES = 25 * 1024 * 1024
RETRY_STATUS = {429, 500, 502, 503, 504}
ATTEMPTS = 3
BACKOFF = 1.0                         # waits 1 s, 2 s between the 3 attempts
DEADLINE = 45.0                       # seconds for one request incl. download
ARCHIVE_HOST = "web.archive.org"
HOST_INTERVAL = {ARCHIVE_HOST: 1.0}   # minimum seconds between requests to the same host


def host_of(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def snapshot_url(timestamp: str, original: str) -> str:
    """Raw (id_) form of a Wayback capture: original bytes, no toolbar (WQ4)."""
    return f"https://{ARCHIVE_HOST}/web/{timestamp}id_/{original}"


class Fetcher:
    def __init__(self, cache: PageCache, mode: Mode = Mode.LIVE, client: httpx.Client | None = None,
                 netlog: NetLog | None = None, max_bytes: int = MAX_BYTES, user_agent: str = USER_AGENT,
                 sleep=time.sleep, clock=time.monotonic, workers: int = 4, respect_robots: bool = True):
        self.cache, self.mode, self.netlog = cache, mode, netlog or NetLog()
        self.client = client or httpx.Client(timeout=httpx.Timeout(20.0, connect=10.0), follow_redirects=True,
                                             max_redirects=5)
        self.max_bytes, self.ua, self.sleep, self.clock = max_bytes, user_agent, sleep, clock
        self.workers, self.respect_robots = workers, respect_robots
        self._gates: dict[str, tuple[threading.Lock, RateLimiter]] = {}
        self._gates_lock = threading.Lock()
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None | bool] = {}

    # ---------------------------------------------------------------- per-host gate
    def _gate(self, host: str):
        with self._gates_lock:
            if host not in self._gates:
                self._gates[host] = (threading.Lock(), RateLimiter(HOST_INTERVAL.get(host, 0.0), self.clock, self.sleep))
            return self._gates[host]

    # ---------------------------------------------------------------- one HTTP exchange (with retries)
    def _request(self, url: str, kind: str, params: dict | None = None):
        """-> (status_label, http_status, content_type, final_url, body|None). Holds the host gate for the whole exchange."""
        lock, limiter = self._gate(host_of(url))
        with lock:
            status, http, ctype, final, body = "error", None, "", url, None
            for attempt in range(ATTEMPTS):
                limiter.wait()
                t0 = self.clock()
                try:
                    status, http, ctype, final, body = self._stream(url, params)
                except httpx.TimeoutException:
                    status, http, ctype, final, body = "timeout", None, "", url, None
                except httpx.HTTPError as e:
                    status, http, ctype, final, body = f"error:{type(e).__name__}", None, "", url, None
                self.netlog.log(kind, url, status, self.clock() - t0, attempt=attempt + 1,
                                bytes=None if body is None else len(body))
                transient = status in ("timeout",) or status.startswith("error:") or (http in RETRY_STATUS)
                if not transient or attempt == ATTEMPTS - 1:
                    break
                self.sleep(BACKOFF * 2 ** attempt)
            return status, http, ctype, final, body

    def _stream(self, url, params):
        t0 = self.clock()
        with self.client.stream("GET", url, params=params, headers={"User-Agent": self.ua}) as r:
            ctype, final = r.headers.get("content-type", ""), str(r.url)
            if r.status_code != 200:
                return f"http_{r.status_code}", r.status_code, ctype, final, None
            cl = r.headers.get("content-length")
            if cl and cl.isdigit() and int(cl) > self.max_bytes and not r.headers.get("content-encoding"):
                return "too_large", 200, ctype, final, None
            buf, n = [], 0
            for part in r.iter_bytes():
                n += len(part)
                if n > self.max_bytes:
                    return "too_large", 200, ctype, final, None
                if self.clock() - t0 > DEADLINE:
                    raise httpx.ReadTimeout("deadline exceeded")
                buf.append(part)
            return "ok", 200, ctype, final, b"".join(buf)

    # ---------------------------------------------------------------- robots.txt
    def allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        host = host_of(url)
        if host == ARCHIVE_HOST:
            return True
        scheme = urlparse(url).scheme or "https"
        if host not in self._robots:
            status, http, _, _, body = self._request(f"{scheme}://{host}/robots.txt", "robots")
            rp = urllib.robotparser.RobotFileParser()
            if status == "ok":
                rp.parse(body.decode("utf-8", "replace").splitlines())
                self._robots[host] = rp
            elif http is not None and 400 <= http < 500:
                self._robots[host] = True                      # no robots.txt -> everything allowed
            else:
                self._robots[host] = False                     # 5xx / unreachable -> disallowed (RFC 9309)
        r = self._robots[host]
        return r if isinstance(r, bool) else r.can_fetch(UA_TOKEN, url)

    # ---------------------------------------------------------------- public API
    def get(self, url: str, wayback_ts: str | None = None) -> tuple[PageRecord, bytes | None]:
        """Fetch a page live (wayback_ts=None) or its Wayback snapshot. Cache first; REPLAY never touches the network."""
        key = page_key(url, wayback_ts)
        rec = self.cache.get_page(key)
        if rec is not None:
            return rec, (self.cache.get_body(rec.raw_hash) if rec.raw_hash else None)
        if self.mode == Mode.REPLAY:
            raise ReplayMiss(f"page not in cache: {key}")
        if wayback_ts is None and not self.allowed(url):
            rec = PageRecord(key, url, None, "robots_blocked", None, "", url, None, 0, time.time())
            self.cache.put_page(rec, None)
            return rec, None
        target = snapshot_url(wayback_ts, url) if wayback_ts else url
        status, http, ctype, final, body = self._request(target, "fetch" if not wayback_ts else "fetch_wayback")
        h = PageCache.sha256(body) if body is not None else None
        rec = PageRecord(key, url, wayback_ts, status, http, ctype, final, h, 0 if body is None else len(body), time.time())
        self.cache.put_page(rec, body)
        return rec, body

    def get_many(self, items: list[tuple[str, str | None]]):
        """Parallel across hosts, serial within a host (the gate). Results in input order."""
        with ThreadPoolExecutor(max_workers=self.workers) as ex:
            return list(ex.map(lambda it: self.get(*it), items))


class Wayback:
    """CDX lookup: newest status-200 capture of `url` at or before the claim date (WQ3), cached and replayable."""

    CDX = f"https://{ARCHIVE_HOST}/cdx/search/cdx"

    def __init__(self, fetcher: Fetcher):
        self.f = fetcher

    def closest_before(self, url: str, claim_date: str) -> tuple[str, str] | None:
        """-> (timestamp, original url of the capture) or None. claim_date = 'YYYY-MM-DD'."""
        cache = self.f.cache
        found, ts, orig = cache.get_lookup(url, claim_date)
        if found:
            return (ts, orig) if ts else None
        if self.f.mode == Mode.REPLAY:
            raise ReplayMiss(f"wayback lookup not in cache: {url} <= {claim_date}")
        params = {"url": url, "output": "json", "fl": "timestamp,original,statuscode,mimetype,digest",
                  "filter": "statuscode:200", "to": claim_date.replace("-", "") + "235959", "limit": "-1"}
        status, http, _, _, body = self.f._request(self.CDX, "cdx", params)
        if status != "ok":
            raise RuntimeError(f"CDX lookup failed ({status}) for {url}")         # not cached: a failure is not 'no snapshot'
        res = parse_cdx(body, claim_date)
        cache.put_lookup(url, claim_date, *(res or (None, None)), now=time.time())
        return res


_TS = re.compile(r"^\d{14}$")


def parse_cdx(body: bytes, claim_date: str) -> tuple[str, str] | None:
    """Last row of a CDX JSON answer (header row skipped); defensively re-checks the timestamp bound."""
    rows = json.loads(body.decode("utf-8")) if body.strip() else []
    rows = [r for r in rows[1:] if len(r) >= 2 and _TS.match(r[0])]
    bound = claim_date.replace("-", "") + "235959"
    rows = [r for r in rows if r[0] <= bound]
    return (rows[-1][0], rows[-1][1]) if rows else None
