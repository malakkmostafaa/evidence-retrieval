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
- Decision: passages are computed in fp32 on the CPU (Encoder(device="cpu", dtype="fp32")) and stored as float16 like the corpus; the corpus used fp16 on the GPU (D10 verified GPU-fp16 vs fp32 cosine > 0.999, so the difference is below ranking noise but not zero). BM25 uses N, avgdl (corpus pool, all six bands, N = 6,415,863) and the df of the query terms read from the term offsets (no postings); the df of every term used is frozen into the run manifest. Documents shorter than 200 characters are not chunked (D8). RRF depth 100 per list (raised to N if N > 100), ties -> earlier page/passage in input order (input order = engine rank, then position in the page).
- Evidence: tests/test_web_select.py equivalence test: on the tiny corpus built by the real pipeline, the web path (own chunker call, own scoring) returns the same passages in the same order for 7 queries with RRF scores equal to 1e-12, dense to 1e-5, BM25 to 1e-4 relative; 14/14 injected bugs in select.py were caught.
- Measured: BGE-small on this CPU (8 threads, fp32): 16.5 chunks/s for ~300-token chunks, model load 11 s. A page with 20 chunks therefore costs ~1.2 s, 10 pages ~12 s.
- Limitations: BM25 float64 here vs float32 in the corpus (relative difference ~1e-7); df is frozen from the pool as it is today (all six bands final).


## WD1b: Engine failures are failures, not "no results"   [engineering]   2026-10-19
- Decision: an exception or an empty answer is retried (4 attempts, waits 2/4/8 s, 3 s spacing), then recorded as a search failure (`failures` table, replayed as `RecordedFailure`), never cached as an empty result. The tool returns no hits and sets `last_report.search_error`.
- Evidence (E, smoke run): 81 search attempts: 15 ok, 62 `DDGSException: No results found`, 4 empty list. Two claims failed in all conditions; three claims first failed and later succeeded.
- Limitation: a claim whose search failed counts as 0 gold hits; it is reported separately (13 of 15 claims had results).

---
## Open decisions after WS5 (waiting for Malak) - recommendation last

### WQ5: Search reliability (62 of 81 attempts failed)
| option | pros | cons | cost | evidence |
|---|---|---|---|---|
| keep duckduckgo only, accept failures | simplest, one backend recorded | web arm is sparse; 2 of 15 claims empty | none | E (this run) |
| fallback backend `yahoo` when duckduckgo fails (backend stored per result) | gave 7 results in the earlier probe; no new software | second scraped engine with different ranking; also may be throttled | ~30 lines | E (one probe) |
| SearXNG (self-hosted) | one aggregated, configurable interface | needs Docker or WSL on Windows; RAM is low; still scrapes engines | setup hours, ~500 MB RAM | A |
| slower spacing (e.g. 10 s) | may reduce throttling | longer runs; no proof it helps | time | A |
| Tavily / Serper (free tiers) | official APIs, stable | key needed, limited credits (1,000 / month; 2,500 one-time) | account | E (vendor pages, sources disagree on details) |
Recommendation: yahoo fallback now, test SearXNG later if the web arm is kept.

### WQ6: Date priority when a page has both a URL date and an htmldate value
| option | pros | cons |
|---|---|---|
| htmldate first (current) | uses page content | page-chrome dates (2026) override a clear URL date: at least 2 of 31 "dated after" pages are wrong in this sample |
| URL date first | URL dates are usually the publication date | absent for most pages; stale for re-published pages |
| the EARLIER of the two | fewer false removals | can admit a leaked page whose URL carries an old date |
| the LATER of the two | never admits a leak from a stale URL date | loses the pages above (same as current) |
Recommendation: keep current (it never admits a leak) and report the false-removal rate from the manual review; revisit with more claims.

### WQ7: Partial dates ("2020-03")
Not met in this sample (0). Current rule: earliest possible day (consistent with the corpus, D5). Stricter alternative: latest possible day. Decide when it occurs.

### WQ8: Query formulation
Current: claim text unchanged. Alternatives: strip quotation marks, truncate to the first 200 characters, or extract keywords. None tested; the failures seen are throttling, not the query form. Recommendation: no change now.

### WQ9: Held-out claims used
Ranks 180-189 were used and inspected (as asked). From now on treat them as seen for the web tool.

---
## WD1c: Serper is the provider for evaluation runs   [evaluation]   approved by Malak 2026-10-19
- Decision: `SerperProvider` (POST https://google.serper.dev/search, key from env var `SERPER_API_KEY`, body {q, gl=us, hl=en, num=10, autocorrect=false}; backend recorded as "google", version "serper-search-v1"). ddgs stays for development and unit tests only. A cache directory is locked to one provider (`provider.json`); mixing providers within one experiment raises an error. `autocorrect=false` so the engine does not rewrite the claim text silently (the API default is on).
- Query budget (system): persisted counter in `~/.evret/query_budget.json` (override dir with EVRET_BUDGET_DIR), shared by all worktrees; counts every request SENT; warning at 1,500, refusal at 2,300 unless `EVRET_BUDGET_OVERRIDE=1`; the search cache means re-runs and REPLAY cost 0 queries; a 4xx answer (bad key, no credit) is not retried; an empty `organic` list is a genuine result (cached, not retried).
- Terms checked 2026-10-19 (serper.dev homepage and /terms): "Get 2,500 free queries", "No credit card required". The terms say nothing about caching/retaining results, academic use, free-credit expiry or rate limits; they forbid mirroring the materials as-is without added value, misrepresenting the source, removing proprietary notices, and circumventing key limits. /pricing returned 404, so **credit expiry and rate limit remain unverified** (third parties say paid credits expire after 6 months). Consequences: the raw cache (`outputs/web_cache*`) is git-ignored and not redistributed; only derived statistics and short passage excerpts appear in reports; the thesis should name Serper/Google as the source; use the free credits soon after account creation.
- Limitation: external commercial service; queries are sent to a third party; results are Google's ranking of 2026, not the 2020 index AVeriTeC's annotators used.
