# Pre-registration: web vs corpus-with-own-store-removed, and the oracle routing headroom

Written 2026-10-20, before any of the numbers below were computed. Pool claims only (ranks 0-179), the same claim sets as the earlier web/corpus comparison: CovNovel@512 on **88** claims, CovUnion@512 on **91** claims (claims with >= 1 anchored answer; CovNovel needs >= 3 novel answer tokens). Budget 512 BGE tokens, shared `evret.metrics_cov`, the web run = main condition, top-50 passages, claims without a kept web page score 0 (primary) or are dropped (secondary). **No new retrieval, no queries, no network calls**: only per-claim values that already exist are used.

**Detectability.** Differences below about **0.05** are not detectable with n = 88-91. A CI that contains 0 is not evidence of no difference; every number comes with its CI and n.

## Data availability (checked before registering)
| source | per-claim values | status |
|---|---|---|
| web main | `results_replay.jsonl` -> metrics_cov | available |
| corpus, normal (dense / BM25 / hybrid) | `outputs/web_full_serper/corpus_rows.json` (my re-run, reproduces the corpus report to 0.001) | available |
| corpus with own store removed (primary variant) | `outputs/corpus_v1/own_store_removal.json` in the corpus session | **aggregates only** (means per metric and retriever; the cov_novel mean for primary dense is stored as NaN). The per-claim arrays exist only inside `eval_removal.py` while it runs and are not saved. |

So the own-store-removed rows cannot be computed from existing per-claim values. They are registered here, not computed, and stay pending until the corpus session saves the per-claim arrays (a request is in the report). Nothing is re-run to fill the gap.

## Analysis 1 - web vs corpus with own store removed (pending the per-claim file)
Paired per claim, web main minus corpus (dense, BM25, hybrid) in the **primary** own-store-removal variant (every document of the claim's own store removed; BM25/hybrid with recomputed statistics, the corpus session's headline choice). Metrics CovNovel@512, CovUnion@512. Report: both means, mean paired difference, 95% percentile bootstrap CI (10,000 resamples, seed 42, claim = unit, `evret.stats.paired_bootstrap`), wins / ties / losses (web better / equal / worse), n; variants: all claims (primary) and claims with a kept web page (secondary), n stated for both.
Asymmetries stated with the table: (1) the web run applies a claim-date cutoff, the corpus run does not (it can use pages that postdate the claim); (2) candidate pools differ (<= 10 fetched Google results of 2026 vs 6.4M stored chunks minus about 1% removed); (3) removing the own store removes the annotators' evidence by construction, so the table measures coverage from *other* claims' material versus fresh web material, not the retrieval quality of either; the anchored answers (claim set) were defined on the full corpus texts; (4) other claims' stores overlap in topic, so the removed corpus is not claim-independent.

## Analysis 2 - oracle router (upper bound on routing headroom)
For each claim and each corpus retriever separately, `oracle = max(web, corpus)` per metric. This uses the coverage of both sources on the same claim, which no real router can see; it is a **ceiling on the headroom for routing between these two sources, not a result for any router**. Report, for the **normal corpus** (available now) and for the **own-store-removed corpus** (pending):
- mean of the oracle; mean of each single source; **best single source = the one with the higher mean on the same claims** (fixed by the means, not chosen per claim);
- paired gain = mean(oracle) - mean(best single source), with 95% bootstrap CI (gain is >= 0 by construction, so the CI describes its size, not whether it exists);
- share of claims where web wins, corpus wins, tie (strict inequality; ties include both-zero);
- the same on the claims **with a kept web page**, and, among all claims where the corpus beats the web, the split into "web had nothing" (no kept page, web score 0) and "web is worse" (a kept page exists), to separate the two causes.
Reading rule: a gain below about 0.05 is within what cannot be detected; the oracle gain is an optimistic upper bound because taking a per-claim maximum of two noisy scores inflates the mean (winner's-curse effect), so it overstates what any router could reach.
