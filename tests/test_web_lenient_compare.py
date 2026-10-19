"""Hand-built main/lenient results: consistency self-check, funnel of added-back URLs, paired table."""
import numpy as np

from evret.web.lenient_compare import added_funnel, consistency, paired_table


def U(url, removed=None, n_chunks=0):
    return {"url": url, "removed": removed, "n_chunks": n_chunks}


def H(url, text="t", score=1.0):
    return {"url": url, "text": text, "score": score}


MAIN = {
    1: {"urls": [U("a", "date_unknown"), U("b", None, 1)], "hits": [H("b")]},
    2: {"urls": [U("c", None, 1), U("d", "dated_after")], "hits": [H("c")]},
    3: {"urls": [U("e", "date_unknown")], "hits": []},
}
LEN = {
    1: {"urls": [U("a", None, 2), U("b", None, 1)], "hits": [H("a"), H("b")]},
    2: {"urls": [U("c", None, 1), U("d", "dated_after")], "hits": [H("c")]},
    3: {"urls": [U("e", "tiny")], "hits": []},
}


def test_consistency_accepts_exactly_the_planned_difference_and_flags_anything_else():
    c = consistency(MAIN, LEN)
    assert c["inconsistent_claims"] == [] and c["claims_with_date_unknown_main"] == 2
    assert c["claims_without_added_pages_identical"] == 1 and c["of_those_top50_changed"] == 1
    bad = {**LEN, 2: {"urls": [U("c", None, 1), U("d", None, 1)], "hits": [H("c")]}}          # a dated_after page slipped back in
    assert consistency(MAIN, bad)["inconsistent_claims"] == [2]
    bad2 = {**LEN, 2: {"urls": LEN[2]["urls"], "hits": [H("c", score=0.5)]}}                  # claim without added page changed its scores
    assert consistency(MAIN, bad2)["inconsistent_claims"] == [2]


def test_added_funnel_counts_by_hand():
    f = added_funnel(MAIN, LEN)
    assert f["date_unknown_in_main"] == 2 and f["still_removed_tiny_or_no_text"] == 1 and f["kept_in_lenient"] == 1
    assert f["chunked"] == 1 and f["with_passage_in_top50"] == 1 and f["claims_with_added_page"] == 2
    assert f["claims_with_added_page_in_top50"] == 1 and f["top50_passages_total_lenient"] == 3 and f["top50_passages_from_added"] == 1
    assert f["added_pages_in_top5_claims"] == 1


def row(nov, uni, kept):
    return {"cov_novel@B512": nov, "cov_union@B512": uni, "has_kept_page": kept}


def test_paired_table_by_hand():
    main = {1: row(0.25, 0.5, True), 2: row(0.5, 0.5, True), 3: row(0.0, 0.0, False)}
    lenient = {1: row(0.5, 0.75, True), 2: row(0.5, 0.5, True), 3: row(0.0, 0.0, False)}
    t = paired_table(main, lenient)
    p = t["variants"]["primary_all_claims"]["cov_novel"]
    assert p["n"] == 3 and abs(p["lenient_minus_main"]["mean_diff"] - 0.25 / 3) < 1e-12 and p["claims_with_nonzero_diff"] == 1
    assert (p["lenient_minus_main"]["wins"], p["lenient_minus_main"]["ties"], p["lenient_minus_main"]["losses"]) == (1, 2, 0)
    s = t["variants"]["secondary_claims_with_kept_page_in_lenient"]["cov_union"]
    assert s["n"] == 2 and abs(s["lenient_minus_main"]["mean_diff"] - 0.125) < 1e-12           # claim 3 has no kept page: excluded
    assert t["n_claims_kept_main"] == 2 and t["n_claims_kept_lenient"] == 2
    nan = {**lenient, 2: row(float("nan"), 0.5, True)}
    assert paired_table(main, nan)["variants"]["primary_all_claims"]["cov_novel"]["n"] == 2   # undefined CovNovel drops out of both sides


def test_a_url_that_is_not_relaxed_is_not_counted_as_kept_and_nan_on_either_side_drops_out():
    main = {**MAIN, 4: {"urls": [U("f", "date_unknown")], "hits": []}}
    lenient = {**LEN, 4: {"urls": [U("f", "date_unknown")], "hits": []}}                         # filter not relaxed
    f = added_funnel(main, lenient)
    assert f["date_unknown_in_main"] == 3 and f["kept_in_lenient"] == 1
    m = {1: row(float("nan"), 0.5, True), 2: row(0.5, 0.5, True)}
    l = {1: row(0.5, 0.5, True), 2: row(0.5, 0.5, True)}
    assert paired_table(m, l)["variants"]["primary_all_claims"]["cov_novel"]["n"] == 1
