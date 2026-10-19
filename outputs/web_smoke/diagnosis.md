# Diagnosis of the web smoke run (cached data; 4 extra probe calls to the engine)

## 1. Search failures

81 search attempts logged: error:DDGSException: 62, ok: 15, error:EmptyResult: 4.

**Cause (diagnosed live with 4 probe calls, see text below):** the netlog only keeps the exception class. `ddgs` turns every non-200 answer of the engine into `None` and, when no engine raised, into `DDGSException('No results found.')`. A direct request to `html.duckduckgo.com/html/` returned **HTTP 202 with DuckDuckGo's anomaly (bot-challenge) page** for the claim queries *and* for a harmless control query ("Eiffel Tower height in metres"). So all 62 `DDGSException` failures are most likely bot-challenges; rate limit headers, timeouts, parse errors and captcha-vs-block cannot be told apart from the cache, and no timeouts or HTTP errors appear (all failures return in 0.3-1.0 s, except two of 5 s).

Timeline (attempt, clock time, gap to previous attempt, result). Runs are separated by long gaps; a query's 4 attempts are 2-9 s apart:

| # | time | gap s | status | s | query (start) |
|---|---|---|---|---|---|
| 1 | 17:19:03 |  | ok | 0.9 | o: The State of Massachusetts commit |
| 2 | 17:19:18 | 15 | ok | 0.8 | o: It's NOT a SECOND WAVE of COVID-1 |
| 3 | 17:20:34 | 76 | ok | 0.9 | o: You see the number today? 33.1 GD |
| 4 | 17:21:53 | 80 | ok | 0.9 | o: Nigeria’s urban population at ind |
| 5 | 17:22:57 | 64 | ok | 0.9 | o: New York City Mayor Bill de Blasi |
| 6 | 17:23:35 | 38 | ok | 1.2 | o: It makes no sense for oil to be c |
| 7 | 17:23:55 | 20 | ok | 0.9 | o: Australian politician, Daniel And |
| 8 | 17:23:57 | 2 | DDGSException | 0.3 | o: Donald Trump said "Last month, I  |
| 9 | 17:24:00 | 3 | DDGSException | 0.3 | o: Donald Trump said "Last month, I  |
| 10 | 17:24:05 | 5 | DDGSException | 1.0 | o: Donald Trump said "Last month, I  |
| 11 | 17:24:14 | 8 | DDGSException | 0.3 | o: Donald Trump said "Last month, I  |
| 12 | 17:29:28 | 314 | ok | 1.1 | o: Donald Trump said "Last month, I  |
| 13 | 17:29:30 | 2 | DDGSException | 0.3 | o: PTFE Sprayed On Blue Masks Causes |
| 14 | 17:29:33 | 3 | DDGSException | 0.3 | o: PTFE Sprayed On Blue Masks Causes |
| 15 | 17:29:37 | 4 | DDGSException | 0.3 | o: PTFE Sprayed On Blue Masks Causes |
| 16 | 17:29:46 | 8 | DDGSException | 0.3 | o: PTFE Sprayed On Blue Masks Causes |
| 17 | 17:29:49 | 4 | DDGSException | 0.8 | o: Breitbart News reports that the d |
| 18 | 17:29:52 | 2 | DDGSException | 0.3 | o: Breitbart News reports that the d |
| 19 | 17:29:56 | 4 | DDGSException | 0.3 | o: Breitbart News reports that the d |
| 20 | 17:30:05 | 9 | DDGSException | 0.8 | o: Breitbart News reports that the d |
| 21 | 17:30:07 | 3 | DDGSException | 0.3 | o: People are trying to lower the le |
| 22 | 17:30:11 | 4 | DDGSException | 1.1 | o: People are trying to lower the le |
| 23 | 17:30:16 | 5 | DDGSException | 0.8 | o: People are trying to lower the le |
| 24 | 17:30:24 | 8 | DDGSException | 0.3 | o: People are trying to lower the le |
| 25 | 17:30:31 | 6 | ok | 3.6 | o: The Democrats deliberately spread |
| 26 | 17:31:07 | 36 | ok | 1.3 | o: Sunil Gavaskar said that "Virat K |
| 27 | 17:31:14 | 7 | DDGSException | 5.0 | o: The wife of  Lal Bahadur Shastri  |
| 28 | 17:31:21 | 7 | DDGSException | 5.0 | o: The wife of  Lal Bahadur Shastri  |
| 29 | 17:31:26 | 6 | ok | 1.8 | o: The wife of  Lal Bahadur Shastri  |
| 30 | 17:32:15 | 49 | ok | 1.1 | o: Daughters of President Muhammadu  |
| 31 | 17:32:34 | 19 | ok | 0.8 | o: PTFE Sprayed On Blue Masks Causes |
| 32 | 17:32:52 | 17 | ok | 0.8 | o: Breitbart News reports that the d |
| 33 | 17:33:08 | 16 | ok | 0.9 | o: People are trying to lower the le |
| 34 | 17:40:13 | 425 | EmptyResult | 1.1 | o: Donald Trump said "Last month, I  |
| 35 | 17:40:16 | 2 | DDGSException | 0.3 | o: Donald Trump said "Last month, I  |
| 36 | 17:40:20 | 4 | DDGSException | 0.3 | o: Donald Trump said "Last month, I  |
| 37 | 17:40:28 | 8 | DDGSException | 0.3 | o: Donald Trump said "Last month, I  |
| 38 | 17:40:31 | 3 | DDGSException | 0.3 | o: Sunil Gavaskar said that "Virat K |
| 39 | 17:40:34 | 3 | DDGSException | 0.3 | o: Sunil Gavaskar said that "Virat K |
| 40 | 17:40:38 | 4 | DDGSException | 0.3 | o: Sunil Gavaskar said that "Virat K |
| 41 | 17:40:47 | 8 | DDGSException | 0.3 | o: Sunil Gavaskar said that "Virat K |
| 42 | 17:40:50 | 3 | DDGSException | 0.3 | o: Donald Trump said "Last month, I  |
| 43 | 17:40:53 | 3 | DDGSException | 0.3 | o: Donald Trump said "Last month, I  |
| 44 | 17:40:57 | 4 | DDGSException | 0.3 | o: Donald Trump said "Last month, I  |
| 45 | 17:41:05 | 8 | DDGSException | 0.3 | o: Donald Trump said "Last month, I  |
| 46 | 17:41:08 | 3 | DDGSException | 0.3 | o: Sunil Gavaskar said that "Virat K |
| 47 | 17:41:11 | 3 | DDGSException | 0.3 | o: Sunil Gavaskar said that "Virat K |
| 48 | 17:41:16 | 5 | EmptyResult | 0.9 | o: Sunil Gavaskar said that "Virat K |
| 49 | 17:41:24 | 8 | DDGSException | 0.3 | o: Sunil Gavaskar said that "Virat K |
| 50 | 17:41:27 | 3 | DDGSException | 0.3 | o: Donald Trump said "Last month, I  |
| 51 | 17:41:30 | 3 | DDGSException | 0.3 | o: Donald Trump said "Last month, I  |
| 52 | 17:41:35 | 4 | DDGSException | 0.3 | o: Donald Trump said "Last month, I  |
| 53 | 17:41:43 | 8 | DDGSException | 0.3 | o: Donald Trump said "Last month, I  |
| 54 | 17:41:46 | 3 | DDGSException | 0.3 | o: Sunil Gavaskar said that "Virat K |
| 55 | 17:41:49 | 3 | DDGSException | 0.3 | o: Sunil Gavaskar said that "Virat K |
| 56 | 17:41:53 | 4 | DDGSException | 0.3 | o: Sunil Gavaskar said that "Virat K |
| 57 | 17:42:02 | 8 | DDGSException | 0.3 | o: Sunil Gavaskar said that "Virat K |
| 58 | 17:45:42 | 220 | EmptyResult | 1.0 | o: Donald Trump said "Last month, I  |
| 59 | 17:45:44 | 2 | DDGSException | 0.3 | o: Donald Trump said "Last month, I  |
| 60 | 17:45:48 | 4 | DDGSException | 0.3 | o: Donald Trump said "Last month, I  |
| 61 | 17:45:56 | 8 | DDGSException | 0.3 | o: Donald Trump said "Last month, I  |
| 62 | 17:45:59 | 3 | DDGSException | 0.3 | o: Sunil Gavaskar said that "Virat K |
| 63 | 17:46:02 | 3 | DDGSException | 0.3 | o: Sunil Gavaskar said that "Virat K |
| 64 | 17:46:07 | 4 | DDGSException | 0.3 | o: Sunil Gavaskar said that "Virat K |
| 65 | 17:46:15 | 8 | DDGSException | 0.4 | o: Sunil Gavaskar said that "Virat K |
| 66 | 17:46:18 | 3 | DDGSException | 0.3 | o: Donald Trump said "Last month, I  |
| 67 | 17:46:21 | 3 | DDGSException | 0.3 | o: Donald Trump said "Last month, I  |
| 68 | 17:46:25 | 4 | DDGSException | 0.3 | o: Donald Trump said "Last month, I  |
| 69 | 17:46:35 | 10 | DDGSException | 1.6 | o: Donald Trump said "Last month, I  |
| 70 | 17:46:37 | 2 | DDGSException | 0.3 | o: Sunil Gavaskar said that "Virat K |
| 71 | 17:46:40 | 3 | DDGSException | 0.3 | o: Sunil Gavaskar said that "Virat K |
| 72 | 17:46:44 | 5 | EmptyResult | 0.8 | o: Sunil Gavaskar said that "Virat K |
| 73 | 17:46:53 | 8 | DDGSException | 0.3 | o: Sunil Gavaskar said that "Virat K |
| 74 | 17:46:56 | 3 | DDGSException | 0.3 | o: Donald Trump said "Last month, I  |
| 75 | 17:46:59 | 3 | DDGSException | 0.3 | o: Donald Trump said "Last month, I  |
| 76 | 17:47:03 | 4 | DDGSException | 0.3 | o: Donald Trump said "Last month, I  |
| 77 | 17:47:11 | 8 | DDGSException | 0.3 | o: Donald Trump said "Last month, I  |
| 78 | 17:47:14 | 3 | DDGSException | 0.3 | o: Sunil Gavaskar said that "Virat K |
| 79 | 17:47:17 | 3 | DDGSException | 0.3 | o: Sunil Gavaskar said that "Virat K |
| 80 | 17:47:22 | 4 | DDGSException | 0.3 | o: Sunil Gavaskar said that "Virat K |
| 81 | 17:47:30 | 8 | DDGSException | 0.3 | o: Sunil Gavaskar said that "Virat K |

**Pattern.** In the first live run the first 7 queries succeeded (5 minutes, 1 query every 15-80 s because fetching ran in between). From query 8 on, a query failed 4 of 4 attempts spaced 2-9 s; the block lifted again only after pauses: success after 314 s (claim 485), after 36 s (269) and after 6 s (one claim that failed twice first); claims 124, 37 and 418 failed 4 of 4 and succeeded on the re-try about 3 minutes later. In the three re-runs (17:40-17:47) 485 and 269 failed 24 of 24 attempts, and every probe afterwards (including the control query) got the challenge. Failure therefore **clusters after a burst of ~7 queries and persists for minutes; 2-9 s of backoff is far too short to wait it out**. The straight quotation marks in 485 and 269 are not the cause (both succeeded once with the same text).


## 2. Gold-URL funnel (main condition)

Order of the pipeline: search returned the URL -> not removed by the URL filters (own article / fact-check) -> fetch OK -> date filter passed -> enough text -> in top-N passages (N = 50).

| claim | grp | gold URLs | search ok | returned | url filters | fetched | date | text | top-50 passages | top-10 |
|---|---|---|---|---|---|---|---|---|---|---|
| 272 | pool | 3 | yes | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 443 | pool | 2 | yes | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 9 | pool | 1 | yes | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 203 | pool | 3 | yes | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 277 | pool | 4 | yes | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 208 | held | 5 | yes | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 331 | held | 1 | yes | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 188 | held | 3 | yes | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 184 | held | 2 | yes | 2 | 2 | 2 | 2 | 2 | 2 | 2 |
| 111 | held | 1 | yes | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 124 | held | 1 | yes | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 37 | held | 2 | yes | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 418 | held | 5 | yes | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 485 | held | 3 | FAILED | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 269 | held | 5 | FAILED | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| **sum** | | 41 | | 2 | 2 | 2 | 2 | 2 | 2 | 2 |

Gold URL properties: 15 of 41 are Wayback wrappers; the gold *host* appears among the engine results for 3 of 41 gold URLs (exact URL: 2). Dead links / redirects of the gold URLs cannot be judged from the cache (they were never requested, only the 2 returned ones were: both fetched OK). Checking all gold URLs would need 41 CDX lookups + 41 fetches (about 5 minutes); not run, waiting for approval.

## 3. Answer-content coverage proxy

Removed: my own definition was withdrawn on request. It will be added with the original metric code once the main session's port is merged.

## 4. Provider decision (WQ5 revised) - nothing is switched until you approve

Facts used (verified 2026-10-19 unless marked): AVeriTeC's original annotation and baseline used the **Google Search API restricted to documents published before the estimated claim date**; the released knowledge store kept the URLs of the **first results page** of Google queries written by ChatGPT from the claim, gold questions and gold answers (+ distractor queries); the 2023 baseline's own search term was the claim reduced to verbs, nouns and adjectives, keeping 30 results (arXiv 2410.23850, 2305.13117). Serper: 2,500 free queries for a new account, no card; 1 credit per query returning up to 10 results (third-party sources; the official pricing page was not reachable, **credit expiry and rate limit unverified**). DuckDuckGo: HTML endpoint answers 202 + anomaly page when it flags the client (measured today).

**Query budget for a full 300-claim run.** One query per claim (claim text, as now) = **300 queries**, regardless of the three conditions (main / lenient / factcheck read the same cached results). A 500-claim dev run = 500. If we later use 3 queries per claim (claim + 2 reduced or question-style variants) = 900. Re-runs cost 0 queries: the search cache key is (provider, backend, version, query, params), pages and Wayback lookups are cached by URL, REPLAY mode refuses to touch the network, and failures are cached as failures (a live re-run retries only those). Changing the query text, the provider or the backend creates new keys (and new queries); changing filters, K, N, conditions, the chunker's downstream scoring or the date rule does not.

| | A. Fix DDG rate limits | B. Fixed recorded chain DDG -> Yahoo | C. SearXNG self-hosted | D. Serper free tier |
|---|---|---|---|---|
| What changes | wait out the challenge: cooldown after the first 202 (e.g. 5 min, doubling), 15-20 s spacing, one client session | on 202/empty from duckduckgo, ask yahoo; chain order fixed in config; backend of every result stored; cache key includes the chain | run SearXNG (JSON format on); same SearchProvider interface | `SerperProvider` (HTTP POST, API key from an environment variable, never stored in the repo) |
| Queries for 300 claims | 300 successful + retries (retries are free in credits) | 300 + fallback calls | 300 | **300 of 2,500** (leaves ~2,200 for 500-claim dev run or variants) |
| Expected wall time (assumption) | 300 x 20 s = 100 min + cooldowns; our run: block after ~7 queries, minutes to clear => 3-4 h | like A, but fewer idle pauses if yahoo is not blocked at the same time | like A: it scrapes the same engines from the same IP | 300 x ~1 s = minutes |
| Engine = AVeriTeC's | no (DuckDuckGo) | no | mixed (can include Google as one scraped engine, which also gets blocked) | **yes, Google results** |
| Reliability evidence | measured: 62 of 81 attempts failed; no proof that slower helps | yahoo gave 7 results in one probe; not tested under load | not tested; needs Docker/WSL (4.5 GB RAM free) | not tested here; official API, so no bot challenge expected |
| Cost / risk | none; may still fail; IP-level block can last hours | ~30 lines + tests; two scraped engines, both can be blocked, ranking differs per backend, mixing needs a note in the thesis | hours of setup; still scraping; RAM | account needed; terms of service on storing results unchecked; free credits are one-time (expiry unverified); Google ranking of **2026**, not 2020 |
| Reproducibility | cache + manifest as now | cache + chain recorded | cache + manifest; instance version recorded | cache + manifest; results frozen once, re-runs free |
| Limitation to state in the thesis | scraping, unstable | scraping, two engines | scraping | external commercial API; queries sent to a third party |

Not a difference between the options: all return today's web, so the temporal filtering (Wayback + date) is needed in every case; the engine's own date filter (Serper offers one) is not used (WD2, arXiv 2602.00758).

**Recommendation (yours to approve): D for the real 300-claim run** (stable, same engine family as AVeriTeC, 300 of 2,500 queries, cached forever), **keeping A as the free default for development and tests** with a longer cooldown after a challenge. B only if you prefer to stay fully free, C only if you want an aggregator for its own sake. I have not changed any code or provider.
