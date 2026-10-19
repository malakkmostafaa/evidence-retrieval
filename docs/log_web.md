# LOG (web tool)

## 2026-10-19 (WS0-WS1)
- Tried: read corpus code and decisions; wrote plan and decisions; asked WQ1-4; new venv; providers (ddgs, SearXNG), rate limiter, backoff, search cache with replay; one live ddgs probe of 7 backends.
- Happened: 9 tests pass; 7/7 injected bugs caught (limiter, cache key, backoff, replay, rank numbering, URL dedupe, cache write). Failed attempt: my first multi-file shell heredoc broke on a quote, nothing was written (files are now written with the file tool). egg-info files are tracked in git and changed by `pip install -e` (reverted).
- Next: WS2 fetcher + Wayback + page cache.
