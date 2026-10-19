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

---
## Answers (Malak, 2026-10-19)
- WQ1 = new worktree venv with CPU torch (.venv: ddgs 9.16.0, trafilatura 2.3.1, htmldate 1.11.0, pypdf 6.21.1, httpx 0.28.1, torch 2.14.1+cpu). BGE-small snapshot read from the shared HF cache (same pinned revision).
- WQ2 = pypdf (light on RAM; layout quality on complex PDFs is a known limitation).
- WQ3 = newest snapshot with status 200 at or before the claim date.
- WQ4 = raw id_ form of the Wayback URL.

## WD1a: ddgs backend = "duckduckgo" (provisional)   [methodology]   2026-10-19
- Evidence (E, one probe, query "Eiffel Tower height in metres", region us-en, 3 s apart): duckduckgo 10 results (2.2 s), yahoo 7 (1.0 s); bing, brave, google, mojeek, startpage returned "No results found" at that moment. Recorded fixture: tests/web_fixtures/ddgs_duckduckgo_eiffel.json.
- Alternatives: yahoo (fewer results), others (not working today). Backends can start/stop working at any time; the backend name is in the cache key and on every result.
- Limitation: single probe, n=1 query; re-probe at WS5 start.

## WD2a: Wayback CDX query (verified live 2026-10-19)   [engineering]
- Request: `GET https://web.archive.org/cdx/search/cdx?url=<url>&output=json&fl=timestamp,original,statuscode,mimetype,digest&filter=statuscode:200&to=<claim date>235959&limit=-1`. Verified: `to` is an inclusive upper bound; `limit=-1` returns the LAST (= newest) matching row, i.e. the newest 200-snapshot at or before the claim date (WQ3); an unknown URL returns `[]`; the first JSON row is the header. `sort=closest&closest=...` also worked once but is not needed. Recorded fixtures: tests/web_fixtures/cdx_*.json.
- Snapshot fetch: `https://web.archive.org/web/<timestamp>id_/<original>` (raw bytes, WQ4). Verified: returns text/html of the capture; a requested timestamp without an exact capture is redirected to the nearest one (can be EARLIER or LATER), so we request only timestamps taken from the CDX answer and re-check that the final URL's timestamp is <= the claim date.
- "At or before the claim date" is evaluated at day granularity (to = YYYYMMDD235959).

## WD4a: Fetcher details   [engineering]   2026-10-19
- Decision: robots.txt per RFC 9309 (4xx = allowed; 5xx/unreachable = disallowed; robots not applied to web.archive.org snapshots); retries on timeout/transport error/429/5xx: 3 attempts, waits 1 s and 2 s; 404 etc. recorded, not retried; archive.org spaced >= 1 s between requests; per-request deadline 45 s; raw bytes stored zlib-compressed by sha256 (lets us re-run extraction without re-downloading). User-Agent: `evret-thesis-bot/0.1 (academic research, bachelor thesis; non-commercial; ...)`, WITHOUT a contact e-mail (none was authorised); add one via `Fetcher(user_agent=...)` if the supervisor wants it.
- Limitation: robots is checked for the first URL only, not for each redirect hop.

## WD2b: Date handling details   [methodology]   2026-10-19
- Decision: (1) Wayback snapshot: pub_date = snapshot day = UPPER bound of the publication date, date_source "wayback", always counts as <= claim date; the htmldate value of the snapshot is stored separately (`html_date`) for manual review only. (2) htmldate is called on the page content only (`original_date=True`, no URL passed) because with a URL it silently reads the URL path and would be mislabelled "htmldate" (found by a test). (3) URL date second, "none" last. (4) Partial dates ("2020-03") are compared by their EARLIEST day, the same rule as the corpus `not_after` filter (D5) - consistent but permissive: a page dated "2020-03" passes for a claim on 2020-03-10. Counts of partial dates are reported in WS5. (5) The same day counts as before (<=). (6) If the claim has no date, nothing is removed by date.
- Alternative for (4): latest possible day (stricter, fewer leaks, fewer pages). Not chosen yet; ask Malak if the WS5 numbers show it matters.

## WD4b: Extraction details   [engineering]
- trafilatura defaults with include_comments=False, include_tables=True; pypdf reads at most 300 pages (cut recorded in `note`); non-HTML/PDF types give empty text with a note.

## WD5a: First-pass selection details   [methodology]   2026-10-19
- Decision: passages are computed in fp32 on the CPU (Encoder(device="cpu", dtype="fp32")) and stored as float16 like the corpus; the corpus used fp16 on the GPU (D10 verified GPU-fp16 vs fp32 cosine > 0.999, so the difference is below ranking noise but not zero). BM25 uses N, avgdl (corpus pool, all six bands, N = 6,415,862) and the df of the query terms read from the term offsets (no postings); the df of every term used is frozen into the run manifest. Documents shorter than 200 characters are not chunked (D8). RRF depth 100 per list (raised to N if N > 100), ties -> earlier page/passage in input order (input order = engine rank, then position in the page).
- Evidence: tests/test_web_select.py equivalence test: on the tiny corpus built by the real pipeline, the web path (own chunker call, own scoring) returns the same passages in the same order for 7 queries with RRF scores equal to 1e-12, dense to 1e-5, BM25 to 1e-4 relative; 14/14 injected bugs in select.py were caught.
- Measured: BGE-small on this CPU (8 threads, fp32): 16.5 chunks/s for ~300-token chunks, model load 11 s. A page with 20 chunks therefore costs ~1.2 s, 10 pages ~12 s.
- Limitations: BM25 float64 here vs float32 in the corpus (relative difference ~1e-7); df is frozen from the pool as it is today (all six bands final).
