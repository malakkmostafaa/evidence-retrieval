# Pre-registration: web "lenient" condition (written before it is computed)

Written 2026-10-20, before any lenient number exists. Pool claims only (ranks 0-179).

## What lenient changes relative to main
**Filters only. Queries and search parameters are unchanged.**

| part of the pipeline | main | lenient |
|---|---|---|
| query text, fallback rule, provider, `num`, `gl`, `hl`, `autocorrect` | claim text (+ quote fallback) | identical (same cache keys, so the same cached Serper answers) |
| URL filters: own article, fact-check domains | on | on (identical) |
| Wayback lookup, snapshot-or-live fetch, robots.txt, extraction, htmldate / URL date | as run | identical (all cached) |
| date filter, page dated after the claim | removed | removed (identical) |
| date filter, page whose date is **unknown** (no snapshot, no htmldate, no URL date) | **removed** (`date_unknown`) | **kept**, flagged `undated` |
| tiny / no-text pages | removed | removed (identical) |
| chunking, embedding, scoring, RRF, top-50 | as run | identical code; only the added pages bring extra passages |

Code: `ClaimContext.lenient_dates` is read in exactly one place, `filters.date_reason` (checked by grep). So lenient = main + the pages that main dropped as `date_unknown` (38 URLs over the 180 claims in main) and which have enough text.

Consequence for how it is computed: **no new queries and no network calls.** Every page involved was already fetched in main (the date is known only after the fetch), so lenient is computed by REPLAY from the frozen cache (`--replay`: a cache miss raises an error; the query counter does not move). Local CPU work only (chunk + embed the added pages, 3 threads). If the replay raised a cache miss, that would mean lenient needs something main did not fetch; I would stop and ask.

Self-check before interpreting anything: for every claim, the lenient URL records must equal the main records except for URLs whose main outcome was `date_unknown`; claims without such a URL must have identical top-50 passages and identical scores.

## Fixed comparison (paired, per claim, against main)
- Unit: the claim. Pairing: same claim in main and lenient. Bootstrap: percentile, 10,000 resamples, seed 42, 95% CI (`evret.stats.paired_bootstrap`); also wins / ties / losses.
- Metrics (same as step 2, shared `evret.metrics_cov`): **CovNovel@512** (primary) and **CovUnion@512**, budget 512 BGE tokens, same anchored answers and claim set as the corpus report (91 claims with an anchored answer; CovNovel defined for 88). Primary variant: all claims (a claim without a kept page scores 0). Secondary: claims with at least one kept page in the condition being compared (n stated).
- Descriptive extras (no tests): SourceHit@10/50 and gold-URL entries found (gold funnel) over all 180 claims; number of claims whose top-50 changed.
- Funnel table: the URLs added back, step by step: `date_unknown` in main -> enough text -> chunked -> at least one passage in the lenient top-50 -> gold page; plus how many of the lenient top-50 passages come from added pages, and the date source of the added pages (all `none` by definition).
- Detectability: **differences below about 0.05 are not detectable at n = 180** (and not at n = 88-91 for the coverage claims); the added pages affect only a minority of claims, so most paired differences are exactly 0. I report the observed CI widths next to every difference and do not interpret a CI that contains 0 as "no effect".
- Interpretation rule: lenient trades temporal-leakage risk for recall. A gain would be reported as "more coverage from pages of unknown date, with unknown leakage risk" and never as an improvement of the method. Unknown-date pages cannot be checked against the claim date; the manual-review list covers the added pages that reach the top-5.

## Fact-check condition (later, not run)
Left for later, and framed as a **leakage diagnostic**, not as a candidate setting: it keeps fact-check domains, so a higher score would measure how much the answer is available from fact-checkers (label / answer leakage), not retrieval quality. Own article stays excluded. It will be run only after approval, by replay where possible (pages of fact-check domains were never fetched in main, so it needs new fetches but no new queries).
