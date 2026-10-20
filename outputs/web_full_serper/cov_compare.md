| variant | metric | n | web | corpus dense | corpus BM25 | corpus hybrid |
|---|---|---|---|---|---|---|
| primary_all_claims | cov_novel@512 | 88 | 0.273 [0.217, 0.333] | 0.403 [0.343, 0.464] | 0.313 [0.265, 0.365] | 0.376 [0.321, 0.436] |
| primary_all_claims | cov_union@512 | 91 | 0.334 [0.275, 0.395] | 0.467 [0.410, 0.526] | 0.400 [0.352, 0.451] | 0.448 [0.393, 0.504] |
| secondary_claims_with_kept_page | cov_novel@512 | 72 | 0.334 [0.273, 0.399] | 0.410 [0.342, 0.479] | 0.323 [0.270, 0.379] | 0.371 [0.308, 0.436] |
| secondary_claims_with_kept_page | cov_union@512 | 75 | 0.406 [0.345, 0.470] | 0.476 [0.412, 0.541] | 0.410 [0.360, 0.464] | 0.448 [0.388, 0.511] |

Paired difference web - corpus (mean over identical claims, percentile bootstrap 95% CI, 10,000 resamples, claim = unit):

| variant | metric | n | vs dense | vs BM25 | vs hybrid |
|---|---|---|---|---|---|
| primary_all_claims | cov_novel@512 | 88 | -0.129 [-0.188, -0.072] (W/T/L 19/13/56) | -0.040 [-0.100, +0.020] (W/T/L 33/10/45) | -0.103 [-0.164, -0.044] (W/T/L 26/9/53) |
| primary_all_claims | cov_union@512 | 91 | -0.133 [-0.188, -0.078] (W/T/L 20/12/59) | -0.066 [-0.125, -0.007] (W/T/L 33/9/49) | -0.114 [-0.170, -0.056] (W/T/L 25/9/57) |
| secondary_claims_with_kept_page | cov_novel@512 | 72 | -0.076 [-0.136, -0.018] (W/T/L 19/13/40) | +0.011 [-0.050, +0.074] (W/T/L 33/9/30) | -0.037 [-0.093, +0.019] (W/T/L 26/9/37) |
| secondary_claims_with_kept_page | cov_union@512 | 75 | -0.070 [-0.123, -0.019] (W/T/L 20/12/43) | -0.004 [-0.060, +0.053] (W/T/L 33/9/33) | -0.042 [-0.095, +0.009] (W/T/L 25/9/41) |