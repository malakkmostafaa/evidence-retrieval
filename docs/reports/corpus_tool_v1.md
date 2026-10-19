# Corpus tool v1 - report (bands 0-1 evaluated; full-pool run in progress)

Status 2026-10-19. Searched corpus: pool bands 0-1 (2,758,511 chunks); pool total = bands 0-5 = 6,415,863 chunks (embedding of bands 2-5 running, ~6 h). Re-run `python -m evret.eval_pool ... --bands 0 1 2 3 4 5` when done. **Free disk now: 32.0 GB.**

## What was built and verified
| stage | result |
|---|---|
| S1 ingest | 301,754 records -> 215,226 documents; unique non-empty keys, unique chars (10,600,102,626) and max length (38,503,280) equal the audit; 200/200 sampled documents byte-identical; real shards regenerate with identical sha256 |
| S2 chunk | pool 6,415,863 chunks (band 0: 1,580,741; 72% PDF; 10% split by the cap); sampled checks bands 0-5: 0 span / hash / coverage errors, 0 token mismatches, max 500 tokens |
| S3 embed | band 0: self-retrieval 300/300, median stored-vs-fresh cosine 0.999999, 0 truncations; ~300 chunks/s |
| S4 search | dense / BM25 / hybrid, filters, `search_batch`; pool-wide BM25 statistics proven by an equivalence test |

## SourceHit on bands 0-1 (60 claims; gold only used for scoring)
Reachable claims = 48 of 60 (>= 1 gold URL has an indexed, non-fact-check document). Default filters (fact-check pages excluded). Claim text is the query; k counts chunks. 95% bootstrap CIs resample claims (10,000 draws); differences are paired per claim.

| metric (reachable claims, n = 48) | dense | BM25 | hybrid |
|---|---|---|---|
| SourceHit@10 | 0.250 [0.125, 0.375] | 0.167 [0.063, 0.271] | 0.229 [0.125, 0.354] |
| SourceHit@50 | 0.438 [0.292, 0.583] | 0.333 [0.208, 0.458] | 0.438 [0.292, 0.583] |
| GoldRecall@10 | 0.153 [0.074, 0.241] | 0.118 [0.042, 0.207] | 0.160 [0.073, 0.260] |
| GoldRecall@50 | 0.293 [0.188, 0.408] | 0.241 [0.137, 0.356] | 0.291 [0.182, 0.408] |

Paired differences (95% CI): at k = 10 no pair differs (dense - BM25 SourceHit@10 = +0.083 [-0.021, +0.208]). At k = 50 only hybrid > BM25 has a CI excluding 0 (SourceHit@50 +0.104 [+0.021, +0.208]; GoldRecall@50 +0.050 [+0.016, +0.093]); dense - BM25 SourceHit@50 = +0.104 [0.000, +0.229] touches zero. **Conclusion: with 48 claims the three methods cannot be ranked, except that BM25 alone is weaker than hybrid at k = 50.** Including fact-check pages (F3 ablation) changes nothing for dense and BM25 and lowers hybrid@10 (0.229 -> 0.188), but that is within noise. Full tables: `outputs/corpus_v1/eval_bands_0_1.json`. Top-5 examples for 5 claims, for you to judge: `outputs/corpus_v1/examples_bands_0_1.md`.

## Why 58 of 173 gold URLs are unreachable (bands 0-1)
| state | gold URLs |
|---|---|
| reachable | 115 |
| empty text (scrape returned nothing) | 52 |
| tiny text (< 200 chars) | 2 |
| fact-check flag (excluded by F3) | 4 |
| not in the document table | 0 |

(On the 30 band-0 claims alone: 27 of 91.) Almost all losses are empty scrapes, i.e. a property of the knowledge store (the audit found 262 of 638 gold records empty), not of retrieval.

## Leakage checks
18,000 hits checked (60 claims x 3 retrievers x 50 x 2 filter variants): 0 documents outside the pool, 0 hits on a claim's own fact-checking article / original-claim URL (after Wayback unwrapping, D12). Sealed bands do not exist in any artefact.

## Costs (2 bands searched)
Single query median: dense 683 ms, BM25 435 ms, hybrid 998 ms; batched 60 claims: 36 / 293 / 326 ms per query. Peak RAM 4.8 GB. Dense search streams all vectors, so it grows linearly with bands (about 5 GB of float16 vectors for the whole pool). Disk (pool): documents 2.0 GB, chunk Parquet ~4 GB, SQLite text 9.9 GB, BM25 4.5 GB, vectors ~4.9 GB when finished.

## Not done / limitations
- **CovNovel@512 not added**: its definition is not in this repository or on the Desktop; please give me the definition (or the old code) and I will add it next to SourceHit.
- Numbers are for 2 of 6 bands and 60 claims; do not quote them as the final result.
- The old split file was not found; the pool differs from the earlier experiments.
- Fact-check flag precision about 72% (D8); chunk split rate 10% (D9).
