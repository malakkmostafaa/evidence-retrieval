# DECISIONS

Format: Decision / Alternatives considered / Evidence / Reason / Limitations, revisit if.

## D00a: Local development on Windows with a Python 3.11 venv   [engineering]   2026-10-18
- Decision: develop and run locally (VS Code, git repo); native Windows Python 3.11.9 in a venv; PyTorch 2.14.1 + CUDA 13.2; RTX 3060 Laptop GPU (6.4 GB), 16.5 GB RAM.
- Alternatives considered: Colab/Kaggle notebooks with code on Drive; WSL2; Python 3.14 (already installed).
- Evidence: docs/env_report.txt (15 checks, 0 FAIL): GPU vs CPU matmul rel. diff 2.75e-07; BGE-small embeddings GPU vs CPU min cosine 1.000000.
- Reason: data no longer fits Drive comfortably after removing truncation; git commits give stronger provenance than notebook hashes; local GPU removes the Colab/Drive split. 3.11 instead of 3.14 for ML-library compatibility.
- Limitations / revisit if: float16 results may differ slightly on other GPUs; WSL2 needed only if a Docker-based vector DB is chosen later.

## D01: Read the knowledge store ZIPs as streams, never extract   [engineering]   2026-10-18
- Decision: stream each ZIP member line by line (Python zipfile).
- Alternatives considered: extract everything first; extract one ZIP at a time and delete.
- Evidence: no extra disk; originals remain the single source of truth (checksummed in audit_summary.json).
- Reason: disk budget (~57 GB free) and reproducibility.
- Limitations / revisit if: manual inspection needs extracted files (sample records are printed instead).

## D02: Unreadable lines are counted, categorised and sampled, not skipped   [engineering]   2026-10-18
- Decision: split lines only at "\n" (binary readline, never str.splitlines()); strict UTF-8 decoding; every failure counted by kind with up to 20 samples; line accounting must close (lines = records + blank + bad).
- Alternatives considered: skip silently (previous reader); stop at first error.
- Evidence: previous build lost records because splitlines() split at U+2028 inside scraped text (corpus_v2 notes); unit test reproduces the issue.
- Reason: "no data loss" must be demonstrable, not assumed.
- Limitations / revisit if: none known.

## D3: Pool design - sealed rank bands   [methodology]   2026-10-19
- Decision: each of the 300 claims gets a rank 0-299 from a seeded (42) permutation interleaved by veracity label (inside each label group the claims are shuffled, the i-th of n gets key (i+u)/n, u~U[0,1); sort by key). Bands = 10 blocks of 30 ranks. Pool = bands 0-5 (`--pool-bands`), bands 6-9 sealed: no text is written, chunked, embedded or indexed for them, and no statistic of this task uses them except the ingest totals needed to reconcile with the audit (counts and characters over all 300 stores; no sealed text is read after pass 1).
- Alternatives considered: random split without stratification; stratified split without ranks; writing sealed text but not indexing it.
- Evidence: tests/test_pool.py (every band holds each label within +-2 of its expected count); fixture tests in tests/test_ingest.py.
- Reason: a rank order lets the pool grow later (more bands) without re-drawing, and the seal is enforced by not producing sealed artefacts at all.
- Limitations: the old split file `corpus_split_seed42_h40.json` was not available, so this pool is NOT the earlier experiments' pool (the code supports `--old-split`; the file format is assumed). Only 21-23 claims have the two rarest labels, so a band holds 2-3 of each.

## D4: Gold-derived query types   [methodology, UNDECIDED]   2026-10-19
- Decision: not taken. The `type` of every record is kept in origins.parquet so that min_rank over non-gold types can be recomputed later. Only the ingest and eval modules may read origins (guard test).

## D5: Publication dates   [engineering]   2026-10-19
- Decision: pub_date = date found in the URL path (audit's url_date; "YYYY-MM" or "YYYY-MM-DD"), date_source = "url" or "none". Pages without a date are kept. The `not_after` filter keeps undated pages (marked date_source="none") and compares partial dates by their earliest possible day.
- Limitations: 14.6% of records have a URL date; undated pages can be later than the claim, i.e. a temporal-leak risk that the filter cannot remove.

## D6: Dedup unit = exact (normalised URL, content hash)   [engineering]   2026-10-19
- Decision: one document per exact key; every record is kept as a row in `origins` (doc_id, claim, type, query, raw URL, line). Documents are numbered in (min_rank, first appearance) order; min_rank = lowest rank of any claim whose store contains the key.
- Evidence: 301,754 records -> 215,226 documents, 166,933 non-empty, 10,600,102,626 characters, maximum 38,503,280: identical to the Block 1b audit (outputs/corpus_v1/ingest_verify.json).
- Limitations: identical texts under different URLs stay separate (about 1.1% of characters).

## D7: Text is byte-exact   [engineering]   2026-10-19
- Decision: no truncation or rewriting; url2text items joined with "\n"; stored as UTF-8 bytes with `surrogatepass` (lone surrogates survive) in a binary column; U+2028 and NUL kept. Offsets are Python code points.
- Evidence: 200 sampled pool documents (7 with U+2028, 12 with NUL, 82 with non-BMP characters; none with a lone surrogate happened to be sampled, covered by the fixture test) are identical to a fresh read of the ZIP record.
- Limitations: the tokenizer cannot encode lone surrogates; for tokenising they are replaced by U+FFFD (same length, offsets unchanged); stored text is untouched.

## D8: Flags, not deletion; fact-check policy F3   [methodology]   2026-10-19
- Decision: is_empty, is_tiny (<200 chars), is_pdf, is_factcheck (audit heuristic) are flags. Empty and tiny documents are not chunked. Flagged fact-check pages are indexed but excluded by default at query time (ablation includes them); each claim's own fact_checking_article and original_claim_url are always excluded via `exclude_norm_urls` built by the evaluation layer.
- Evidence (precision of the flag, 50 random flagged pool URLs, outputs/corpus_v1/factcheck_sample50.txt): my reading is about 36 of 50 (72%) real fact-check pages; false positives are articles ABOUT fact-checking or hoaxes (brookings, newslaundry, nymag Sandy Hook, vulture, rollingstone, indiana hoaxy), a search page and a Twitter profile. 1,957 of 138,982 pool documents (1.4%) are flagged. Recall is unknown (fact-checkers outside the host list are missed).
- Limitations: default exclusion removes about 0.4% of pool documents wrongly. Malak to confirm the judgement.
