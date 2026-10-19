# DECISIONS (web tool)

Format as DECISIONS.md. Merged into DECISIONS.md later. Evidence is marked established (E) or assumption (A).

## WD1: Search provider = ddgs behind a SearchProvider interface   [methodology]   2026-10-19
- Decision: `ddgs` (exact version pinned at install; 9.16.0 is the latest on PyPI), text search, explicit backend stored on every result (never "auto"), region us-en, 10 results/query. SearXNG adapter (self-hosted, JSON format enabled) as optional second provider. No paid APIs.
- Alternatives:
| option | pros | cons | cost here | evidence |
|---|---|---|---|---|
| ddgs (chosen) | no key, many engines, one line | scrapes engines, can be blocked or change | free | E: PyPI 9.16.0, backends bing/brave/duckduckgo/google/mojeek/startpage/yandex/yahoo/wikipedia |
| SearXNG | self-hosted, JSON API, stable interface | also scrapes engines; needs Docker/WSL on Windows | RAM + setup | E (documented), A (effort) |
| Tavily | official API, 1,000 credits/month | credits run out, key needed, results tuned for LLMs | free tier | E (vendor + comparison sites) |
| Serper | Google results | 2,500 queries one time only | one-time | E, sources disagree on renewal |
| Brave API | own index | $5 monthly credit, card required | card | E, sources disagree |
| Google Custom Search | - | closed to new users, ends 1 Jan 2027 | - | E |
| Bing Search API | - | retired Aug 2025 | - | from supervisor brief, to re-verify before the thesis cites it |
- Limitation: ddgs and SearXNG scrape engines instead of using official APIs; results change over time and can be blocked (hence the cache, WD6).

## WD2: Temporal leakage by Wayback snapshot + date, not engine filters   [methodology, leakage]   2026-10-19
- Decision: no engine date filter. Per result URL: Wayback CDX lookup with upper bound = claim date; if a snapshot exists fetch it (date_source="wayback", the snapshot timestamp proves the content existed by then). Otherwise fetch live, pub_date from htmldate, else from the URL; keep iff pub_date <= claim_date. Unknown date: excluded in the main condition, kept (flagged) in the "lenient" ablation. Counts: wayback found / dated <= / dated after / unknown.
- Evidence (E): arXiv 2602.00758 (El Lahib et al.): date-filtered search leaked post-cutoff content for 71% (Google) and 81% (DuckDuckGo) of questions.
- Limitations: a Wayback snapshot is a lower bound on age, not the publication date, and a live page may have been edited after its date; htmldate can be wrong.

## WD3: Fact-check and own-article leakage   [methodology, leakage]   2026-10-19
- Decision: always exclude fact_checking_article and original_claim_url (+ cached variant) via `evret.urls.url_variants`; exclude `evret.audit.is_factcheck` URLs in the main condition, include in an ablation (AVeriTeC: ~6% of gold answers came from other fact-checkers).
- Limitation: D8 measured ~72% precision for the flag and unknown recall.

## WD4: Fetch and extract   [engineering]   2026-10-19
- Decision: httpx, timeouts, retries with backoff, robots.txt, honest User-Agent, 1 request at a time per domain, a few domains in parallel, 25 MB cap (`too_large` recorded, never truncated), trafilatura for HTML, PDF library: see WQ2, raw bytes hash and extracted text stored.

## WD5: First-pass passage selection   [methodology]   2026-10-19
- Decision: chunk with pack_200_250 (same caps), embed with BGE-small (same revision/settings), score dense cosine and BM25 with pool statistics (N, avgdl, df of the query terms), RRF k=60, top N=50 (configurable), three scores kept. Cross-encoder not implemented; Hits carry what it needs.
- Alternatives: search snippets only (no date control, too short); all chunks to the cross-encoder (more expensive per passage); BM25 only (misses semantic matches). A (cost), E (known behaviour of lexical retrieval).

## WD6: Two caches + replay mode   [engineering, reproducibility]   2026-10-19
- Decision: `outputs/web_cache/` SQLite + blobs: search cache (provider, backend, version, query, params -> results, timestamp) and page cache (url, wayback_timestamp|"live" -> status, hash, text, date, fetch time, chunks, vectors). REPLAY mode: zero network calls, error on a miss. Each run records a manifest hash of the cache.

## WD7: Budget   [engineering]   2026-10-19
- Decision: <= 1 query / 3 s / provider with exponential backoff, <= 10 pages fetched / query, global timeouts, every network call logged.

---
## Open decisions (waiting for Malak)

### WQ1: Python environment
| option | pros | cons | cost | evidence |
|---|---|---|---|---|
| A. new venv in the worktree, CPU torch, install ddgs/trafilatura/htmldate/pypdf there | cannot disturb the GPU job's environment; clean pins for web deps | ~1 GB download, ~3 min; embeddings on CPU (the same model, tiny numeric difference from fp16 GPU, checked by a test) | disk ~2 GB | A |
| B. install the new packages into the main folder's .venv | no download of torch; GPU available | changes the environment of a running job (version bumps of shared deps such as numpy/lxml could break it) | risk | A |
| C. venv with `--system-site-packages` pointing to main venv | reuses torch | fragile on Windows | | A |

### WQ2: PDF text extractor
| option | pros | cons | evidence |
|---|---|---|---|
| pypdf | pure Python, light, no native deps | weaker layout/ordering on complex PDFs, slower on big files | A |
| pdfminer.six | better text order and layout analysis | slower, more RAM, heavier API | A |
| PyMuPDF | fastest, best quality | AGPL licence, native binary | A |

### WQ3: which Wayback snapshot at/before the claim date
| option | pros | cons |
|---|---|---|
| newest snapshot <= claim date | closest to what the claim-checker could see | page may be a redirect/error stub |
| oldest snapshot | maximally safe | may predate the content being added |
| first with status 200 and text > 200 chars, newest first | robust | one extra fetch sometimes |

### WQ4: Wayback fetch form
| option | pros | cons |
|---|---|---|
| raw `.../web/<ts>id_/<url>` | original bytes, no toolbar/rewritten links | none notable |
| normal replay | what a browser sees | injects Wayback banner text into the extracted page, rewritten links |
