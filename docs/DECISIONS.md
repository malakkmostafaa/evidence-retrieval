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

## D9: Chunking - pack_200_250, 20-word overlap, hard cap   [methodology, PROVISIONAL DEFAULT]   2026-10-19
- Decision: words = runs of non-whitespace; a chunk ends at the first sentence/line boundary at or after word 200 (word ends in . ! ? [+ closing quote/bracket] or is followed by whitespace containing "\n"), else at word 250; next chunk starts 20 words earlier; last chunk only if it holds new words. Cap: 500 tokens (counted with the real BGE tokenizer incl. [CLS]/[SEP]) and 5,000 characters; an over-cap chunk is halved (at the whitespace nearest the middle) until every piece fits; nothing is dropped. Empty and tiny documents are not chunked.
- Alternatives considered: fixed 256-token windows, sentence-based chunks, no overlap (not compared yet; this is a default, not an experiment result).
- Evidence (band 0, 30 pool stores, 1,580,741 chunks): 300 random documents / 295,534 chunks: 0 span errors, 0 hash errors, 0 documents with an uncovered non-whitespace character; 2,000 re-tokenised chunks: 0 mismatches of n_tokens; max 500 tokens, max 4,510 chars, 0 chunks over either cap. Mean 285 tokens / 1,250 characters per chunk. 72% of band-0 chunks come from PDFs. 10.3% of chunks (162,407) had to be split by the cap, almost all from PDF text (many word pieces per word, long unbroken strings) - these pieces can start or end mid-sentence.
- Limitations: the 10% split rate shows 250 words is too long for noisy PDF text; a lower word cap for PDFs is an obvious experiment. Chunk boundaries are heuristics (no sentence splitter); lone surrogates are replaced by U+FFFD only for token counting.

## D10: Embedding model and procedure   [methodology]   2026-10-19
- Decision: BAAI/bge-small-en-v1.5 at revision 5c38ec7c405ec4b44b94cc5a9bb96e735b38267a; CLS pooling, L2-normalised, max_length 512 with truncation disabled (a longer sequence raises); passages without prefix, fp16 compute, float16 storage, length-sorted batches (<= 24k tokens); queries fp32 with the card's instruction "Represent this sentence for searching relevant passages: ".
- Evidence: the model's 1_Pooling/config.json has pooling_mode_cls_token = true (dimension 384; no Normalize module, so we normalise); tests/test_embed.py: our fp16 passage vectors vs sentence-transformers fp32 have min cosine > 0.999 on 5 texts, the instruction changes the query vector (cosine to the un-prefixed vector < 0.999), mutation "mean pooling instead of CLS" fails the test.
- Benchmark (RTX 3060 Laptop, 5 min, 6,000 random band-0 chunks, mean 284 tokens): 324 / 306 / 303 chunks/s for token budgets 8k / 16k / 32k (GPU-bound; tokenisation alone 7,168 chunks/s; peak VRAM 0.36 GB). The GPU runs at 652 MHz of 2100 MHz (power/thermal limit), so this is the machine's real speed. Budget 24k used. Eager attention is 1.9x slower than SDPA.
- Limitations: ~300 chunks/s means ~85 min per 1.6M-chunk band; the full pool takes hours.

## D11: Retrieval implementation   [engineering, methodology]   2026-10-19
- Decision: DenseExact (all vectors streamed from memmapped shards through the GPU, inner product, no approximate index); BM25 (own numpy implementation, k1 = 1.5, b = 0.75, regex \w+ on lower-cased text, no stemming, no stop words, Lucene idf ln(1 + (N-df+0.5)/(df+0.5)), unique query terms, disk-backed per band, 64-bit term hashes); Hybrid = RRF with k = 60, equal weights, top-100 of each. Tie-break: lower chunk_id.
- Evidence: BM25 matches hand-computed closed-form scores on a 3-chunk corpus (tests/test_bm25.py, 3 mutations caught); search tests on a corpus built by the real pipeline (tests/test_search.py, 6 mutations caught: tie order, RRF k, URL exclusion, date filter, default fact-check exclusion, mask).
- Limitations: BM25 statistics (N, df, avgdl) are computed over the finished bands only, so scores change when bands are added. 64-bit hashing could collide (probability ~1e-4 in total).

## D12: Own-article exclusion must unwrap Wayback URLs   [methodology, leakage]   2026-10-19
- Decision: `exclude_norm_urls` for a claim contains, for each of fact_checking_article, original_claim_url and (extra, same page) cached_original_claim_url, both the normalised URL as given and the normalised unwrapped original (`evret.urls.url_variants`); the search layer finds a document under its stored URL and under the unwrapped form of it.
- Evidence: all 180 pooled claims' fact_checking_article are `web.archive.org/web/<timestamp>/<original>` wrappers (so are 38 of 97 original_claim_urls and 83 of 96 cached ones). Matched as written they hit 0 / 10 / 0 pool documents; unwrapped they hit 17 / 24 / 24. The Block 1 audit line "fact_checking_article_in_any_store: 0" was therefore a false negative caused by the wrapper, not proof of absence.
- Limitations: pages that merely copy a fact-check under another URL are not caught (the F3 flag handles known fact-check hosts only); the gold source URLs are also partly wrapped (167 of 481), so gold matching uses the same variants.

## D13: BM25 statistics are pool-wide   [methodology]   2026-10-19
- Decision: N, df and avgdl are summed over all active bands (BM25Index.idfs / avgdl); per-band postings only store tf and chunk length. Checked by tests/test_bm25.py: a toy corpus split into bands [0,3), [3,5), [5,8) gives bit-identical scores and the same ranking as one index over the union; a mutation using a per-band average length fails the test; per-band statistics are shown to differ.
- Smoke test with all six bands: for one claim the same query gives sum(idf) 49.7 (band 0 only, N = 1.58M) vs 50.3 (N = 6.42M), i.e. scores change when bands are added, as intended.
- Term statistics (report only, no filtering): band 0 has 1,736,360 distinct terms, 52.3% occur in exactly one chunk; whole pool 5,839,281 distinct terms, 55.8% with df = 1, but they supply only 0.43% of all 761.6M postings. BM25 index = 4.5 GB.
