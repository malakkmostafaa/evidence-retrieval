# LOG (web tool)

## 2026-10-19 (WS0-WS1)
- Tried: read corpus code and decisions; wrote plan and decisions; asked WQ1-4; new venv; providers (ddgs, SearXNG), rate limiter, backoff, search cache with replay; one live ddgs probe of 7 backends.
- Happened: 9 tests pass; 7/7 injected bugs caught (limiter, cache key, backoff, replay, rank numbering, URL dedupe, cache write). Failed attempt: my first multi-file shell heredoc broke on a quote, nothing was written (files are now written with the file tool). egg-info files are tracked in git and changed by `pip install -e` (reverted).
- Next: WS2 fetcher + Wayback + page cache.

## 2026-10-19 (WS2)
- Tried: page cache (SQLite + compressed blobs), polite fetcher, Wayback CDX lookup; probed the real CDX API and one real snapshot fetch.
- Happened: 16 tests pass + 1 live smoke test (CDX + snapshot of bbc.com/news, 8.6 s). Mutation check: 13/13 injected bugs caught after one fix. Failed attempts: (1) a thread race (two threads wrote the same blob temp file -> PermissionError) found by the parallel-hosts test, fixed with unique temp names; (2) my size-cap test only exercised the Content-Length shortcut, so the off-by-one mutation in the streaming path survived - added a chunked-body test, then it was caught.
- Next: WS3 extraction, dates, leakage filters.
