# Web tool v3 - pool claims, main condition, Serper (Google)

Date: 2026-10-19. 180 pool claims (ranks 0-179 = bands 0-5, from the shared `ranks.json` / corpus manifest; no sealed claim queried). Condition **main** only (fact-check domains removed, unknown dates removed, own article removed). Provider `serper/google/serper-search-v1`, query = claim text with the quotation-mark fallback (WD1d). Raw: `outputs/web_full_serper/` (results.jsonl, summary.md, diagnosis.md with the 180-row per-claim funnel, manual_review.md, manifest*.json, logs). Lenient and fact-check conditions have **not** been run (waiting for approval).

## Gold-URL funnel (481 gold URL entries of 180 claims; 167 are Wayback wrappers)
| step | gold entries | claims with >= 1 |
|---|---|---|
| gold URL entries | 481 | 180 |
| returned by Serper (exact URL after unwrapping) | 28 | 16 |
| passed URL filters (own article, fact-check domain) | 18 | 11 |
| fetched OK | 15 | 11 |
| passed date filter | 15 | 11 |
| enough text (kept) | 15 | 11 |
| in top-50 passages | 15 | 11 |
| in top-10 / top-5 passages | 12 / - | 10 / 9 |

Reading: of the 28 returned gold entries, 10 were removed as fact-check domains (the annotators themselves used fact-checkers for part of their sources; WD3 ablation) and 3 by robots.txt; every gold entry that was fetched also passed the date filter and reached the top-50. The loss is overwhelmingly **before** the filters: only 28 of 481 gold entries (6%) are returned by the engine at all (the gold host appears for 92). Whether the other gold pages are dead, moved or simply not retrieved by a claim-text query was not checked (it would need 481 CDX lookups and fetches; not run).

## All returned URLs (1,765)
| outcome | URLs |
|---|---|
| removed: dated after the claim | 433 (25%) |
| removed: fact-check domain | 175 (10%) |
| removed: own article | 53 (3%) |
| removed: date unknown | 38 (2%) |
| lost: robots.txt | 346 (20%) |
| lost: HTTP 403 / 429 / other fetch failures | 241 / 9 / 18 (405 x2, 406 x4, 202, 203, 307 x2, timeout x5, too large x2, protocol error) |
| tiny or no text | 36 |
| **kept** | **416 (24%)** |

Wayback: 300 of 1,537 looked-up URLs (20%) had a snapshot at or before the claim date (41 lookups failed). Kept pages are dated by snapshot (293), htmldate (120) or URL (3); 408 HTML, 8 PDF. 36 of 180 claims have no kept page (0 passages).

## Seconds per claim (wall clock; 3 CPU threads)
| step | mean s/claim | share |
|---|---|---|
| search (incl. 1 s spacing) | 2.4 | 8% |
| Wayback lookups | 11.9 | 38% |
| fetch | 10.6 | 34% |
| extract | 1.2 | 4% |
| chunk | 0.0 | 0% |
| embed (CPU, 3 threads) | 5.4 | 17% |
| select | 0.0 | 0% |
| **total** | **31.6** (169 cold claims; 29.8 over all 180) | |

Embedding is 17% of step time, below the 20% threshold but close (3 threads instead of 8); no cascade proposed. 39 passages per claim on average. Whole run about 1.5 h.

## Queries
- This invocation: **148** live queries (the 32 claims done earlier were reused from the cache). Total counted on this machine: **191 of 2,500** (counter `~/.evret/query_budget.json`), which includes the 15-claim smoke run (10 of those claims are sealed, see WQ9) and the stopped 300-claim run.
- Fallback: **2** of 180 claims used the quotation-mark fallback (claims 452 and 130); 178 needed none; 0 searches failed, 0 claims returned no results.
- Sealed claims (bands 6-9) were not queried in this run. For a later sealed run the cost would be one query per claim plus fallbacks (the pool rate was 2 per 180).

## Replay check
Replay of the 180 runs: 0 network calls, 0 queries, identical hits (URLs, passages, scores) and identical per-URL outcomes (0 differences). The replay exposed a real gap, now fixed: the frozen pool statistics were written only at the end of a run, so claims finished in the stopped run were missing from them. The runner now freezes the document frequencies of all claim queries up front (local index, no network) and after every claim. The manifest hash differs between the live run (`d748424c...`) and the replay (`89dcc884...`) only because the frozen-statistics part grew from 1,094 to 1,357 terms; hits are identical.

## Limitations
One day's Google ranking (2026); Wayback covers 20%; 20% of URLs are lost to robots.txt (social media, some publishers) and 14% to HTTP 403; htmldate false "after" dates (v1) not re-measured; robots answers other than 200/4xx (e.g. 202, timeouts) count as "disallowed"; the answer-coverage metric is not included (waiting for the port from the main session).
