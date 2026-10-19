## Funnel (URLs over all claims; each URL counted once)

| step | main | lenient | factcheck |
|---|---|---|---|
| returned | 121 (100%) | 121 (100%) | 121 (100%) |
| date_unknown | 1 (1%) | 0 (0%) | 1 (1%) |
| dated_after | 31 (26%) | 31 (26%) | 40 (33%) |
| factcheck | 23 (19%) | 23 (19%) | 0 (0%) |
| fetch_http_402 | 1 (1%) | 1 (1%) | 1 (1%) |
| fetch_http_403 | 16 (13%) | 16 (13%) | 22 (18%) |
| fetch_http_429 | 3 (2%) | 3 (2%) | 3 (2%) |
| fetch_robots_blocked | 3 (2%) | 3 (2%) | 6 (5%) |
| fetch_timeout | 1 (1%) | 1 (1%) | 1 (1%) |
| own_article | 5 (4%) | 5 (4%) | 5 (4%) |
| tiny | 0 (0%) | 1 (1%) | 0 (0%) |
| kept | 37 (31%) | 37 (31%) | 42 (35%) |

## Wayback coverage (URLs that reached the lookup)

| cond | looked up | snapshot found | none | error | dated <= | dated after | unknown |
|---|---|---|---|---|---|---|---|
| main | 93 | 23 (25%) | 70 | 0 | 37 | 31 | 1 |
| lenient | 93 | 23 (25%) | 70 | 0 | 37 | 31 | 1 |
| factcheck | 116 | 23 (20%) | 83 | 10 | 42 | 40 | 1 |

## Gold-URL hits (claims with >= 1 gold URL; n claims = 15 per condition)

| cond | group | claims | in engine results | in fetched pages | in kept pages | top-5 | top-10 | top-50 |
|---|---|---|---|---|---|---|---|---|
| main | pooled | 5 | 0 | 0 | 0 | 0 | 0 | 0 |
| main | held-out | 10 | 1 | 1 | 1 | 0 | 1 | 1 |
| main | all | 15 | 1 | 1 | 1 | 0 | 1 | 1 |
| lenient | pooled | 5 | 0 | 0 | 0 | 0 | 0 | 0 |
| lenient | held-out | 10 | 1 | 1 | 1 | 0 | 1 | 1 |
| lenient | all | 15 | 1 | 1 | 1 | 0 | 1 | 1 |
| factcheck | pooled | 5 | 0 | 0 | 0 | 0 | 0 | 0 |
| factcheck | held-out | 10 | 1 | 1 | 1 | 0 | 1 | 1 |
| factcheck | all | 15 | 1 | 1 | 1 | 0 | 1 | 1 |

Fate of every gold URL that the engine returned (main condition):

41 gold URLs in total; returned by the engine: 2; fate: kept: 2

## Search outcome (queries; engine = ddgs/duckduckgo)

- main: 13 of 15 claim queries returned results; 2 failed (error or empty answer after 4 attempts): claims 485, 269
- lenient: 13 of 15 claim queries returned results; 2 failed (error or empty answer after 4 attempts): claims 485, 269
- factcheck: 13 of 15 claim queries returned results; 2 failed (error or empty answer after 4 attempts): claims 485, 269

## Seconds per claim (main condition; cold = the claim's pages were not cached yet, i.e. Wayback time > 0.5 s)

| step | mean s/claim | share of step time |
|---|---|---|
| search | 3.6 | 8% |
| wayback | 13.6 | 29% |
| fetch | 24.8 | 53% |
| extract | 1.0 | 2% |
| chunk | 0.0 | 0% |
| embed | 3.5 | 8% |
| select | 0.0 | 0% |
| **total (wall)** | 46.7 | |

n = 9 cold claims (of 15).

Passages per claim (mean): 39.4; claims with 0 passages: 2.