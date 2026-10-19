# Plan: web search tool (Block W) - WS0

Status: written 2026-10-19. **[est]** = assumption until measured, **[meas]** = measured, **[ver]** = verified from a source on 2026-10-19.

## Idea in plain words
Stage 1 (the search engine) picks ~10 pages for a query. Stage 2 (our code) downloads them, throws away anything that
could leak the answer (published after the claim, the claim's own fact-check, other fact-checkers), cuts the rest into
passages exactly like the corpus tool, and keeps the best N passages. A later shared cross-encoder (not here) re-ranks
corpus and web candidates together. Everything the network returns is stored in a frozen cache so a run can be replayed.

## Inputs found
- Corpus code to reuse unchanged: `evret.chunk` (pack_200_250, `make_counter`, `chunk_document`), `evret.embed.Encoder`
  (BGE-small, revision pinned), `evret.bm25` (`tokenize`, `term_hash`, `BM25Index.idfs`), `evret.urls` (`canonical`,
  `url_variants`), `evret.audit.is_factcheck`, `evret.search.Hit`/`Filters`.
- Pool BM25 statistics: `evret-main/data/corpus_v1/bm25/band=0..5` (all six bands exist, N = 6,415,862 chunks). Read-only; I read
  only `meta.json`, `doclen.npy` (sum -> avgdl) and the term offsets (-> df of the query terms). No postings are loaded.
  To stay reproducible the web tool copies N, avgdl and the df of every query term it uses into the web cache manifest.
- dev.json present. The worktree has no `data/` and no `.venv` (see open question Q1).
- Free RAM is 4.5 GB: tests use CPU and tiny batches only.

## Modules (`src/evret/web/`)
| module | job |
|---|---|
| `schema.py` | `WebHit` (extends `Hit`), `ClaimContext`, enums for fetch_status/date_source, outcome counters |
| `providers.py` | `SearchProvider` interface, `DdgsProvider` (explicit backend), `SearxngProvider`, rate limiter (3 s), `SearchCache` |
| `wayback.py` | CDX lookup (`to=<claim date>`, status 200, newest snapshot at/before the date), snapshot URL builder |
| `fetch.py` | httpx client, robots.txt, per-domain lock, retries/backoff, 25 MB cap, call log, `PageCache` (SQLite + blobs) |
| `extract.py` | trafilatura for HTML, PDF extractor, htmldate, URL date |
| `filters.py` | date filter, own-article filter (unwrapping matcher), fact-check filter; returns a reason for every removal |
| `select.py` | chunk -> embed (cached) -> dense cosine + BM25 with pool statistics -> RRF(60) -> top N |
| `tool.py` | `search_web(query, k, filters, claim_context)`; modes LIVE / REPLAY; manifest hash |
| `eval_web.py` | the only module that sees gold URLs (smoke evaluation, WS5) |

## Data flow and schemas
```
query --provider--> [(url, title, snippet, engine, engine_rank)] x10        (search cache)
  --each url--> own-article / fact-check URL filter (before any download: saves requests)
  --Wayback CDX(to=claim_date)--> snapshot or none                          (counted: wayback found / none)
  --fetch (snapshot or live)--> bytes, status, hash                         (page cache)
  --extract--> text, pub_date, date_source                                  (page cache)
  --date filter--> kept / dated_after / unknown(excluded in main, kept in lenient)
  --chunk (pack_200_250) + BGE embed (cached)--> passages
  --dense, BM25 (pool stats), RRF--> top N WebHit
```
`WebHit` = corpus `Hit` fields (chunk_id = stable hash of url+start, doc_id, rank, score, retriever, dense_score, bm25_score,
text, start, end, url, domain, is_pdf, pub_date, date_source, flags) + `source="web"`, `fetched_from`, `wayback_timestamp`,
`engine`, `engine_rank`, `fetch_status`, `page_hash`, `fetch_time`, `hybrid_score`, `vector` (kept for the later reranker).
Corpus modules are not modified; `WebHit` subclasses the dataclass.

## Order of the date/leakage checks (cheapest first)
1. URL-level: own article / original_claim_url (unwrapped), flagged fact-check domain (main condition) - no download needed.
2. Wayback lookup, fetch, extract, date. 3. date filter. A page removed at an earlier step is never downloaded.
Counters per query: `returned, removed_own, removed_factcheck, wayback_found, fetch_failed (by status), dated_le, dated_after, unknown, kept`.

## Risks
| risk | handling |
|---|---|
| ddgs scrapes engines: blocks, CAPTCHAs, silent changes, 202 rate limit | explicit backend, 3 s spacing, backoff, cache, SearXNG fallback; reported as a limitation |
| Wayback snapshot older than the page's current content, or redirects/soft-404 | status 200 filter on CDX; snapshot is by construction not newer than claim date; check text length |
| Wayback fetch is slow (several s) and rate-limited | 1 CDX + 1 fetch per page, cached forever; counted separately |
| htmldate guesses wrong dates | date_source recorded; manual-review list in WS5 |
| RAM 4.5 GB | CPU BGE-small, batch 16, one page at a time; PDFs capped at 25 MB |
| gold URL leakage into the search code | `claim_context` carries only date + exclusion URLs; gold only in `eval_web.py` |
| pool df/N change when the other session adds bands | N, avgdl, df copied into the cache manifest; all six bands are final |
| robots.txt blocks many news sites | recorded as `robots_blocked`; Wayback snapshot is fetched from archive.org, so it is not affected |

## Expected seconds per claim [est]
search 1 query ~2 s + wait; CDX 10 x ~1.5 s; fetch 10 pages ~10-25 s (politeness, mix of wayback and live); extract ~2 s;
chunk <1 s; embed ~300 chunks on CPU at 20-40 chunks/s ~ 8-15 s; select <1 s. **Total ~30-60 s per claim** on a cold cache, ~12 s warm.
The smoke run (15 claims) is therefore ~10-15 min. Replaced by measurement in WS5.

## Verified facts used in decisions [ver]
- ddgs 9.16.0 (PyPI, 26 Aug 2026); text backends: bing, brave, duckduckgo, google, grokipedia, mojeek, startpage, yandex, yahoo, wikipedia; default "auto".
- arXiv 2602.00758 (El Lahib et al.): date-filtered search leaked post-cutoff content for 71% (Google) / 81% (DuckDuckGo) of questions.
- Tavily 1,000 credits/month free; Serper 2,500 free queries one-time; Brave $5 monthly credit, card required (sources disagree, re-check before citing);
  Google Custom Search JSON closed to new users, ends 1 Jan 2027. Bing Search API retirement (Aug 2025): from your brief, not yet re-verified.
- Wayback CDX `from`/`to` (inclusive, yyyyMMddhhmmss), `filter=statuscode:200`, `limit`, `collapse`; `sort=closest` is disputed in third-party sources -> I will test it in the WS2 live smoke test and not rely on it.

## Open questions (details in docs/decisions_web.md, WQ1-WQ4)
Q1 environment, Q2 PDF library, Q3 which Wayback snapshot, Q4 Wayback raw (`id_`) vs normal replay.
