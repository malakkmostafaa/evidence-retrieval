# Plan: corpus retrieval tool (Blocks 3-7) - S0

Status: written 2026-10-19. Estimates are labelled **[est]** (assumption, replaced by measurement) or **[meas]** (measured).

## Inputs found
ZIPs `C:\Users\malak\Desktop\ks\ks_upload` (8 parts), subsets, dev.json: all present. **Old split file `corpus_split_seed42_h40.json`: not found** on disk (searched Desktop, Documents). Until you give a path, D3 uses a fresh seeded, label-stratified ranking of all 300 claims (so the pool will NOT be identical to the earlier experiments' pool). The code accepts `--old-split PATH` already; re-running ingest is cheap (see risks).
Missing package `pyarrow` was installed in the venv (needed for Parquet). Free RAM right now is only ~2.7 GB of 16 GB, so every stage is memory-bounded and uses at most 4 worker processes (spawn).

## Modules (package `evret`)
| module | job |
|---|---|
| `pool.py` | D3 ranks 0-299, bands, pool cutoff (pure functions, no I/O except the dev/subset/split JSONs) |
| `ingest.py` | pass 1 (keys, min_rank, flags, origins; no text kept) and pass 2 (documents Parquet) + manifest |
| `chunk.py` | word packer (generator), token cap/split, per-band chunk Parquet, `chunk_text.sqlite` |
| `embed.py` | benchmark, resumable band-by-band embedding to float16 `.npy` shards + manifest |
| `search.py` | `Retriever` interface, `DenseExact`, `BM25`, `Hybrid` (RRF), filters, `search_batch` |
| `eval_pool.py` (eval layer) | the ONLY place that touches claims/gold/origins: builds `exclude_norm_urls`, scores SourceHit |

## Schemas (all under `data/corpus_v1/`, git-ignored)
- `documents/band=B/part-N.parquet`: doc_id (=doc_ord, int64), norm_url, url, host, content_hash, text (string), n_chars, n_items, n_words, is_pdf, is_empty, is_tiny, is_factcheck, pub_date, date_source, min_rank, band. Sealed bands: metadata only, no text (see change 1).
- `origins.parquet`: doc_id, claim_rank, claim_id, type, query, url_raw, line_no. Never read outside `ingest`/`eval`.
- `chunks/band=B.parquet`: chunk_id (global, int64), doc_id, piece, start, end (code points), n_tokens, text_hash (int64), flags, text.
- `chunk_text.sqlite`: chunk_id -> UTF-8 BLOB (derived, rebuildable).
- `vectors/band=B/shard-NNNN.npy` (float16, <=50k x 384) + `embed_manifest.json` (model, revision, chunk-table sha256).
- `bm25/band=B/`: term-hash-grouped postings (see change 2).

## Suggested changes to your instructions (I will proceed with these unless you object)
1. **Sealed bands: write metadata only, no text.** Their text is never allowed to be used, so not writing it is the strongest form of the seal and cuts pass 2 to the 180 pool stores (~40% less reading, ~2-3 GB less disk). Reconciliation with the audit uses pass 1 totals (counts and characters over all 300 stores; this touches no sealed text). A flag `--include-sealed-text` exists for the final test run.
2. **BM25: own implementation on numpy, disk-backed, per band** (not bm25s / one in-memory matrix). [est] ~1.2e9 postings for the pool would need ~10 GB RAM in one scipy matrix; we have 16 GB total, ~3 GB free. Per-band postings (term hash uint64 grouped, chunk_id int32, tf uint16) are memory-mapped; IDF and average length are computed globally over the finished bands at load time, so "works on whichever bands are finished" holds. Same formula (k1=1.5, b=0.75, Lucene-style idf), checked against a closed-form toy corpus.
3. **Document `n_tokens` includes [CLS]/[SEP]** (what the model sees), so the 512 limit is checked directly.
4. **Packer rule made explicit (it was ambiguous):** words = maximal non-whitespace runs; a chunk ends at the FIRST sentence/line boundary at or after word 200 (word ends in . ! ? possibly followed by quotes/brackets, or is followed by a newline), else at word 250; next chunk starts 20 words before the end; the final chunk is emitted only if it contains words not already covered. Big documents (38M chars) are processed with a regex scan, never by splitting the whole text into a word list.
5. **Dedup to merge only on exact (normalized URL, hash)** as you said; identical texts under different URLs stay separate documents (cost: ~1% more text, [meas] 10.60e9 vs 10.48e9 chars).
6. Pass 1 in parallel (one worker per store, 4 workers); output is merged in rank order so results are deterministic.

## Estimates [est]
| stage | pool (bands 0-5) | all-300 reference |
|---|---|---|
| ingest pass 1 | ~8-12 min | 21.7 GB read |
| ingest pass 2 | ~6-10 min, ~2-3 GB zstd | |
| chunk | ~8M chunks (746 chars/chunk from the audit), 15-30 min on 4 procs, chunks Parquet ~4 GB, sqlite ~12 GB | 14.1M chunks |
| embed | BGE-small fp16 on RTX 3060: ~800-1500 chunks/s -> 1.5-3 h; vectors ~6 GB | 10.9 GB |
| BM25 build | 20-40 min, ~7 GB | |
| total new disk | ~30-35 GB of ~56 GB free | |

## Risks
- **RAM** (2.7 GB free): bounded generators, small batches, mmap; I will check `psutil` before each long job.
- **Old split missing** -> pool differs from earlier experiments. Fix: give me the file, re-run ingest (~15 min) before chunking if you want that equality. I will start chunking only after your answer or after S1 is verified, whichever you prefer; default: continue.
- PDF text is noisy (columns, tables, ligatures); chunks of such text hit the token cap more often. Measured, not hidden.
- Disk: the SQLite text copy is 12 GB duplicate text; it is deletable and rebuildable.
- Windows: spawn only, `__main__` guards, utf-8 explicit, no `splitlines()`.
- Fact-check heuristic precision unknown until you see the 50 sampled URLs (S1 output).
