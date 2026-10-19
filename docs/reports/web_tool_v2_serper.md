# Web tool v2 - smoke evaluation with Serper (Google)

Date: 2026-10-19. Provider: `serper/google/serper-search-v1` (WD1c), claim text as query, `num=10`, `gl=us`, `hl=en`, `autocorrect=false`. Same 15 claims (5 pooled ranks 0-4, 10 held-out ranks 180-189) and the same 3 conditions as v1. Raw files: `outputs/web_smoke_serper/` (results.json, summary.md, diagnosis.md, manual_review.md, manifest.json). **Descriptive only (n = 15).** The v1 DuckDuckGo run (`web_tool_v1.md`) used a different provider and a different cache directory; providers are not mixed (each cache directory is locked to one provider).

## Queries used
- **Live Serper queries in this run: 15** (one per claim; the lenient and factcheck conditions and the replay read the cache). Total on this machine so far: **15 of 2,500** (counter `~/.evret/query_budget.json`; warn 1,500, refuse 2,300). The API reported `credits: 1` per query.
- **Expected for a full 300-claim run: 300 queries** (285 new, because the 15 smoke claims are cached if the query text stays the same). The dev set (500 claims): 500. All conditions and ablations share the cached results, so they add 0. If a query variant is introduced (see "Quotation marks" below) every changed query is a new cache key: at most +1 query for each affected claim. 3 queries per claim would be 900.
- **Re-runs cost nothing**: REPLAY of all 45 runs made 0 network calls and 0 queries, returned bit-identical hits and the same funnel, and the same manifest hash (`47367148...ecee0`).
- Network calls logged in the live run: 15 search, 123 CDX lookups, 64 robots.txt, 65 live fetches, 22 Wayback fetches.

## Gold-URL funnel (main condition)
Gold URLs are entries of the annotators' source list (41 entries for the 15 claims; 15 are Wayback wrappers; several entries of one claim can be the same page). Order of the pipeline: returned by the engine -> not removed by the URL filters (own article, fact-check domain) -> fetched OK -> date filter passed -> enough text -> in the top-50 passages -> in the top-10.

| step | gold entries | claims with >= 1 |
|---|---|---|
| gold URL entries | 41 | 15 |
| returned by Serper | 3 | 1 (claim 418) |
| passed URL filters | 3 | 1 |
| fetched OK | 3 | 1 |
| passed date filter | 3 | 1 |
| enough text | 3 | 1 |
| in top-50 passages | 3 | 1 |
| in top-10 / top-5 | 3 / 3 | 1 / 1 |

The 3 entries of claim 418 are the same page (bhwlawfirm.com), so there is **1 distinct gold page** in the results (v1/DuckDuckGo: 1 claim, 2 entries, claim 184). The gold host (not the exact URL) appears among the results for 8 of 41 entries. Per-claim table: `outputs/web_smoke_serper/diagnosis.md`. Dead or redirected gold URLs cannot be judged from the cache (only returned ones were requested; they were fetched OK or via Wayback). Checking all 41 would need 41 CDX lookups + 41 fetches (about 5 minutes); not run.

## All returned URLs (121 per condition) - where they go
| step | main | lenient | factcheck |
|---|---|---|---|
| returned | 121 | 121 | 121 |
| removed: fact-check domain | 12 (10%) | 12 | 0 |
| removed: own article | 4 (3%) | 4 | 4 |
| removed: dated after the claim | 19 (16%) | 19 | 24 |
| removed: date unknown | 3 (2%) | 0 | 3 |
| lost: HTTP 403 | 15 (12%) | 15 | 19 |
| lost: robots.txt | 29 (24%) | 29 | 30 |
| tiny page | 1 | 1 | 1 |
| **kept** | **38 (31%)** | 41 | 40 |

Wayback: 21 of 105 looked-up URLs (20%) had a status-200 snapshot at or before the claim date (3 lookups failed); 21 of the 38 kept pages are dated by their snapshot, 17 by htmldate. All kept pages are HTML. The robots.txt losses are 9 hosts, mostly social media (facebook, instagram, reddit, quora, x.com); two hosts are blocked only because robots.txt answered HTTP 202 or timed out, which the RFC 9309 rule treats as "disallowed" (a limitation).

Compared with v1 (DuckDuckGo, different day and engine): dated-after 16% (v1 26%), fact-check 10% (v1 19%), kept 31% (same). Not a test of the engines against each other.

## Seconds per claim (main, wall clock, 13 cold claims of 15; 2 returned no results)
| step | mean s/claim | share |
|---|---|---|
| search (incl. 1 s spacing) | 3.1 | 11% |
| Wayback lookups | 11.5 | 40% |
| fetch | 8.4 | 29% |
| extract | 2.8 | 10% |
| chunk | 0.0 | 0% |
| embed (CPU) | 3.0 | 11% |
| select | 0.0 | 0% |
| **total (wall)** | **29.0** | |

Embedding is 11% (< 20%): still no BM25-then-embed cascade needed. Wayback lookups are now the largest step (sequential, at least 1 s apart by design). A 300-claim cold run is about 2.4 h (estimate = 300 x 29 s). Passages per claim: 31.8 on average.

## Quotation marks (new finding, decision WQ8 is now supported by data)
Two claims got **0 results** from Serper: 331 (curly quotation marks around a long quote) and 269 (straight quotes), and 485 (straight quotes) got only 4. Google treats a quoted string as an exact phrase, so a claim that contains a long quotation can match nothing. DuckDuckGo showed the same two claims as failures, but that was mostly the bot challenge. Claim 418, which gave the only gold hit, has no quotes. Options (not applied; the query text is unchanged in this run):

| option | pros | cons | extra queries |
|---|---|---|---|
| keep the claim text as is | simplest; matches v1 | claims with quoted speech return little or nothing (3 of 15 here) | 0 |
| strip quotation marks (" “ ” ‘ ’) from the query | keeps all words; trivial; defensible | changes the query; exact-phrase matches no longer prioritised | 1 per affected claim (~20% of claims, about 60 of 300) |
| fall back to the stripped query only when the first query returns < 3 results | cheapest; recorded in the cache | two query forms in one experiment (documented) | about 1 per affected claim |
| AVeriTeC baseline style: claim reduced to verbs, nouns and adjectives | closest to the original baseline | needs a POS tagger; changes every query | +0 if replacing, 300 new keys |
Recommendation: the fallback rule, because it changes only the failing claims; the decision is yours.

## Limitations
Descriptive, n = 15; one engine, one day; the engine returns the 2026 Google ranking, not the 2020 one; Wayback covers 20% of URLs; robots.txt and 403 remove about a third of the returned URLs (social media, paywalls); htmldate errors from v1 remain (not re-measured); the answer-coverage proxy is **not** part of this report (it will be added with the original metric code once the main session's port is merged). Serper terms: see WD1c (credit expiry and rate limit unverified).
