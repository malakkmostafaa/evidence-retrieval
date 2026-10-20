"""Oracle routing headroom between the web tool and the corpus tool (pre-registered in docs/plans/web_oracle_router_plan.md).

Per claim: oracle = max(web, corpus) of a coverage metric. It is an UPPER BOUND on what routing between the two sources could reach,
not a router (it sees both scores). Uses existing per-claim values only. usage:
  python -m evret.web.oracle_router --web outputs/web_full_serper [--corpus-rows corpus_rows.json] [--label normal]
"""
from __future__ import annotations

import argparse
import json
import os

import numpy as np

from evret.stats import paired_bootstrap
from evret.web.cov_compare import BUDGET, METRICS, ci_mean


def oracle(web: dict, corp: dict, retriever: str, metric: str, only_kept: bool = False) -> dict:
    """web: claim -> row (with has_kept_page); corp: claim -> {retriever: row}."""
    key = f"{metric}@B{BUDGET}"
    ids = [i for i in sorted(web) if (web[i]["has_kept_page"] or not only_kept)]
    w = np.array([web[i][key] for i in ids], float)
    c = np.array([corp[i][retriever][key] for i in ids], float)
    kept = np.array([web[i]["has_kept_page"] for i in ids])
    ok = ~np.isnan(w) & ~np.isnan(c)
    w, c, kept = w[ok], c[ok], kept[ok]
    o = np.maximum(w, c)
    best_name = "web" if w.mean() >= c.mean() else "corpus"
    best = w if best_name == "web" else c
    out = {"n": int(len(w)), "web": ci_mean(w), "corpus": ci_mean(c), "oracle": ci_mean(o), "best_single_source": best_name,
           "gain_over_best_single": paired_bootstrap(o, best) if len(w) > 1 else None,
           "web_wins": int((w > c).sum()), "corpus_wins": int((c > w).sum()), "ties": int((w == c).sum())}
    worse = c > w                                                       # claims where the corpus beats the web, split by cause
    out["corpus_wins_web_had_no_page"] = int((worse & ~kept).sum())
    out["corpus_wins_web_has_page_but_worse"] = int((worse & kept).sum())
    return out


def table(web, corp, retrievers=("dense", "bm25", "hybrid")) -> dict:
    return {v: {m: {r: oracle(web, corp, r, m, only_kept=(v == "claims_with_kept_web_page")) for r in retrievers} for m in METRICS}
            for v in ("all_claims", "claims_with_kept_web_page")}


def to_markdown(t, label) -> str:
    f = lambda x: f"{x[0]:.3f}"
    out = [f"Corpus = {label}.", "", "| variant | metric | corpus retriever | n | web | corpus | oracle (max) | best single | gain over best [95% CI] | web wins / corpus wins / ties | corpus wins: web had no page / web worse |",
           "|---|---|---|---|---|---|---|---|---|---|---|"]
    for v, ms in t.items():
        for m, rs in ms.items():
            for r, e in rs.items():
                g = e["gain_over_best_single"]
                gs = f"{g['mean_diff']:+.3f} [{g['ci95.0'][0]:+.3f}, {g['ci95.0'][1]:+.3f}]" if g else "-"
                out.append(f"| {v} | {m}@512 | {r} | {e['n']} | {f(e['web'])} | {f(e['corpus'])} | {f(e['oracle'])} | {e['best_single_source']} | {gs} | "
                           f"{e['web_wins']} / {e['corpus_wins']} / {e['ties']} | {e['corpus_wins_web_had_no_page']} / {e['corpus_wins_web_has_page_but_worse']} |")
    return "\n".join(out)


def main(argv=None):
    from evret import eval_pool as ep
    from evret.web.cov_compare import web_rows
    from evret.web.eval_web import CORPUS, DEV, load_results
    ap = argparse.ArgumentParser()
    ap.add_argument("--web", default="outputs/web_full_serper")
    ap.add_argument("--corpus-rows", default=None)
    ap.add_argument("--label", default="normal")
    a = ap.parse_args(argv)
    cfg = json.load(open(os.path.join(CORPUS, "manifest.json"), encoding="utf-8"))["config"]
    claims = ep.load_claims(DEV, os.path.join(CORPUS, "ranks.json"), cfg["band_size"], list(range(cfg["pool_bands"])))
    count, offs = ep.make_token_fns()
    anchored = ep.anchored_answers(CORPUS, claims)
    web = web_rows(load_results(a.web, replay=True), claims, anchored, count, offs)
    corp = {int(k): v for k, v in json.load(open(a.corpus_rows or os.path.join(a.web, "corpus_rows.json"))).items()}
    t = table(web, corp)
    json.dump(t, open(os.path.join(a.web, f"oracle_router_{a.label}.json"), "w"), indent=1)
    md = to_markdown(t, a.label)
    open(os.path.join(a.web, f"oracle_router_{a.label}.md"), "w", encoding="utf-8").write(md)
    print(md)


if __name__ == "__main__":
    main()
