## Funnel (URLs over all claims; each URL counted once)

| step | main |
|---|---|
| returned | 1765 (100%) |
| date_unknown | 38 (2%) |
| dated_after | 433 (25%) |
| factcheck | 175 (10%) |
| fetch_error:RemoteProtocolError | 1 (0%) |
| fetch_http_202 | 1 (0%) |
| fetch_http_203 | 1 (0%) |
| fetch_http_307 | 2 (0%) |
| fetch_http_403 | 241 (14%) |
| fetch_http_405 | 2 (0%) |
| fetch_http_406 | 4 (0%) |
| fetch_http_429 | 9 (1%) |
| fetch_robots_blocked | 346 (20%) |
| fetch_timeout | 5 (0%) |
| fetch_too_large | 2 (0%) |
| no_text | 5 (0%) |
| own_article | 53 (3%) |
| tiny | 31 (2%) |
| kept | 416 (24%) |

## Wayback coverage (URLs that reached the lookup)

| cond | looked up | snapshot found | none | error | dated <= | dated after | unknown |
|---|---|---|---|---|---|---|---|
| main | 1537 | 300 (20%) | 1196 | 41 | 452 | 433 | 38 |

## Gold-URL hits (claims with >= 1 gold URL; n claims = 180 per condition)

| cond | group | claims | in engine results | in fetched pages | in kept pages | top-5 | top-10 | top-50 |
|---|---|---|---|---|---|---|---|---|
| main | pooled | 180 | 16 | 11 | 11 | 9 | 10 | 11 |
| main | held-out | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| main | all | 180 | 16 | 11 | 11 | 9 | 10 | 11 |

Fate of every gold URL that the engine returned (main condition):

481 gold URLs in total; returned by the engine: 28; fate: kept: 15, factcheck: 10, fetch_robots_blocked: 3

## Search outcome (queries)

- main: 180 of 180 claim queries returned results; 0 returned no results (failed or empty answer): claims 

## Seconds per claim (main condition; cold = the claim's pages were not cached yet, i.e. Wayback time > 0.5 s)

| step | mean s/claim | share of step time |
|---|---|---|
| search | 2.4 | 8% |
| wayback | 11.9 | 38% |
| fetch | 10.6 | 34% |
| extract | 1.2 | 4% |
| chunk | 0.0 | 0% |
| embed | 5.4 | 17% |
| select | 0.0 | 0% |
| **total (wall)** | 31.6 | |

n = 169 cold claims (of 180).

Passages per claim (mean): 39.1; claims with 0 passages: 33.