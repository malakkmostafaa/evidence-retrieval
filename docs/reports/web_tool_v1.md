# Web tool v1 - smoke evaluation (WS5)

Date: 2026-10-19. Code: `src/evret/web/`. Raw results: `outputs/web_smoke/` (results.json, summary.md, manual_review.md, manifest.json, logs/).
**Descriptive only: n = 15 claims (5 pooled ranks 0-4, 10 held-out ranks 180-189).** No significance claims. The 10 held-out claims have now been looked at
(manual review) and must not serve as a blind test for the web tool again.

## Setup
- Query = claim text, unchanged. Engine `ddgs 9.16.0`, backend `duckduckgo`, region us-en, 10 results (WD1, WD1a). Run date 2026-10-19 (the engine returns today's web).
- Conditions (same claims, same frozen cache): **main** (fact-check domains removed, unknown dates removed), **lenient** (unknown dates kept), **factcheck** (fact-check domains kept). The claim's own article / original URL is removed in all three.
- Scoring: gold URLs matched with `evret.urls.url_variants` (wrapped and unwrapped, normalised). Gold URLs are used in `eval_web.py` only.
- Reproducibility: REPLAY of all 45 (condition x claim) runs made **0 network calls**, returned identical URLs, passages and order, bit-identical scores across two different `PYTHONHASHSEED`s, and the same manifest hash (`2786776e...ebc`) as the live run. Network calls logged in total: 421 (81 search attempts, 137 CDX lookups, 87 robots.txt, 93 live fetches, 23 Wayback fetches).
- Tests: 118 pass, 1 live smoke test skipped by default; every stage was mutation-checked (see log_web.md).

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

## What the numbers say (read with n = 15 in mind)
1. **The engine is the weakest link.** Of 81 search attempts 15 succeeded; 62 raised `DDGSException: No results found` and 4 returned an empty list. With 4 attempts and backoff, 13 of 15 claims got results; claims 485 and 269 failed in every condition, while other claims that failed once succeeded later (and a direct probe of 3 claims at the end failed for all of them). This looks like throttling or blocking, not the query form. The duckduckgo backend therefore cannot be treated as a stable provider; failures are recorded in the cache (and replayed as failures) instead of being cached as "no results".
2. **Temporal leakage is real and large.** Of the 121 returned URLs in the main condition, 26% are dated after the claim (mostly 2025-2026 pages), 19% are fact-check domains and 4% are the claim's own article; only 31% (37 pages) survive. This supports not relying on engine date filters.
3. **Wayback gives dates for free but covers only a quarter of URLs**: 23 of 93 looked-up URLs (25%) had a status-200 snapshot at or before the claim date; those pages are dated by the snapshot (an upper bound); the other 14 of the 37 kept pages are live pages dated by htmldate. All 37 kept pages are HTML (no PDF reached the output; the PDF path is only tested on fixtures).
4. **Gold hits are rare**: only 1 of 15 claims (held-out claim 184) has a gold URL among the engine results; it survived all filters and is in the top-10 passages (top-5: 0 of 15). 0 of 5 pooled claims. 2 of 41 gold URLs were returned by the engine at all. The engine finds a different part of the web than the annotators' sources, and 2020 gold pages are rarely what a 2026 query returns.
5. **Time**: 46.7 s per claim (wall clock, n = 9 cold claims, 2 of them with 0 passages): fetch 53%, Wayback 29%, search 8% (includes retries of failing queries), embedding 8%, extraction 2%. **Embedding is well below the 20% threshold, so no BM25-then-embed cascade is proposed.** The cost is network time, not the model. CPU embedding speed is 16.5 chunks/s (39 passages per claim on average).

## Examples (from outputs/web_smoke/manual_review.md)
- Claim 9 (GDP 33.1, claim date 2020-10-30): ranks 1-2 are two passages of an NBC News article, dated by its Wayback snapshot of 2020-10-30; rank 3 is the BEA page (snapshot 2020-10-30). In the factcheck ablation a CNN fact-check dated 2020-10-29 appears.
- Claim 203 (Nigeria urban population): rank 1 is photius.com (snapshot 2017), rank 2 a World Bank data page whose live htmldate is 2009-10-01 (questionable: a live data page).
- False "dated after" examples: `sciencedaily.com/releases/2022/03/220330103215.htm` (URL says 2022-03-30) got htmldate 2026-10-18, `pmc.ncbi.nlm.nih.gov/articles/PMC9384225/` got 2026-10-11. Both were removed although they are old pages (htmldate picked up a page-chrome date). The filter errs on the safe side (no leak) but loses recall.

## Limitations
- Scraping-based provider: results change over time, are throttled or blocked, and are not the results the annotators saw in 2020. The frozen cache is a snapshot of 2026-10-19, not of 2020.
- Wayback coverage gaps (25% of URLs); a snapshot is an upper bound of the publication date.
- htmldate errors (see above); partial dates were not met in this sample (0), so the earliest-day rule (WD2b) is untested.
- Pages behind 403/429 (16 + 3 of 121 URLs), robots.txt (3) and a timeout (1) are lost; no JavaScript rendering.
- 15 claims, one engine backend, one day: all numbers are descriptive.
- BGE passages computed in fp32 on CPU, stored float16 (the corpus: fp16 GPU); BM25 uses today's pool statistics (N = 6,415,863 chunks).

## Decisions waiting for Malak
See `docs/decisions_web.md` WQ5-WQ9 (engine reliability, date priority, partial dates, query formulation, seen claims).
