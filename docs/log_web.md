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


## 2026-10-19 (WS5)
- Tried: search_web assembly (filters, Wayback, fetch, extract, date filter, chunk/embed, select), evaluation layer, live smoke run on 15 claims x 3 conditions, replay checks, report.
- Happened: 118 tests pass; replay = 45/45 identical, 0 network calls, same manifest hash. Failed attempts: (1) the first live run crashed on claim 485 because the engine raised after 4 retries -> failures are now recorded and the run continues; (2) three claims' main runs had failed searches while the ablations succeeded -> resumable run that redoes failed searches; (3) empty engine answers had been cached as results (2 entries) -> now failures, entries purged; (4) replay differed from live in the 16th digit because the BM25 sum order depended on PYTHONHASHSEED -> sorted terms + test; (5) NetLog lines interleaved across threads -> lock + test; (6) a Windows race when two threads stored identical blob content (found by a test) -> fixed. Findings: 62 of 81 search attempts failed; 26% of URLs dated after the claim; Wayback covers 25%; 1 of 15 claims has a gold URL in the results.
- Next: Malak decides WQ5-WQ9; then merge docs_web files into DECISIONS.md / LOG.md and hand the WebHit candidates to the shared reranker block.

## 2026-10-19 (diagnosis after WS5)
- Tried: read the failures from the cache (netlog, failures table), 4 probe calls to the engine, per-claim gold funnel, content-word coverage proxy, provider options.
- Happened: failures = DuckDuckGo anomaly page (HTTP 202) hidden by ddgs as No results found; clusters after ~7 queries and lasts minutes; gold funnel: 41 gold URLs, 2 returned, those 2 reach the top-10; coverage proxy (new, the earlier experiments had none) 0.20 / 0.24 / 0.26 at k = 5 / 10 / 50 in main. No provider switched. See docs/reports/web_tool_v1_diagnosis.md.
- Next: Malak chooses the provider (WQ5).

## 2026-10-19 (Serper)
- Tried: SerperProvider (env key, persisted query budget 1500/2300, 4xx not retried, empty answer cached, autocorrect off), provider lock per cache directory; live smoke run on the same 15 claims; replay.
- Happened: 15 live queries (15 of 2,500 used); replay = identical, 0 queries; 1 distinct gold page returned (claim 418) and it reaches the top-5; kept 31% of URLs; 29 s per claim; 3 claims with quotation marks gave 0-4 results. Removed my own coverage proxy from the diagnosis on request (to be re-added with the ported original). Failed attempts: none in the run; mutation check found one unguarded line (num > 10) and a test was added.
- Next: Malak decides WQ8 (quotation marks); then 300-claim run (300 queries).

## 2026-10-19 (pool main run)
- Tried: quotation-mark fallback, pool-only claim list (ranks 0-179), main condition with Serper on 3 CPU threads, replay check.
- Happened: 180/180 claims searched (148 new queries, 191 total used), 2 fallbacks, 24% of URLs kept, 11 claims with a gold page in the top-50, 31.6 s per claim. Failed attempt: replay raised KeyError because the frozen df were written only at the end of a run and the stopped run had not written them -> now frozen up front and after every claim; replay then identical.
- Next: wait for approval for lenient / fact-check conditions.

## 2026-10-20 (coverage vs corpus, lenient)
- Tried: metrics_cov (merged by Malak) on the web top-50, corpus re-run on CPU for per-claim values, paired bootstrap; lenient pre-registered, replayed from cache, compared paired against main.
- Happened: corpus numbers reproduce the corpus report (to 0.001); web CovNovel@512 0.273 vs corpus dense 0.403 / hybrid 0.376 (paired -0.13 / -0.10, CIs exclude 0), vs BM25 -0.04 (CI includes 0); lenient +0.015 to +0.020, CIs include 0, 9 of 88-91 claims change, 17 of 27 added pages mention years after 2020. 0 queries, 0 network calls (counter 191). Failed attempt: none in the runs; the per-claim corpus values had to be recomputed because only means were stored.
- Next: fact-check condition (leakage diagnostic) only after approval.

## 2026-10-20 (fact-check diagnostic)
- Tried: fact-check condition on the 180 pool claims (no queries; new page fetches), replay check, paired comparison against main.
- Happened: 46 of 175 fact-check URLs kept (67 dated after, 59 blocked); CovNovel +0.024 [-0.002,+0.052], CovUnion +0.033 [+0.005,+0.065]; no gold gain; replay identical, counter unchanged (191). Found: 2 URLs differed for a non-planned reason (transient Wayback lookup errors in main). Corrected an earlier statement: the 10 gold entries lost as fact-check domains are 3 distinct pages.
- Next: nothing pending; sealed claims not touched.

## 2026-10-20 (oracle router)
- Tried: pre-registered web vs own-store-removed corpus + oracle router; checked data availability first.
- Happened: per-claim values for the own-store-removed corpus do not exist (aggregates only; one NaN mean), so that comparison is pending a per-claim file from the corpus session; oracle router computed for the normal corpus from existing per-claim values: gain over best single +0.04 to +0.08 (all claims), +0.045 to +0.09 (claims with a web page); 0 queries, no retrieval.
- Next: corpus session saves per-claim arrays; then run oracle_router --label own_store_removed and the paired table.
