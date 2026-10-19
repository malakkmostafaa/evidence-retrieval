# Diagnosis of the web smoke run (cached data; 4 extra probe calls to the engine)

## 1. Search failures

15 search attempts logged: ok: 15.

Provider serper/google: official API, no bot challenge; every attempt is one billed request. Per-query timeline omitted.

## 2. Gold-URL funnel (main condition)

Order of the pipeline: search returned the URL -> not removed by the URL filters (own article / fact-check) -> fetch OK -> date filter passed -> enough text -> in top-N passages (N = 50).

| claim | grp | gold URLs | search ok | returned | url filters | fetched | date | text | top-50 passages | top-10 |
|---|---|---|---|---|---|---|---|---|---|---|
| 272 | pool | 3 | yes | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 443 | pool | 2 | yes | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 9 | pool | 1 | yes | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 203 | pool | 3 | yes | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 277 | pool | 4 | yes | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 208 | held | 5 | yes | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 331 | held | 1 | FAILED | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 485 | held | 3 | yes | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 124 | held | 1 | yes | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 37 | held | 2 | yes | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 418 | held | 5 | yes | 3 | 3 | 3 | 3 | 3 | 3 | 3 |
| 188 | held | 3 | yes | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 269 | held | 5 | FAILED | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 184 | held | 2 | yes | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 111 | held | 1 | yes | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| **sum** | | 41 | | 3 | 3 | 3 | 3 | 3 | 3 | 3 |

Gold URL properties: 15 of 41 are Wayback wrappers; the gold *host* appears among the engine results for 8 of 41 gold URLs (exact URL: 3). Dead links / redirects of the gold URLs cannot be judged from the cache (they were never requested, only the gold URLs the engine returned were). Checking all gold URLs would need 41 CDX lookups + 41 fetches (about 5 minutes); not run, waiting for approval.