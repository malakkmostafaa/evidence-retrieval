## Funnel (URLs over all claims; each URL counted once)

| step | main | lenient | factcheck |
|---|---|---|---|
| returned | 121 (100%) | 121 (100%) | 121 (100%) |
| date_unknown | 3 (2%) | 0 (0%) | 3 (2%) |
| dated_after | 19 (16%) | 19 (16%) | 24 (20%) |
| factcheck | 12 (10%) | 12 (10%) | 0 (0%) |
| fetch_http_403 | 15 (12%) | 15 (12%) | 19 (16%) |
| fetch_robots_blocked | 29 (24%) | 29 (24%) | 30 (25%) |
| own_article | 4 (3%) | 4 (3%) | 4 (3%) |
| tiny | 1 (1%) | 1 (1%) | 1 (1%) |
| kept | 38 (31%) | 41 (34%) | 40 (33%) |

## Wayback coverage (URLs that reached the lookup)

| cond | looked up | snapshot found | none | error | dated <= | dated after | unknown |
|---|---|---|---|---|---|---|---|
| main | 105 | 21 (20%) | 81 | 3 | 39 | 19 | 3 |
| lenient | 105 | 21 (20%) | 81 | 3 | 39 | 19 | 3 |
| factcheck | 117 | 22 (19%) | 92 | 3 | 41 | 24 | 3 |

## Gold-URL hits (claims with >= 1 gold URL; n claims = 15 per condition)

| cond | group | claims | in engine results | in fetched pages | in kept pages | top-5 | top-10 | top-50 |
|---|---|---|---|---|---|---|---|---|
| main | pooled | 5 | 0 | 0 | 0 | 0 | 0 | 0 |
| main | held-out | 10 | 1 | 1 | 1 | 1 | 1 | 1 |
| main | all | 15 | 1 | 1 | 1 | 1 | 1 | 1 |
| lenient | pooled | 5 | 0 | 0 | 0 | 0 | 0 | 0 |
| lenient | held-out | 10 | 1 | 1 | 1 | 1 | 1 | 1 |
| lenient | all | 15 | 1 | 1 | 1 | 1 | 1 | 1 |
| factcheck | pooled | 5 | 0 | 0 | 0 | 0 | 0 | 0 |
| factcheck | held-out | 10 | 1 | 1 | 1 | 1 | 1 | 1 |
| factcheck | all | 15 | 1 | 1 | 1 | 1 | 1 | 1 |

Fate of every gold URL that the engine returned (main condition):

41 gold URLs in total; returned by the engine: 3; fate: kept: 3

## Search outcome (queries)

- main: 13 of 15 claim queries returned results; 2 returned no results (failed or empty answer): claims 331, 269
- lenient: 13 of 15 claim queries returned results; 2 returned no results (failed or empty answer): claims 331, 269
- factcheck: 13 of 15 claim queries returned results; 2 returned no results (failed or empty answer): claims 331, 269

## Seconds per claim (main condition; cold = the claim's pages were not cached yet, i.e. Wayback time > 0.5 s)

| step | mean s/claim | share of step time |
|---|---|---|
| search | 3.1 | 11% |
| wayback | 11.5 | 40% |
| fetch | 8.4 | 29% |
| extract | 2.8 | 10% |
| chunk | 0.0 | 0% |
| embed | 3.0 | 11% |
| select | 0.0 | 0% |
| **total (wall)** | 29.0 | |

n = 13 cold claims (of 15).

Passages per claim (mean): 31.8; claims with 0 passages: 1.