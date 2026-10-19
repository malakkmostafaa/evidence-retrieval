# LOG (web tool)

## 2026-10-19 (WS0-WS1)
- Tried: read corpus code and decisions; wrote plan and decisions; asked WQ1-4; new venv; providers (ddgs, SearXNG), rate limiter, backoff, search cache with replay; one live ddgs probe of 7 backends.
- Happened: 9 tests pass; 7/7 injected bugs caught (limiter, cache key, backoff, replay, rank numbering, URL dedupe, cache write). Failed attempt: my first multi-file shell heredoc broke on a quote, nothing was written (files are now written with the file tool). egg-info files are tracked in git and changed by `pip install -e` (reverted).
- Next: WS2 fetcher + Wayback + page cache.

## 2026-10-19 (WS2)
- Tried: page cache (SQLite + compressed blobs), polite fetcher, Wayback CDX lookup; probed the real CDX API and one real snapshot fetch.
- Happened: 16 tests pass + 1 live smoke test (CDX + snapshot of bbc.com/news, 8.6 s). Mutation check: 13/13 injected bugs caught after one fix. Failed attempts: (1) a thread race (two threads wrote the same blob temp file -> PermissionError) found by the parallel-hosts test, fixed with unique temp names; (2) my size-cap test only exercised the Content-Length shortcut, so the off-by-one mutation in the streaming path survived - added a chunked-body test, then it was caught.
- Next: WS3 extraction, dates, leakage filters.

## 2026-10-19 (WS3)
- Tried: extraction (trafilatura, pypdf, htmldate, URL date), date filter, own-article and fact-check URL filters; fixtures: pages dated before / after / unknown, a PDF built byte by byte, wrapped own-article URL.
- Happened: 11 tests pass; 14/14 injected bugs caught after two test fixes. Failed attempts: (1) htmldate given the URL returned the URL's date labelled "htmldate" (test found it; URL no longer passed); (2) my fact-check test for a wrapped URL was too weak because the path alone matched the regex, so a mutation survived - changed to a URL where only the unwrapped host reveals the fact-checker; (3) comment-stripping was untested - added a fixture.
- Next: WS4 chunking + first-pass selection + Hit schema + equivalence test.

## 2026-10-19 (WS4)
- Tried: WebHit (subclass of the corpus Hit), pool statistics (N, avgdl, df from term offsets), BM25 and RRF for web passages, per-page chunk/vector cache, equivalence test against the corpus Hybrid.
- Happened: 8 tests pass; 14/14 injected bugs caught (3 initially survived: df=0 term, query-vs-passage encoder, RRF depth - tests added). CPU embedding speed measured: 16.5 chunks/s. Failed attempt: my first new test used frozen stats without the query term and raised the intended KeyError (correct behaviour, test fixed).
- Next: WS5 - assemble search_web, evaluation layer, run 10 held-out + 5 pooled claims, write docs/reports/web_tool_v1.md.
