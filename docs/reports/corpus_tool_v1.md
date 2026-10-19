# Corpus tool v1 - report (full pool, bands 0-5)

Date 2026-10-19. Searched corpus: pool bands 0-5, 6,415,863 chunks from 138,982 pool documents; the 4 sealed bands were never chunked, embedded or indexed. Evaluated: all 180 pooled claims (claim text = query; gold used only for scoring). Raw numbers: `outputs/corpus_v1/eval_bands_0_1_2_3_4_5.json`; examples for you to judge: `outputs/corpus_v1/examples_bands_0_1_2_3_4_5.md`.
**Free disk now: 18.4 GB (was 56.6 GB at the start). Peak RAM of the evaluation: 7.8 GB.**

## What was built and verified
| stage | result |
|---|---|
| S1 ingest | 301,754 records -> 215,226 documents; unique non-empty keys, characters (10,600,102,626) and maximum length (38,503,280) equal the audit; 200/200 sampled documents byte-identical; regenerated real shards have identical sha256 |
| S2 chunk | 6,415,863 chunks; sampled checks on every band: 0 span / hash / coverage errors, 0 token mismatches, max 500 tokens, max 4,971 chars; ~10% of chunks split by the cap (mostly PDF) |
| S3 embed | all 6 bands; whole-pool check: self-retrieval 300/300 (8 via exact duplicates), median stored-vs-fresh cosine 1.000001 (min 0.99984), 0 truncations; ~300 chunks/s (GPU throttled to ~650 MHz) |
| S4 search | dense (exact), BM25 (pool-wide statistics, proven by an equivalence test), hybrid (RRF k=60, top-100 each), filters, `search_batch` |
| S5 | this report; metrics from the shared module `evret.metrics_cov` (D14) |

## Results (default filters: fact-check pages excluded; k counts chunks; 95% bootstrap CIs over claims, paired differences per claim)
**SourceHit / GoldRecall** - reachable claims = 137 of 180 (>= 1 gold URL has an indexed, non-fact-check document):

| metric | dense | BM25 | hybrid |
|---|---|---|---|
| SourceHit@10 | 0.197 [0.131, 0.263] | 0.153 [0.095, 0.212] | 0.204 [0.139, 0.277] |
| SourceHit@50 | 0.423 [0.343, 0.504] | 0.314 [0.241, 0.394] | 0.402 [0.321, 0.482] |
| GoldRecall@10 | 0.134 [0.086, 0.186] | 0.098 [0.058, 0.143] | 0.141 [0.091, 0.195] |
| GoldRecall@50 | 0.287 [0.224, 0.351] | 0.213 [0.155, 0.273] | 0.266 [0.204, 0.329] |

**Answer coverage** (legacy metrics, fixed budget of 512 BGE tokens; claims with >= 1 anchored answer: 91 of 180, 88 with a defined CovNovel):

| metric | dense | BM25 | hybrid |
|---|---|---|---|
| CovNovel@512 (primary) | 0.403 [0.344, 0.464] | 0.313 [0.266, 0.364] | 0.377 [0.320, 0.436] |
| CovUnion@512 | 0.468 [0.410, 0.527] | 0.400 [0.351, 0.451] | 0.448 [0.393, 0.505] |
| AnswerRecall@10 | 0.277 [0.193, 0.363] | 0.229 [0.149, 0.312] | 0.294 [0.205, 0.384] |

**What the paired differences allow us to say** (differences whose 95% CI excludes 0):
- Dense > BM25: SourceHit@50 +0.110 [+0.051, +0.168]; GoldRecall@50 +0.075 [+0.033, +0.118]; CovNovel@512 +0.089 [+0.036, +0.143]; CovUnion@512 +0.067 [+0.024, +0.111]. Dense is better than BM25 at deeper cut-offs and in answer coverage.
- Hybrid > BM25: SourceHit@50 +0.088 [+0.044, +0.139]; CovNovel@512 +0.063 [+0.020, +0.108]; CovUnion@512 +0.048 [+0.012, +0.085]; AnswerRecall@10 +0.066 [+0.015, +0.121].
- **Dense vs hybrid: no difference at any k = 10 / 50 or in CovNovel@512 / CovUnion@512 (all CIs include 0), so they are not ranked.** Only the variable-length "CovNovel@10" favours dense over hybrid (+0.026 [+0.005, +0.048]); that metric favours large chunks and is not the primary one.
- At k = 10, SourceHit does not separate any pair.
- Including fact-check pages (F3 ablation) changes SourceHit@50 by -0.007 (dense), 0 (BM25), -0.007 (hybrid); no effect worth reporting.

## Why 188 of 481 gold URLs are unreachable
| state | gold URLs |
|---|---|
| reachable | 293 |
| empty text (the scrape returned nothing) | 149 |
| tiny text (< 200 characters) | 15 |
| fact-check flag (excluded by F3 default) | 24 |
| not in the document table | 0 |
So 31% of gold URLs, and 43 of 180 claims, cannot be found by any text retriever because the knowledge store holds no usable text for them (mostly empty scrapes).

## Leakage checks
54,000 hits checked (180 claims x 3 retrievers x 50 x 2 filter variants): **0 documents outside the pool, 0 hits on a claim's own fact-checking article / original-claim URL** (Wayback-unwrapped, D12). Sealed bands do not exist in any artefact; the 43 sealed label rows of the metric regression were never re-anchored (D15).

## Costs
- Time: ingest 6 min, chunking ~35 min (4 workers), embedding ~6 h (300 chunks/s), BM25 ~10 min.
- Query latency (all 6 bands): single query median dense 1.18 s, BM25 1.03 s, hybrid 1.79 s (dense streams 4.6 GB of vectors); batched 180 claims: dense 30 ms, BM25 612 ms, hybrid 605 ms per query.
- RAM: 7.8 GB peak for evaluation (6.4M chunk metadata + memmapped postings/vectors).
- Disk (data/corpus_v1): SQLite chunk text 9.3 GB (derived, rebuildable), BM25 4.5 GB, vectors 4.6 GB, chunk Parquet 2.4 GB, documents 2.0 GB.

## Limitations
- The pool is a fresh stratified ranking, NOT the earlier experiments' pool (old split file not found); the chunker differs from the legacy pack_200_250 (D9a), so chunk-level numbers are not comparable with experiments 04b/05.
- Only 137 claims have a reachable gold page and 91 have an anchored answer; CIs are wide and several differences are small.
- The fact-check flag has about 72% precision (D8); gold annotation anchoring over-represents extractive evidence (D14).
- The metrics are validated only as a regression against the old labels (D14, D15), not on this corpus; the optional 50-passage relabelling is proposed, not run.
- BM25 is my own implementation (validated on a toy corpus, D11/D13); dense search is exact but slow for single queries (1.2 s).
- Sealed bands 6-9 (120 claims) remain untouched for the final test.
