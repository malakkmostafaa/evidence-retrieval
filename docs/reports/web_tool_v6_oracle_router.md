# Web tool v6 - oracle routing headroom (normal corpus) and the pending own-store-removed comparison

Date: 2026-10-20. Pre-registered in `docs/plans/web_oracle_router_plan.md` (committed before any number here). Pool claims, same claim sets as before: CovNovel@512 n = 88, CovUnion@512 n = 91 (claims with an anchored answer); web = main condition, top-50 passages; corpus = the corpus tool's normal run (my local re-run, which reproduces the corpus report to 0.001). **No new retrieval, no queries, no network calls.** Raw: `outputs/web_full_serper/oracle_router_normal.{json,md}`.

**Detectability.** Differences below about 0.05 are not detectable with n = 88-91; a CI containing 0 does not show "no difference".

## What could not be done: web vs corpus-with-own-store-removed
The corpus session's `own_store_removal.json` stores **only aggregates** (one mean per metric and retriever; the primary dense CovNovel mean is even stored as NaN). The per-claim arrays exist only inside `eval_removal.py` while it runs and are not saved. A paired per-claim comparison and the oracle router for the removed corpus therefore cannot be computed from existing per-claim values, and I did not re-run retrieval to fill the gap. **Request to the corpus session**: save, for the normal run and for the primary own-store-removal variant (BM25/hybrid with recomputed statistics), the per-claim `cov_novel@B512` and `cov_union@B512` arrays with their `claim_ids` for dense, BM25 and hybrid (the `store` dict in `eval_removal.py`). With that file, `python -m evret.web.oracle_router --corpus-rows <file> --label own_store_removed` and the paired table of the earlier comparison run unchanged. Asymmetries to state with those tables are in the plan (date cutoff only on the web side; candidate pools; the removal deletes the annotators' evidence by construction; other claims' stores overlap in topic).

## Oracle router, normal corpus (upper bound, not a router)
`oracle = max(web, corpus)` per claim, per corpus retriever. It sees both scores, which no router can; it bounds the headroom for routing between these two sources. "Best single" = the source with the higher mean on the same claims. Gain = mean(oracle) - mean(best single), bootstrap 95% CI (10,000 resamples, claim = unit; the gain is >= 0 by construction, so the CI shows its size only). W / C / T = claims where web / corpus / neither is strictly better.

**All claims (web without a kept page scores 0)**

| metric | corpus | n | web | corpus | oracle | best single | gain [95% CI] | W / C / T | corpus wins: web had no page / web worse |
|---|---|---|---|---|---|---|---|---|---|
| CovNovel@512 | dense | 88 | 0.273 | 0.403 | 0.443 | corpus | +0.041 [+0.021, +0.064] | 19 / 56 / 13 | 16 / 40 |
| CovNovel@512 | BM25 | 88 | 0.273 | 0.313 | 0.395 | corpus | +0.082 [+0.052, +0.116] | 33 / 45 / 10 | 15 / 30 |
| CovNovel@512 | hybrid | 88 | 0.273 | 0.376 | 0.428 | corpus | +0.052 [+0.030, +0.077] | 26 / 53 / 9 | 16 / 37 |
| CovUnion@512 | dense | 91 | 0.334 | 0.467 | 0.504 | corpus | +0.037 [+0.019, +0.058] | 20 / 59 / 12 | 16 / 43 |
| CovUnion@512 | BM25 | 91 | 0.334 | 0.400 | 0.471 | corpus | +0.070 [+0.044, +0.099] | 33 / 49 / 9 | 16 / 33 |
| CovUnion@512 | hybrid | 91 | 0.334 | 0.448 | 0.495 | corpus | +0.047 [+0.028, +0.069] | 25 / 57 / 9 | 16 / 41 |

**Only claims with a kept web page** (separates "web has nothing" from "web is worse")

| metric | corpus | n | web | corpus | oracle | best single | gain [95% CI] | W / C / T |
|---|---|---|---|---|---|---|---|---|
| CovNovel@512 | dense | 72 | 0.334 | 0.410 | 0.460 | corpus | +0.050 [+0.026, +0.078] | 19 / 40 / 13 |
| CovNovel@512 | BM25 | 72 | 0.334 | 0.323 | 0.423 | web | +0.089 [+0.053, +0.128] | 33 / 30 / 9 |
| CovNovel@512 | hybrid | 72 | 0.334 | 0.371 | 0.434 | corpus | +0.063 [+0.038, +0.092] | 26 / 37 / 9 |
| CovUnion@512 | dense | 75 | 0.406 | 0.476 | 0.520 | corpus | +0.045 [+0.024, +0.070] | 20 / 43 / 12 |
| CovUnion@512 | BM25 | 75 | 0.406 | 0.410 | 0.495 | corpus | +0.085 [+0.055, +0.120] | 33 / 33 / 9 |
| CovUnion@512 | hybrid | 75 | 0.406 | 0.448 | 0.505 | corpus | +0.057 [+0.034, +0.083] | 25 / 41 / 9 |

## Reading (upper bound only)
- The oracle adds **+0.04 to +0.08** on top of the best single source on all claims, and +0.045 to +0.09 on claims with a kept web page. Gains of about 0.05 are at the limit of what is detectable here, and a per-claim maximum of two noisy scores is inflated (winner's curse), so these numbers overstate what any real router could reach; the largest gains are against BM25, the weakest corpus retriever.
- Who wins: the corpus is better on 45-59 of 88-91 claims, the web on 19-33, the rest tie (many ties are claims where both sources score the same, mostly low values).
- "Web has nothing" versus "web is worse": of the claims where the corpus beats the web, 15-16 (about 27-30%) are claims where the web run kept no page at all, and 30-43 (about 70-73%) are claims where the web did retrieve pages but covered less. Restricting to claims with a kept web page (n = 72 / 75) leaves the gains unchanged or slightly larger (+0.05 to +0.09), so the routing headroom does not come from the empty web results alone.
- Against the normal corpus the web is the weaker source on average (see v4), so the oracle's value is mostly in the minority of claims where the web wins (19-33).

## Limitations
n = 88-91, one engine day; the normal corpus contains the annotators' own stores (it is the favourable case for the corpus, so the headroom here is for routing between a store built around the claim and the open web, not for a claim-independent corpus; that case is the pending own-store-removed comparison); the web side applies a claim-date cutoff, the corpus side does not; candidate pools differ (<= 10 web pages vs 6.4M chunks); the oracle is not a router and says nothing about whether a router can predict which source wins.
