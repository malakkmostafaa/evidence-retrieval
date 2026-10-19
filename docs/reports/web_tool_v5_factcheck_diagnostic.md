# Web tool v5 - fact-check condition as a leakage diagnostic

Date: 2026-10-20. Pool claims (ranks 0-179), same cached Serper results as main. **This is a diagnostic of answer/label leakage, not a candidate setting**: it keeps pages from fact-check domains (`evret.audit.is_factcheck`), so a higher score measures how much of the answer sits in fact-checkers' pages. The claim's own article stays excluded (and so does any URL matching it). Everything else equals main (same queries, same date filter, same Wayback logic).

**Cost.** 0 queries (counter unchanged at 191 of 2,500; the API key was deliberately not set in the process). It did need new page fetches, because fact-check pages were never downloaded in main: 241 CDX lookups, 118 live fetches, 31 Wayback fetches, 52 robots.txt requests. Replay of the 180 runs afterwards: 0 network calls, identical hits and scores. Files: `outputs/web_full_serper/factcheck_compare.{json,md}`.

**Detectability.** Differences below about 0.05 are not detectable at n = 180 (88-91 for coverage); read the CIs.

## What happened to the 175 fact-check URLs that main removed
| outcome in the fact-check run | URLs |
|---|---|
| dated after the claim (still removed by the date filter) | 67 (38%) |
| HTTP 403 / 429 | 41 / 2 |
| robots.txt | 18 |
| date unknown (removed, as in main) | 1 |
| **kept** | **46 (26%)** |

83 claims had at least one such URL; the top-50 changed for 30 of them. 226 of the 3,934 top-50 passages (5.7%) come from fact-check-looking URLs. 46 more pages are kept (464 vs 416); claims with a kept page 150 vs 144. **Most fact-check pages are already neutralised by the date cutoff** (a fact-check written about a 2020 claim is normally published after it) or by access limits; the 46 survivors are older fact-checks that carry a Wayback snapshot or a date before the claim.

Self-check: the fact-check run equals main except for the URLs main removed as fact-check, with 2 exceptions of another kind (claims 328 and 463): a Wayback lookup had failed transiently in main (the lookup errors are not cached) and succeeded now, which changed one URL each (403 -> kept, dated-after -> kept). Main is therefore slightly disadvantaged for those two URLs; this does not change the reading.

## Paired change against main (same metrics, 10,000-resample bootstrap)
| variant | metric | n | main | fact-check | diff [95% CI] | W/T/L | claims with diff != 0 |
|---|---|---|---|---|---|---|---|
| primary: all claims | CovNovel@512 | 88 | 0.273 | 0.297 | +0.024 [-0.002, +0.052] | 7/77/4 | 11 |
| primary | CovUnion@512 | 91 | 0.334 | 0.367 | +0.033 [+0.005, +0.065] | 9/78/4 | 13 |
| secondary: claims with a kept page | CovNovel@512 | 75 | 0.321 | 0.348 | +0.028 [-0.001, +0.062] | 7/64/4 | 11 |
| secondary | CovUnion@512 | 78 | 0.390 | 0.428 | +0.038 [+0.006, +0.075] | 9/65/4 | 13 |

Gold: the claims with a gold page in the top-50 / top-10 do not change (11 / 10); the 10 gold entries that main lost as "fact-check domain" are only 3 distinct pages, and none of them is recovered here (2 return HTTP 403, 1 is dated after the claim).

## Reading
The coverage change is small: +0.02 to +0.04, below the ~0.05 that can be detected here. Only the CovUnion CI excludes 0 (lower end +0.005), CovNovel does not. About 12-14 claims change at all, and 4 of them get worse (the added passages displace better ones). So under the date cutoff, fact-check pages add little answer coverage in this sample; the leakage that a fact-check-friendly setting would allow is mostly blocked by the protocol itself, not by the domain filter alone. This says nothing about unfiltered fact-check access without a date cutoff, which was not measured. The domain filter stays on in the main condition (WD3) because the AVeriTeC task excludes fact-checking evidence for label-leakage reasons.

## Limitations
n = 180 (88-91 for coverage), one engine day; the fact-check list is a host list plus a path regex (D8: ~72% precision, unknown recall), so some fact-check pages are not flagged and some flagged pages are not fact-checks; 59 of the 175 URLs could not be fetched at all (403, robots, 429); Wayback coverage as in main.
