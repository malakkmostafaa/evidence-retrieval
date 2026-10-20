Corpus = normal.

| variant | metric | corpus retriever | n | web | corpus | oracle (max) | best single | gain over best [95% CI] | web wins / corpus wins / ties | corpus wins: web had no page / web worse |
|---|---|---|---|---|---|---|---|---|---|---|
| all_claims | cov_novel@512 | dense | 88 | 0.273 | 0.403 | 0.443 | corpus | +0.041 [+0.021, +0.064] | 19 / 56 / 13 | 16 / 40 |
| all_claims | cov_novel@512 | bm25 | 88 | 0.273 | 0.313 | 0.395 | corpus | +0.082 [+0.052, +0.116] | 33 / 45 / 10 | 15 / 30 |
| all_claims | cov_novel@512 | hybrid | 88 | 0.273 | 0.376 | 0.428 | corpus | +0.052 [+0.030, +0.077] | 26 / 53 / 9 | 16 / 37 |
| all_claims | cov_union@512 | dense | 91 | 0.334 | 0.467 | 0.504 | corpus | +0.037 [+0.019, +0.058] | 20 / 59 / 12 | 16 / 43 |
| all_claims | cov_union@512 | bm25 | 91 | 0.334 | 0.400 | 0.471 | corpus | +0.070 [+0.044, +0.099] | 33 / 49 / 9 | 16 / 33 |
| all_claims | cov_union@512 | hybrid | 91 | 0.334 | 0.448 | 0.495 | corpus | +0.047 [+0.028, +0.069] | 25 / 57 / 9 | 16 / 41 |
| claims_with_kept_web_page | cov_novel@512 | dense | 72 | 0.334 | 0.410 | 0.460 | corpus | +0.050 [+0.026, +0.078] | 19 / 40 / 13 | 0 / 40 |
| claims_with_kept_web_page | cov_novel@512 | bm25 | 72 | 0.334 | 0.323 | 0.423 | web | +0.089 [+0.053, +0.128] | 33 / 30 / 9 | 0 / 30 |
| claims_with_kept_web_page | cov_novel@512 | hybrid | 72 | 0.334 | 0.371 | 0.434 | corpus | +0.063 [+0.038, +0.092] | 26 / 37 / 9 | 0 / 37 |
| claims_with_kept_web_page | cov_union@512 | dense | 75 | 0.406 | 0.476 | 0.520 | corpus | +0.045 [+0.024, +0.070] | 20 / 43 / 12 | 0 / 43 |
| claims_with_kept_web_page | cov_union@512 | bm25 | 75 | 0.406 | 0.410 | 0.495 | corpus | +0.085 [+0.055, +0.120] | 33 / 33 / 9 | 0 / 33 |
| claims_with_kept_web_page | cov_union@512 | hybrid | 75 | 0.406 | 0.448 | 0.505 | corpus | +0.057 [+0.034, +0.083] | 25 / 41 / 9 | 0 / 41 |