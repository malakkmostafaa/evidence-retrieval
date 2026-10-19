# Web tool v4 - answer coverage vs the corpus tool, and the lenient condition

Date: 2026-10-20. Pool claims only (ranks 0-179). Everything below was computed from the frozen cache by replay: **0 network calls, 0 queries** (counter unchanged at 191 of 2,500). Shared metrics: `evret.metrics_cov` (merged from the corpus branch), budget **512 BGE tokens**, same anchored answers and claim set as the corpus report (**91 claims** with >= 1 anchored answer; **CovNovel defined for 88**). Raw numbers: `outputs/web_full_serper/cov_compare.{json,md}`, `lenient_compare.{json,md}`.

**Detectability.** With n = 180 claims (88-91 for the coverage metrics) differences below about 0.05 are not detectable; paired differences that are exactly 0 for most claims do not make an effect "absent". CIs are shown next to every number.

## 1. Web (main) vs corpus tool - "protocol-favoured corpus"
The corpus numbers were **re-run locally on CPU** (the corpus report stored only means), with the corpus tool's default variant (fact-check excluded, own article excluded). Reproduction check against the corpus report: CovNovel@512 dense 0.403 / BM25 0.313 / hybrid 0.376 (report: 0.403 / 0.313 / 0.377), CovUnion@512 0.467 / 0.400 / 0.448 (report: 0.468 / 0.400 / 0.448); the 0.001 differences are CPU fp32 vs GPU. Web = main condition, top-50 passages, claims without a kept page score 0 (primary).

| variant | metric | n | web | corpus dense | corpus BM25 | corpus hybrid |
|---|---|---|---|---|---|---|
| **primary: all claims** | CovNovel@512 | 88 | 0.273 [0.217, 0.333] | 0.403 [0.343, 0.464] | 0.313 [0.265, 0.365] | 0.376 [0.321, 0.436] |
| primary: all claims | CovUnion@512 | 91 | 0.334 [0.275, 0.395] | 0.467 [0.410, 0.526] | 0.400 [0.352, 0.451] | 0.448 [0.393, 0.504] |
| secondary: claims with >= 1 kept web page | CovNovel@512 | 72 | 0.334 [0.273, 0.399] | 0.410 [0.342, 0.479] | 0.323 [0.270, 0.379] | 0.371 [0.308, 0.436] |
| secondary | CovUnion@512 | 75 | 0.406 [0.345, 0.470] | 0.476 [0.412, 0.541] | 0.410 [0.360, 0.464] | 0.448 [0.388, 0.511] |

Paired difference web - corpus on identical claims (mean, percentile bootstrap 95% CI, 10,000 resamples, claim = unit; W/T/L = claims where web is better / equal / worse):

| variant | metric | n | vs dense | vs BM25 | vs hybrid |
|---|---|---|---|---|---|
| primary | CovNovel@512 | 88 | -0.129 [-0.188, -0.072] (19/13/56) | -0.040 [-0.100, +0.020] (33/10/45) | -0.103 [-0.164, -0.044] (26/9/53) |
| primary | CovUnion@512 | 91 | -0.133 [-0.188, -0.078] (20/12/59) | -0.066 [-0.125, -0.007] (33/9/49) | -0.114 [-0.170, -0.056] (25/9/57) |
| secondary | CovNovel@512 | 72 | -0.076 [-0.136, -0.018] (19/13/40) | +0.011 [-0.050, +0.074] (33/9/30) | -0.037 [-0.093, +0.019] (26/9/37) |
| secondary | CovUnion@512 | 75 | -0.070 [-0.123, -0.019] (20/12/43) | -0.004 [-0.060, +0.053] (33/9/33) | -0.042 [-0.095, +0.009] (25/9/41) |

Reading: on the primary variant the web run scores about 0.10-0.13 lower than dense and hybrid corpus retrieval (CIs exclude 0), and is not clearly different from BM25 on CovNovel (-0.04, CI includes 0). 16 of the 91 claims (18%) have no kept web page and score 0. On the secondary variant (claims with a web page) the gap to dense is -0.07 to -0.08, and web and BM25 are indistinguishable. **This table favours the corpus**, see the asymmetries.

**Limitations of this comparison (asymmetries).**
1. **Claim-date cutoff**: the web run applies it (Wayback snapshot at or before the claim date, or a page date <= claim date; 25% of the returned URLs were removed as dated after the claim, 2% as unknown), the corpus run does **not** (its dated-after documents are not removed; only 14.6% of corpus records have a URL date at all, D5). Removing information that postdates the claim lowers web coverage, so the web is penalised for correct protocol. Hence "protocol-favoured corpus".
2. The corpus is the annotators' own knowledge store (it contains the gold pages: 293 of 481 gold URLs are reachable there), the web run searches today's Google; only 28 of 481 gold entries are returned at all.
3. Anchored answers come from the corpus pages (the answer is "anchored" if it is found in the cited page as stored in the knowledge store), so the claim set itself is chosen from the corpus side.
4. Web: top-50 passages from at most 10 fetched pages; corpus: top-50 chunks of 6.4M. Different candidate pools, same 512-token budget.
5. n = 88-91, one engine day, one query form; CIs are wide.

## 2. Lenient condition (pre-registered in `docs/plans/web_lenient_plan.md`, committed before it was computed)
**What it changes: filters only** - pages with an unknown date are kept (flag `undated`); queries, search parameters, Wayback lookups, fetching and scoring are unchanged. Computed by replay: 0 queries, 0 network calls. **Self-check passed**: lenient equals main for all 180 claims except the URLs that main dropped as `date_unknown`; the 147 claims without such a URL have identical top-50 passages and scores.

Funnel of the URLs added back:

| step | count |
|---|---|
| `date_unknown` URLs in main (33 claims) | 38 |
| still removed (tiny / no text) | 11 |
| kept in lenient | 27 |
| chunked / with >= 1 passage in the top-50 | 27 / 27 |
| claims whose top-50 changed | 26 of 33 |
| top-50 passages from added pages | 545 of 4,093 (13%) |
| added passages in the top-5 | 69 (list: `outputs/web_full_serper/lenient_added_top5.md`) |
| gold: claims with a gold page in the top-50 / top-10 | main 11 / 10, lenient 11 / 10 (no change) |
| claims with a kept page | main 144, lenient 150 |

Paired per claim, lenient - main (same metrics, same claims, 10,000-resample bootstrap):

| variant | metric | n | main | lenient | lenient - main [95% CI] | W/T/L | claims with diff != 0 |
|---|---|---|---|---|---|---|---|
| primary: all claims | CovNovel@512 | 88 | 0.273 | 0.289 | +0.015 [-0.005, +0.042] | 5/79/4 | 9 |
| primary | CovUnion@512 | 91 | 0.334 | 0.351 | +0.017 [-0.004, +0.043] | 5/82/4 | 9 |
| secondary: claims with a kept page in lenient | CovNovel@512 | 75 | 0.321 | 0.339 | +0.018 [-0.006, +0.050] | 5/66/4 | 9 |
| secondary | CovUnion@512 | 78 | 0.390 | 0.410 | +0.020 [-0.005, +0.050] | 5/69/4 | 9 |

Reading: lenient moves the means by +0.015 to +0.020 and the CIs include 0; only 9 of 88-91 claims change at all (5 better, 4 worse). **This is below the detectable difference (~0.05), so the data neither show a gain nor rule out one of up to about 0.04.** Gold-page recall is unchanged.

**Why this is not a free improvement (leakage).** The added pages have no date at all, so they cannot be checked against the claim date. A heuristic check (not a classifier): 17 of the 27 added pages with passages in the top-50 contain a year between 2021 and 2029 in those passages, while every claim in the set is from 2020; examples are a UK "Weekly National Influenza & COVID-19 Report: week 10" PDF that supplies all five top passages for a claim from 2020-10-10 and mentions "week 9 2021", a House committee document with `20210913` in its URL, and a California voter guide under `/2026/`. Some of these years may be forecasts, but the pattern says lenient admits documents that postdate the claim. Lenient is therefore reported as a **recall ablation with unquantified temporal-leakage risk**, not as a candidate setting.

## 3. Fact-check condition
Not run. When it is run (after approval) it is a **leakage diagnostic**: a higher score would measure how much of the answer sits in fact-checkers' pages, not retrieval quality. The claim's own article stays excluded.

## 4. Housekeeping checks (done earlier this session)
- Gold matcher: `url_variants` normalises `www`, scheme, trailing slash, fragments and tracking parameters, sorts the remaining query parameters and unwraps Wayback links; a looser host+path key finds only 8 extra pairs, all different YouTube videos (false matches), so the 28 returned gold entries stand.
- 92 gold hosts vs 28 gold URLs: on 20 claims examined by eye, every host match without a URL match was a different page on the same site (another fact-check of the same site that was removed as own article, a different article on the same news site, a different YouTube video). No matcher bug.
- The 1,765 returned URLs reconcile with the outcome table (the missing one was an arithmetic slip: 18 other fetch failures, not 17; v3 report corrected).
