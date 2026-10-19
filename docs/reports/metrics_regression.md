# Regression of the ported answer-coverage metrics against the 100 manual labels

Date 2026-10-19. Code: `evret.metrics_cov` (ported), `evret.eval_labels`, `scripts/regress_labels.py`. Raw numbers: `outputs/corpus_v1/label_regression.json`. This is a **regression test plus partial validation of the code, NOT a validation on the new corpus**. Free disk 30.3 GB, free RAM 6.1 GB at the time of writing; the embedding job was not touched.

## Sealed rule
43 of the 100 labelled passages belong to claims in sealed bands (rank >= 180). Their gold pages were NOT read, so those rows are **"not re-anchored (sealed)"**; they are used only in version 3 below (old labels, unanchored answers, no new-corpus statistic) and in no new-corpus number.

## Three versions of the numbers (AUC = Mann-Whitney, ties 1/2; Spearman with the 3-level label)
Novel-word scores are undefined (NaN) when no answer has >= 3 novel tokens; those rows are dropped (this is what reproduces the reported values), n is shown.

| version | n (all / novel) | AUC 2 vs 0/1 (all words / novel) | AUC >=1 vs 0 | Spearman |
|---|---|---|---|---|
| **(1) saved scores, all 100 labels (original validation, old pipeline)** | 100 / 95 | **0.802 / 0.752** | 0.737 / 0.708 | 0.516 / 0.440 |
| (2) ported code, anchored answers, 57 pool rows (regression) | 56 / 55 | 0.845 / 0.816 | 0.741 / 0.755 | 0.581 / 0.557 |
| (2b) saved scores on the same 57 rows (comparison) | 57 / 56 | 0.850 / 0.823 | 0.747 / 0.761 | 0.593 / 0.568 |
| (3) ported code, unanchored ("scorable") answers, all 100 rows (sensitivity) | 100 / 100 | 0.783 / 0.742 | 0.723 / 0.709 | 0.483 / 0.424 |

Version (1) reproduces the reported 0.80 / 0.75, 0.74 / 0.71 and 0.52 / 0.44 exactly. Scoring the NaN novel rows as 0 instead of dropping them would give 0.72 / 0.68 / 0.38, so that is not what was reported.

## Row-level agreement of the ported code with the saved per-passage values
- Pool rows with anchoring: **55 of 57 exact** (soft_best and novel_best equal to 1e-9).
- All 100 rows without anchoring: 77 of 100 exact (pool 48/57, sealed 29/43). The 23 other rows are explained by the missing anchoring step (the saved values only count answers found on the cited page); for sealed rows this cannot be checked, by decision.

## The 2 pool rows that still differ (not caused by the chunker)
Anchoring is computed on raw page text and is independent of chunking by design (selection.py docstring), and the labelled passages are fixed text, so the new chunker plays no role.
| row | claim | ported (soft, novel) | saved | cause |
|---|---|---|---|---|
| 68 | 181 | NaN, NaN | 0.625, 0.5 | **Verified.** The gold URL (economictimes.indiatimes.com/...63009549.cms) is stored only as an EMPTY record (0 characters, Wayback wrapper) in the new store, so no answer anchors. The text exists under m.economictimes.com (same path). Anchoring on that copy reproduces 0.625 / 0.5 exactly. So the old run matched the gold URL to its mobile copy (its URL normalisation or page-version choice differs from mine; its `norm_url` is not in the provided files). |
| 35 | 164 | 0.3, 0.2273 | 0.3, 0.2222 | **Not fully explained.** Mine takes the maximum novel recall from the answer citing polygraph.info (5 of 22 novel tokens = 0.2273); the saved value (2 of 9 = 0.2222) is exactly the opcw.org answer, i.e. the old run did not treat the polygraph answer as anchored. The page is short (4,585 characters), so the old 100k-character truncation is NOT the reason (I checked: identical anchor recall on the first 100k characters). Likely a different stored page version or URL matching in the old run; to confirm I would need the old docs table. |

## Leakage check on the labelled passages
Method: for each passage of a pool claim, BM25 over the new corpus with its first 40 words, then an exact whitespace-normalised substring match of three 100-character probes against the top-30 chunks; the source URLs found are compared with the claim's own fact_checking_article, original_claim_url and cached_original_claim_url (Wayback-unwrapped).
- 57 pool-claim passages: **55 matched, 2 unmatched (rows 44, 55)**; **0 of the 55 come from a claim's own article or original-claim URL**. Therefore version (2) is unchanged when such rows are removed (nothing to remove); on the 55 matched rows saved/ported AUC (2 vs 0/1) are 0.841 / 0.835 (all words) and 0.813 / 0.806 (novel).
- 43 sealed-claim passages: cannot be matched (their documents do not exist in the new corpus). To check them I would need the old docs table or old chunk table (chunk_idx -> doc_ord -> URL) of experiments 04b/05; the KEY file only has (arm, claim_id, chunk_idx, rank).

## Not run: optional 50-passage relabelling (proposal)
Sample 50 passages from the new tool (25 dense top-5, 25 hybrid top-5; pool claims; seeded; passages cut at 1,500 characters as before); generate a blinded sheet (row, claim, passage, empty relevance_0_1_2) and a separate key (row, retriever, claim_id, chunk_id, rank); compare AUC (2 vs 0/1) with 0.75. Needs about one hour of rater time; same single-rater limitation.
