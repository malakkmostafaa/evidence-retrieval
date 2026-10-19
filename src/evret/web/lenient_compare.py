"""Lenient vs main (pre-registered in docs/plans/web_lenient_plan.md): paired per claim, same metrics, funnel of added-back URLs.

Both conditions are read from replay results (no network, no queries). usage:
  python -m evret.web.lenient_compare --web outputs/web_full_serper
"""
from __future__ import annotations

import argparse
import json
import os

import numpy as np

from evret.stats import paired_bootstrap
from evret.web.cov_compare import BUDGET, METRICS, ci_mean, web_rows
from evret.web.eval_web import CORPUS, DEV, load_results


def consistency(main, lenient) -> dict:
    """The pre-registered self-check: lenient == main except for URLs that main dropped as date_unknown."""
    bad_urls, same_top, changed = [], 0, 0
    for cid, m in main.items():
        l = lenient[cid]
        mu, lu = {u["url"]: u for u in m["urls"]}, {u["url"]: u for u in l["urls"]}
        if list(mu) != list(lu):
            bad_urls.append(cid)
            continue
        for url, u in mu.items():
            v = lu[url]
            if u["removed"] != "date_unknown" and u["removed"] != v["removed"]:
                bad_urls.append(cid)
        mh = [(h["url"], h["text"], h["score"]) for h in m["hits"]]
        lh = [(h["url"], h["text"], h["score"]) for h in l["hits"]]
        if any(u["removed"] == "date_unknown" for u in m["urls"]):
            changed += mh != lh
        else:
            same_top += mh == lh
            if mh != lh:
                bad_urls.append(cid)
    return {"claims": len(main), "inconsistent_claims": sorted(set(bad_urls)), "claims_without_added_pages_identical": same_top,
            "claims_with_date_unknown_main": sum(any(u["removed"] == "date_unknown" for u in m["urls"]) for m in main.values()),
            "of_those_top50_changed": changed}


def added_funnel(main, lenient) -> dict:
    f = {"date_unknown_in_main": 0, "still_removed_tiny_or_no_text": 0, "kept_in_lenient": 0, "chunked": 0, "with_passage_in_top50": 0,
         "claims_with_added_page": 0, "claims_with_added_page_in_top50": 0, "top50_passages_total_lenient": 0, "top50_passages_from_added": 0,
         "added_pages_gold": 0, "added_pages_in_top5_claims": 0}
    for cid, m in main.items():
        l = lenient[cid]
        added = [u["url"] for u in m["urls"] if u["removed"] == "date_unknown"]
        lu = {u["url"]: u for u in l["urls"]}
        f["date_unknown_in_main"] += len(added)
        f["claims_with_added_page"] += bool(added)
        in_top = set()
        for url in added:
            u = lu[url]
            if u["removed"] in ("tiny", "no_text"):
                f["still_removed_tiny_or_no_text"] += 1
            elif u["removed"] is None:
                f["kept_in_lenient"] += 1
                f["chunked"] += u["n_chunks"] > 0
                if any(h["url"] == url for h in l["hits"]):
                    f["with_passage_in_top50"] += 1
                    in_top.add(url)
                if any(h["url"] == url for h in l["hits"][:5]):
                    f["added_pages_in_top5_claims"] += 1
        f["claims_with_added_page_in_top50"] += bool(in_top)
        f["top50_passages_total_lenient"] += len(l["hits"])
        f["top50_passages_from_added"] += sum(h["url"] in set(added) for h in l["hits"])
    return f


def paired_table(main_rows, len_rows) -> dict:
    ids = sorted(main_rows)
    out = {"n_claims_all": len(ids), "n_claims_kept_main": int(sum(main_rows[i]["has_kept_page"] for i in ids)),
           "n_claims_kept_lenient": int(sum(len_rows[i]["has_kept_page"] for i in ids)), "variants": {}}
    for vname, sel in (("primary_all_claims", ids), ("secondary_claims_with_kept_page_in_lenient", [i for i in ids if len_rows[i]["has_kept_page"]])):
        v = {}
        for m in METRICS:
            key = f"{m}@B{BUDGET}"
            a = np.array([len_rows[i][key] for i in sel], float)
            b = np.array([main_rows[i][key] for i in sel], float)
            ok = ~np.isnan(a) & ~np.isnan(b)
            e = {"n": int(ok.sum()), "main": ci_mean(b[ok]) if ok.any() else None, "lenient": ci_mean(a[ok]) if ok.any() else None,
                 "claims_with_nonzero_diff": int((a[ok] != b[ok]).sum())}
            if ok.sum() > 1:
                e["lenient_minus_main"] = paired_bootstrap(a[ok], b[ok])
            v[m] = e
        out["variants"][vname] = v
    return out


def to_markdown(t) -> str:
    f = lambda x: f"{x[0]:.3f} [{x[1][0]:.3f}, {x[1][1]:.3f}]" if x else "-"
    out = ["| variant | metric | n | main | lenient | lenient - main (95% CI) | W/T/L | claims with diff != 0 |", "|---|---|---|---|---|---|---|---|"]
    for vn, v in t["variants"].items():
        for m, e in v.items():
            d = e.get("lenient_minus_main")
            ds = f"{d['mean_diff']:+.4f} [{d['ci95.0'][0]:+.4f}, {d['ci95.0'][1]:+.4f}]" if d else "-"
            wtl = f"{d['wins']}/{d['ties']}/{d['losses']}" if d else "-"
            out.append(f"| {vn} | {m}@512 | {e['n']} | {f(e['main'])} | {f(e['lenient'])} | {ds} | {wtl} | {e['claims_with_nonzero_diff']} |")
    return "\n".join(out)


def main(argv=None):
    from evret import eval_pool as ep
    from evret.web.cov_compare import web_rows as wr
    ap = argparse.ArgumentParser()
    ap.add_argument("--web", default="outputs/web_full_serper")
    a = ap.parse_args(argv)
    cfg = json.load(open(os.path.join(CORPUS, "manifest.json"), encoding="utf-8"))["config"]
    claims = ep.load_claims(DEV, os.path.join(CORPUS, "ranks.json"), cfg["band_size"], list(range(cfg["pool_bands"])))
    assert len(claims) == 180
    results = load_results(a.web, replay=True)
    main_r = {r["claim_id"]: r for r in results if r["cond"] == "main"}
    len_r = {r["claim_id"]: r for r in results if r["cond"] == "lenient"}
    assert len(main_r) == len(len_r) == 180
    count, offs = ep.make_token_fns()
    anchored = ep.anchored_answers(CORPUS, claims)
    res = {"consistency": consistency(main_r, len_r), "added_funnel": added_funnel(main_r, len_r),
           "paired": paired_table(wr(results, claims, anchored, count, offs, "main"), wr(results, claims, anchored, count, offs, "lenient"))}
    # descriptive gold numbers over all 180 claims
    res["gold"] = {c: {"claims_gold_in_top50": sum(bool(r["gold"]["in_top50"]) for r in rs.values()),
                       "claims_gold_in_top10": sum(bool(r["gold"]["in_top10"]) for r in rs.values()),
                       "claims_gold_in_kept": sum(bool(r["gold"]["in_kept"]) for r in rs.values()),
                       "claims_with_kept_page": sum(r["counts"]["kept"] > 0 for r in rs.values()),
                       "kept_pages": sum(r["counts"]["kept"] for r in rs.values())} for c, rs in (("main", main_r), ("lenient", len_r))}
    json.dump(res, open(os.path.join(a.web, "lenient_compare.json"), "w"), indent=1)
    md = to_markdown(res["paired"])
    open(os.path.join(a.web, "lenient_compare.md"), "w", encoding="utf-8").write(md)
    print(json.dumps({k: v for k, v in res.items() if k != "paired"}, indent=1))
    print(md)


if __name__ == "__main__":
    main()
