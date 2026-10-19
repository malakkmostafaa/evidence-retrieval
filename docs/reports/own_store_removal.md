# Own-store removal evaluation - results (pre-registration: own_store_removal_prereg.md)

Run 2026-10-20 exactly as pre-registered (primary variant fixed before the run; same 180 pooled claims, retrievers, default filters and metrics as the v1 report; claim sets of the normal run: n = 137 for SourceHit/GoldRecall, 91 for CovUnion@512 and AnswerRecall@10, 88 for CovNovel@512). Raw numbers: `outputs/corpus_v1/own_store_removal.json`. Free disk after the run: 25.2 GB.

**Documents removed per claim.** Primary: 1004.1 documents on average (min 574, max 1891) = 62,456 chunks = 0.97% of the pool's chunks. Secondary (documents in no other pool store): 672.9 documents on average (min 200, max 1435) = 27,797 chunks = 0.43% of the pool.

## PRIMARY: every document of the claim's own store removed
Cells: normal value -> value after removal (paired per-claim difference, removal minus normal, with 95% bootstrap CI over claims, 10,000 draws). BM25 and hybrid use recomputed pool statistics (headline choice).

| metric | n | dense: normal -> removed (diff [95% CI]) | BM25 | hybrid |
|---|---|---|---|---|
| SourceHit@10 | 137 | 0.197 -> 0.022 (-0.175 [-0.241, -0.110]) | 0.153 -> 0.015 (-0.139 [-0.204, -0.080]) | 0.204 -> 0.015 (-0.190 [-0.256, -0.124]) |
| SourceHit@50 | 137 | 0.423 -> 0.051 (-0.372 [-0.460, -0.285]) | 0.314 -> 0.015 (-0.299 [-0.380, -0.226]) | 0.402 -> 0.029 (-0.372 [-0.453, -0.285]) |
| GoldRecall@10 | 137 | 0.134 -> 0.018 (-0.116 [-0.165, -0.070]) | 0.098 -> 0.015 (-0.083 [-0.130, -0.041]) | 0.141 -> 0.015 (-0.126 [-0.178, -0.079]) |
| GoldRecall@50 | 137 | 0.287 -> 0.039 (-0.248 [-0.314, -0.185]) | 0.213 -> 0.015 (-0.198 [-0.257, -0.143]) | 0.266 -> 0.025 (-0.240 [-0.305, -0.178]) |
| CovNovel@512 | 88 | 0.403 -> 0.286 (-0.116 [-0.171, -0.065]) | 0.313 -> 0.218 (-0.095 [-0.141, -0.052]) | 0.377 -> 0.261 (-0.116 [-0.173, -0.063]) |
| CovUnion@512 | 91 | 0.468 -> 0.366 (-0.101 [-0.148, -0.057]) | 0.400 -> 0.302 (-0.098 [-0.139, -0.059]) | 0.448 -> 0.348 (-0.100 [-0.143, -0.058]) |
| AnswerRecall@10 | 91 | 0.277 -> 0.077 (-0.201 [-0.280, -0.127]) | 0.229 -> 0.080 (-0.149 [-0.232, -0.071]) | 0.294 -> 0.071 (-0.223 [-0.305, -0.144]) |

**Reading.** Every difference is negative and every CI excludes 0. SourceHit falls from 0.15-0.42 to 0.015-0.05, which is expected by construction: the gold pages sit in the claim's own store and are removed, so a hit is only possible through another stored version of the same URL (2-7 of 137 claims). The answer-coverage metrics fall less: CovNovel@512 loses about 0.10-0.12 (dense 0.403 -> 0.286, BM25 0.313 -> 0.218, hybrid 0.377 -> 0.261) and CovUnion@512 about 0.10, i.e. about 70% of the normal-run coverage is still reached from other claims' stores. AnswerRecall@10 (a single passage holding 80% of an answer) drops most in relative terms (dense 0.277 -> 0.077). Ranking of retrievers after removal: not made (it was not the question; CIs of the retrievers were not compared).

## SECONDARY: only documents exclusive to the claim's own store removed (other stores' copies stay)

| metric | n | dense: normal -> removed (diff [95% CI]) | BM25 | hybrid |
|---|---|---|---|---|
| SourceHit@10 | 137 | 0.197 -> 0.051 (-0.146 [-0.219, -0.080]) | 0.153 -> 0.036 (-0.117 [-0.182, -0.058]) | 0.204 -> 0.051 (-0.153 [-0.219, -0.088]) |
| SourceHit@50 | 137 | 0.423 -> 0.110 (-0.314 [-0.402, -0.226]) | 0.314 -> 0.066 (-0.248 [-0.321, -0.175]) | 0.402 -> 0.088 (-0.314 [-0.394, -0.234]) |
| GoldRecall@10 | 137 | 0.134 -> 0.031 (-0.103 [-0.154, -0.055]) | 0.098 -> 0.021 (-0.076 [-0.124, -0.034]) | 0.141 -> 0.033 (-0.108 [-0.160, -0.061]) |
| GoldRecall@50 | 137 | 0.287 -> 0.068 (-0.220 [-0.282, -0.159]) | 0.213 -> 0.037 (-0.175 [-0.234, -0.122]) | 0.266 -> 0.051 (-0.215 [-0.278, -0.155]) |
| CovNovel@512 | 88 | 0.403 -> 0.322 (-0.081 [-0.133, -0.031]) | 0.313 -> 0.232 (-0.082 [-0.129, -0.039]) | 0.377 -> 0.297 (-0.080 [-0.125, -0.038]) |
| CovUnion@512 | 91 | 0.468 -> 0.393 (-0.075 [-0.121, -0.031]) | 0.400 -> 0.325 (-0.075 [-0.114, -0.040]) | 0.448 -> 0.371 (-0.077 [-0.115, -0.041]) |
| AnswerRecall@10 | 91 | 0.277 -> 0.132 (-0.146 [-0.221, -0.073]) | 0.229 -> 0.117 (-0.112 [-0.192, -0.035]) | 0.294 -> 0.112 (-0.183 [-0.263, -0.102]) |

**Reading.** The drops are smaller than in the primary variant but still all significant: SourceHit@50 0.42 -> 0.11 (dense), CovNovel@512 falls by about 0.08 (dense 0.403 -> 0.322, BM25 0.313 -> 0.232, hybrid 0.377 -> 0.297). Gold pages that also sit in other pool stores remain searchable, so the SourceHit that survives (0.04-0.11) is real retrieval from shared documents.

## BM25 statistics: frozen or recomputed?
Choice made (pre-registered): headline numbers use RECOMPUTED statistics (N, df of the query terms, average length without the removed chunks). Check: the same primary run with frozen pool statistics gives, for every aggregate metric, a value within 0.007 of the recomputed one (largest: BM25 CovNovel@512 0.218 vs 0.212; hybrid AnswerRecall@10 0.071 vs 0.068), far inside the bootstrap half-widths (>= 0.04). So for aggregate results frozen statistics would have been an acceptable approximation (the removed chunks are only 1% of the pool). Individual claims can still change (largest per-claim difference 0.33 in AnswerRecall@10, 0.25 in CovNovel@512), so recomputed statistics remain the headline.

## Checks
99,000 hits checked over all runs: 0 returned documents that were removed, 0 returned a claim's own fact-checking article / original-claim URL. Equivalence of the recomputed statistics with an index built without the chunks is unit-tested (bit-identical; 3 injected bugs caught).

## Limitations
- By construction the gold pages are removed in the primary variant; SourceHit/GoldRecall therefore mostly measure whether the same URL was stored in another claim's store as another version, not retrieval quality. The informative numbers are the coverage metrics.
- Other claims' stores are topically related, so this is a lower bound on how much the corpus design helps, not a claim-independent corpus; the anchored answers (CovNovel claim set) were defined on the full texts.
- 180 pooled claims, single seed/split; CIs are bootstrap over claims; sealed bands untouched; provenance (origins) used in an evaluation-only module and never available to the retrievers.
