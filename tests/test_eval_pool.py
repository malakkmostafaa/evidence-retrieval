"""Evaluation layer: SourceHit by hand, Wayback-aware gold matching, exclusion sets."""
import json

from evret import eval_pool as ev
from evret.urls import url_variants

GOLD = [url_variants("https://a.com/x"), url_variants("https://web.archive.org/web/20200101000000/https://b.com/y"),
        url_variants("https://c.com/z")]


def test_source_hit_hand_computed():
    hits = ["https://other.com/1", "http://www.a.com/x/", "https://b.com/y", "https://other.com/2"]
    assert ev.source_hit(hits, GOLD, 1) == (False, 0.0)
    assert ev.source_hit(hits, GOLD, 2) == (True, 1 / 3)                  # a.com/x found (www, trailing slash ignored)
    a, r = ev.source_hit(hits, GOLD, 3)
    assert a and abs(r - 2 / 3) < 1e-12                                    # b.com/y found although gold is a Wayback URL
    assert ev.source_hit(hits, GOLD, 50) == (True, 2 / 3)                  # c.com/z never retrieved
    assert ev.source_hit(hits, [], 10) == (False, 0.0)
    # the stored URL may itself be the wrapper
    assert ev.source_hit(["https://web.archive.org/web/2019/https://c.com/z"], GOLD, 1) == (True, 1 / 3)


def test_load_claims_builds_exclusions_and_filters_by_band(tmp_path):
    dev = [
        {"claim": "c0", "label": "Refuted", "claim_date": "", "questions": [{"answers": [{"source_url": "https://g.com/1"}]}],
         "fact_checking_article": "https://web.archive.org/web/20201130144023/https://fc.com/a/", "original_claim_url": None,
         "cached_original_claim_url": "https://web.archive.org/web/2020/https://orig.com/p"},
        {"claim": "c1", "label": "Supported", "claim_date": "", "questions": [], "fact_checking_article": "",
         "original_claim_url": "https://orig2.com/q"},
    ]
    json.dump(dev, open(tmp_path / "dev.json", "w"))
    json.dump({"0": 0, "1": 31}, open(tmp_path / "ranks.json", "w"))
    cl = ev.load_claims(str(tmp_path / "dev.json"), str(tmp_path / "ranks.json"), 30, [0])
    assert [c["claim_id"] for c in cl] == [0]                              # claim 1 is in band 1, not finished
    c = cl[0]
    assert {"fc.com/a", "orig.com/p"} <= c["exclude"]
    assert "web.archive.org/web/20201130144023/https://fc.com/a" in c["exclude"]
    assert c["gold_variants"] == [{"g.com/1"}]
    cl = ev.load_claims(str(tmp_path / "dev.json"), str(tmp_path / "ranks.json"), 30, [0, 1])
    assert cl[1]["exclude"] == {"orig2.com/q"}
