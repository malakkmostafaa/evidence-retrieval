"""Hand-computed checks of the web coverage scoring and the paired comparison (shared metrics: evret.metrics_cov)."""
import math

import numpy as np

from evret import metrics_cov as mc
from evret.web.cov_compare import BUDGET, compare, ci_mean, to_markdown, web_rows


def count(t):
    return len(t.split())


def offs(t):
    out, pos = [], 0
    for w in t.split():
        s = t.index(w, pos)
        out.append((s, s + len(w)))
        pos = s + len(w)
    return out


def ans(tokens):
    return {"tokens": frozenset(tokens), "scorable": True, "anchored": True}


CLAIMS = [
    {"claim_id": 1, "text": "alpha", "raw_gold_urls": ["https://g.example/1"]},
    {"claim_id": 2, "text": "alpha", "raw_gold_urls": []},
    {"claim_id": 3, "text": "alpha beta", "raw_gold_urls": []},
]
ANCHORED = {1: [ans(["alpha", "beta", "gamma", "delta"])], 2: [ans(["alpha", "beta", "gamma", "delta"])],
            3: [ans(["alpha", "beta", "gamma"])]}                       # claim 3: only 1 novel token -> CovNovel not defined
RESULTS = [
    {"cond": "main", "claim_id": 1, "hits": [{"url": "https://x.example/p", "text": "beta gamma zzz"}]},
    {"cond": "main", "claim_id": 2, "hits": []},                          # nothing kept
    {"cond": "main", "claim_id": 3, "hits": [{"url": "https://x.example/q", "text": "gamma zzz"}]},
]


def test_web_rows_by_hand_empty_claims_score_zero_and_undefined_novel_is_nan():
    rows = web_rows(RESULTS, CLAIMS, ANCHORED, count, offs)
    # claim 1: passage holds {beta, gamma} of the 4 answer tokens -> union 2/4; novel tokens {beta, gamma, delta} -> 2/3
    assert rows[1]["cov_union@B512"] == 0.5 and abs(rows[1]["cov_novel@B512"] - 2 / 3) < 1e-12 and rows[1]["has_kept_page"]
    assert rows[2]["cov_union@B512"] == 0.0 and rows[2]["cov_novel@B512"] == 0.0 and not rows[2]["has_kept_page"]
    # claim 3: union 1/3 ({gamma} of alpha,beta,gamma); novel = {gamma} only 1 < 3 tokens -> not defined
    assert abs(rows[3]["cov_union@B512"] - 1 / 3) < 1e-12 and math.isnan(rows[3]["cov_novel@B512"])


def test_budget_truncates_the_context_at_512_tokens():
    long_text = " ".join(["beta"] * 600)
    rows = web_rows([{"cond": "main", "claim_id": 1, "hits": [{"url": "https://x.example/p", "text": long_text}]}],
                    CLAIMS[:1], ANCHORED, count, offs)
    assert rows[1]["ctx_tokens@B512"] == BUDGET == 512


def test_primary_and_secondary_variants_and_paired_difference_by_hand():
    web = {1: {"cov_novel@B512": 0.5, "cov_union@B512": 0.5, "has_kept_page": True},
           2: {"cov_novel@B512": 0.0, "cov_union@B512": 0.0, "has_kept_page": False},
           3: {"cov_novel@B512": float("nan"), "cov_union@B512": 0.25, "has_kept_page": True}}
    corp = {i: {r: {"cov_novel@B512": v, "cov_union@B512": u} for r in ("dense", "bm25", "hybrid")}
            for i, (v, u) in {1: (0.25, 0.5), 2: (0.5, 0.75), 3: (0.1, 0.5)}.items()}
    res = compare(web, corp)
    p, s = res["variants"]["primary_all_claims"], res["variants"]["secondary_claims_with_kept_page"]
    assert res["n_claims_all"] == 3 and res["n_claims_with_kept_page"] == 2
    # CovNovel primary: claims 1, 2 (3 is NaN): web mean 0.25, corpus mean 0.375, diffs +0.25, -0.5 -> mean -0.125
    assert p["cov_novel"]["n"] == 2 and abs(p["cov_novel"]["web"][0] - 0.25) < 1e-12
    assert abs(p["cov_novel"]["corpus"]["dense"][0] - 0.375) < 1e-12
    d = p["cov_novel"]["paired_web_minus_corpus"]["dense"]
    assert abs(d["mean_diff"] + 0.125) < 1e-12 and (d["wins"], d["ties"], d["losses"]) == (1, 0, 1)
    # CovUnion primary: all 3 claims: web (0.5+0+0.25)/3 = 0.25, corpus (0.5+0.75+0.5)/3
    assert p["cov_union"]["n"] == 3 and abs(p["cov_union"]["web"][0] - 0.25) < 1e-12
    assert abs(p["cov_union"]["corpus"]["bm25"][0] - (1.75 / 3)) < 1e-12
    # secondary: only claims 1 and 3 (claim 2 had no kept page): CovUnion web (0.5+0.25)/2, corpus (0.5+0.5)/2
    assert s["cov_union"]["n"] == 2 and abs(s["cov_union"]["web"][0] - 0.375) < 1e-12 and abs(s["cov_union"]["corpus"]["hybrid"][0] - 0.5) < 1e-12
    assert s["cov_novel"]["n"] == 1                                         # claim 3 has no defined CovNovel
    assert "primary_all_claims" in to_markdown(res)


def test_ci_mean_is_deterministic_and_brackets_the_mean():
    m, ci, n = ci_mean([0.0, 1.0, 0.0, 1.0])
    assert m == 0.5 and n == 4 and ci[0] <= 0.5 <= ci[1] and ci_mean([0.0, 1.0, 0.0, 1.0]) == (m, ci, n)
