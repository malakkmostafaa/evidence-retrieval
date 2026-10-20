"""Hand-computed oracle router numbers."""
import math

from evret.web.oracle_router import oracle, table, to_markdown


def wr(nov, uni, kept):
    return {"cov_novel@B512": nov, "cov_union@B512": uni, "has_kept_page": kept}


def cr(nov, uni):
    return {r: {"cov_novel@B512": nov, "cov_union@B512": uni} for r in ("dense", "bm25", "hybrid")}


WEB = {1: wr(0.8, 0.8, True), 2: wr(0.2, 0.2, True), 3: wr(0.0, 0.0, False), 4: wr(0.4, 0.4, True), 5: wr(0.5, 0.5, False)}
CORP = {1: cr(0.4, 0.4), 2: cr(0.6, 0.6), 3: cr(0.6, 0.6), 4: cr(0.4, 0.4), 5: cr(float("nan"), 0.5)}


def test_oracle_by_hand_all_claims():
    # CovNovel: claim 5 NaN on the corpus side -> dropped. web = .8 .2 0 .4 (mean .35), corpus = .4 .6 .6 .4 (mean .5)
    e = oracle(WEB, CORP, "dense", "cov_novel")
    assert e["n"] == 4 and abs(e["web"][0] - 0.35) < 1e-12 and abs(e["corpus"][0] - 0.5) < 1e-12
    # oracle = max per claim = .8 .6 .6 .4 -> mean .6 ; best single = corpus (0.5) ; gain = 0.1
    assert abs(e["oracle"][0] - 0.6) < 1e-12 and e["best_single_source"] == "corpus"
    assert abs(e["gain_over_best_single"]["mean_diff"] - 0.1) < 1e-12
    # wins: claim 1 web, claims 2 and 3 corpus, claim 4 tie
    assert (e["web_wins"], e["corpus_wins"], e["ties"]) == (1, 2, 1)
    # corpus wins: claim 2 (web has a page but worse), claim 3 (web had no page)
    assert (e["corpus_wins_web_had_no_page"], e["corpus_wins_web_has_page_but_worse"]) == (1, 1)


def test_oracle_on_claims_with_a_kept_web_page_only():
    e = oracle(WEB, CORP, "bm25", "cov_novel", only_kept=True)      # claims 1, 2, 4 (claim 5 kept=False, 3 kept=False)
    assert e["n"] == 3 and abs(e["web"][0] - (0.8 + 0.2 + 0.4) / 3) < 1e-12 and abs(e["corpus"][0] - (0.4 + 0.6 + 0.4) / 3) < 1e-12
    assert e["best_single_source"] == "web" or e["best_single_source"] == "corpus"
    assert abs(e["oracle"][0] - (0.8 + 0.6 + 0.4) / 3) < 1e-12
    assert e["corpus_wins_web_had_no_page"] == 0 and e["corpus_wins_web_has_page_but_worse"] == 1
    assert abs(e["gain_over_best_single"]["mean_diff"] - ((0.8 + 0.6 + 0.4) / 3 - max((0.8 + 0.2 + 0.4) / 3, (0.4 + 0.6 + 0.4) / 3))) < 1e-12


def test_oracle_is_never_below_the_best_single_source_and_union_uses_all_five_claims():
    t = table(WEB, CORP)
    for v in t.values():
        for m in v.values():
            for e in m.values():
                assert e["oracle"][0] >= max(e["web"][0], e["corpus"][0]) - 1e-12 and e["gain_over_best_single"]["mean_diff"] >= -1e-12
    assert t["all_claims"]["cov_union"]["dense"]["n"] == 5
    assert "oracle (max)" in to_markdown(t, "normal")
    assert not math.isnan(t["all_claims"]["cov_union"]["dense"]["oracle"][0])
