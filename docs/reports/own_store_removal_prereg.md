# Pre-registration: evaluation with each claim's own store removed from the searchable pool

Written 2026-10-20 BEFORE any removal run. Free disk 21.9 GB at the time of writing.

## Question
How much of the v1 result depends on the corpus having been built around the claim? We simulate a corpus that was not, by removing from the searchable pool the documents that came from the claim's own knowledge store, and re-running the v1 evaluation.

## Provenance check (done before registering)
The document table (`doc_index_pool.parquet`) records only `min_rank` (the lowest-ranked claim whose store holds the document). Full membership is in `origins.parquet`, which has one row per record: all 301,754 records of all 300 stores, with `doc_id` and `claim_id`. So "every store a document appears in" is available without re-running the ingest. Facts: 21.0% of the 138,982 pool documents appear in more than one of the 300 stores (12.9% in more than one of the 180 pool stores); a pooled claim's store holds on average 1,004 pool documents (574-1,891; 0.72% of the pool), of which 673 appear in no other pool store.
This provenance is evaluation-only: it is read in an evaluation module (`eval_removal`, allowed by the origins guard test) and reaches the search layer only as a list of document ids in the per-query filter; the retrievers never see claim ids or origins.

## Variants (fixed now)
- **PRIMARY: "own-store removed".** For claim c, remove every document that appears in c's own store, including documents that also appear in other stores.
- **SECONDARY: "own-exclusive removed".** Remove only documents that appear in c's store and in no other POOL store. (Sealed stores' membership is deliberately NOT used: the sealed rule has no exceptions, so "other store" means the other 179 pool stores.)
- Both variants remove documents by `doc_id`, in addition to the normal exclusions (own fact-checking article / original-claim URLs, fact-check and tiny flags). The normal run (no removal) is re-run in the same script as the paired baseline.

## Fixed analysis (same as the v1 report)
- Same 180 pooled claims, same three retrievers (dense, BM25, hybrid), same filters, same k, same metrics, same claim sets: SourceHit@10/@50 and GoldRecall@10/@50 on the 137 claims with reachable gold; CovNovel@512 (n = 88), CovUnion@512 and AnswerRecall@10 (n = 91). The claim sets are the ones defined by the normal run and are NOT redefined after removal (so claims whose gold page was removed count as misses). Anchored answers are computed on the full pool texts (evaluation path), not on the reduced corpus.
- Report, per retriever and metric: value in the normal run, value after removal, paired per-claim difference (removal minus normal) with a 95% bootstrap CI (claims resampled, 10,000 draws), and n. One line: mean number of documents (and chunks) removed per claim.
- Hypotheses are not directional; the differences are reported as measured. Paired CIs excluding 0 are the only basis for saying a metric changed; method rankings follow the v1 rule (no ranking when CIs overlap).
- Unit-test requirement: an index with documents removed through the filter must score exactly like an index built without those documents (see BM25 below).

## BM25 statistics (decision fixed now)
Removing documents changes N, the document frequencies and the average length of the pool the claim is searched in. Because a claim's store is only 0.72% of the pool, the frozen statistics are probably an acceptable approximation, but recomputing is cheap (only the query terms' postings that fall in the removed chunk ranges are counted). **Headline numbers use RECOMPUTED statistics** (N, df of the query terms, average length all computed without the removed chunks, exactly what an index built without them would give; the equivalence is unit-tested). A **frozen-statistics run** is reported as a check: if the headline and frozen values differ by less than the bootstrap half-width everywhere, frozen statistics are documented as an acceptable approximation, otherwise the recomputed numbers stand. Dense retrieval has no corpus statistics.

## Limitations (stated in advance)
- Removing the whole own store also removes the gold pages that lie in it (gold URLs are in the claim's own store by construction); SourceHit can then only be satisfied by a different stored version of the same URL from another store. Near-zero source hits are therefore expected for the primary variant and say little about retrieval quality. CovNovel remains informative because other pages can contain the answer words, but its anchoring is defined on pages that are no longer searchable.
- Other claims' stores overlap in topic (the AVeriTeC stores of related claims), so this is not a truly claim-independent corpus.
- Only pool claims (180) are used; sealed bands stay untouched.
