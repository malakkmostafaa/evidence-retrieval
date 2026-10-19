"""Paired bootstrap over claims. Ported unchanged from legacy_retrieval_v1/src/retrieval/stats.py
(the claim is the unit of analysis; passages of one claim are not independent)."""
from __future__ import annotations

import numpy as np


def paired_bootstrap(a, b, n_boot: int = 10000, seed: int = 42, alphas=(0.05, 0.05 / 3)) -> dict:
    """Mean of (a - b) with percentile CIs. alphas: 0.05 (95%) and 0.05/3 (Bonferroni for 3 confirmatory comparisons)."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    assert a.shape == b.shape
    d = a - b
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(d), size=(n_boot, len(d)))
    means = d[idx].mean(axis=1)
    res = {"n_claims": int(len(d)), "mean_diff": float(d.mean()), "sd_diff": float(d.std(ddof=1)) if len(d) > 1 else 0.0}
    for al in alphas:
        lo, hi = np.quantile(means, [al / 2, 1 - al / 2])
        res[f"ci{round((1 - al) * 100, 2)}"] = (float(lo), float(hi))
    res["wins"], res["ties"], res["losses"] = int((d > 0).sum()), int((d == 0).sum()), int((d < 0).sum())
    return res
