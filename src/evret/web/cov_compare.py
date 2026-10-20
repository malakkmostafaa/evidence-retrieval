"""Answer-coverage scoring of the web pool run and the paired comparison with the corpus tool (shared metrics: evret.metrics_cov).

No web queries and no network calls: the web side is read from the REPLAY results (results_replay.jsonl, produced from the frozen
cache). The corpus side is re-run locally (CPU, same code as evret.eval_pool) because the corpus report stored only means, not per-claim
values. Same claim set (claims with >= 1 anchored gold answer: 91; CovNovel defined for 88), same budget (512 BGE tokens, no special
tokens), same anchored answers (evret.eval_pool.anchored_answers on the corpus), same retrievers/filters as the corpus report
(default variant: fact-check excluded, own article excluded).

usage: python -m evret.web.cov_compare --web outputs/web_full_serper --out outputs/web_full_serper
"""
from __future__ import annotations

import argparse
import json
import os
from types import SimpleNamespace

import numpy as np

from evret import metrics_cov as mc
from evret.stats import paired_bootstrap
from evret.web.eval_web import CORPUS, DEV, load_results

BUDGET = 512
METRICS = ("cov_novel", "cov_union")


def web_rows(results, claims, anchored, count, offs, cond="main"):
    """claim_id -> row of legacy metrics for the web top-50 passages (empty list when no page was kept)."""
    by = {r["claim_id"]: r for r in results if r["cond"] == cond}
    rows = {}
    for c in claims:
        ans = anchored[c["claim_id"]]
        if not ans:
            continue
        r = by[c["claim_id"]]
        ranked = [mc.passage_from_hit(SimpleNamespace(url=h["url"], text=h["text"]), count) for h in r["hits"][:50]]
        row = mc.claim_row(ans, mc.gold_keys(c["raw_gold_urls"]), ranked, BUDGET, (5, 10), offs,
                           claim_tokens=frozenset(mc.content_tokens(c["text"])))
        row["has_kept_page"] = bool(r["hits"])
        rows[c["claim_id"]] = row
    return rows


def corpus_rows(claims, anchored, corpus_root, bands, count, offs, log=print):
    """claim_id -> {retriever: row} using the corpus tool exactly as the corpus report does (default variant)."""
    import torch

    from evret import bm25 as bm
    from evret import embed as em
    from evret import search as sr
    corpus = sr.Corpus(corpus_root, bands)
    enc = em.Encoder(dtype="fp32", device="cpu")
    dense = sr.DenseExact(corpus, em.load_vectors(corpus_root, bands), enc, device="cpu")
    sparse = sr.BM25(corpus, bm.BM25Index([os.path.join(corpus_root, "bm25", f"band={b}") for b in bands]))
    rets = {"dense": dense, "bm25": sparse, "hybrid": sr.Hybrid(dense, sparse)}
    elig = [c for c in claims if anchored[c["claim_id"]]]
    flags = frozenset({"factcheck", "tiny"})
    out = {c["claim_id"]: {} for c in elig}
    torch.set_num_threads(3)
    for name, ret in rets.items():
        for i in range(0, len(elig), 15):
            chunk = elig[i:i + 15]
            hits = ret.search_batch([c["text"] for c in chunk], 50, [sr.Filters(exclude_norm_urls=c["exclude"], exclude_flags=flags) for c in chunk])
            for c, h in zip(chunk, hits):
                ranked = [mc.passage_from_hit(x, count) for x in h]
                out[c["claim_id"]][name] = mc.claim_row(anchored[c["claim_id"]], mc.gold_keys(c["raw_gold_urls"]), ranked, BUDGET, (5, 10),
                                                        offs, claim_tokens=frozenset(mc.content_tokens(c["text"])))
            log(f"  corpus {name}: {min(i + 15, len(elig))}/{len(elig)} claims")
    return out


def ci_mean(x, n_boot=10000, seed=42):
    x = np.asarray(x, float)
    x = x[~np.isnan(x)]
    idx = np.random.default_rng(seed).integers(0, len(x), size=(n_boot, len(x)))
    m = x[idx].mean(1)
    return float(x.mean()), [float(np.quantile(m, 0.025)), float(np.quantile(m, 0.975))], int(len(x))


def compare(web, corp, retrievers=("dense", "bm25", "hybrid")):
    """Paired tables. Primary: all eligible claims (no kept page = 0). Secondary: only claims with >= 1 kept page."""
    ids = sorted(web)
    out = {"n_claims_all": len(ids), "n_claims_with_kept_page": int(sum(web[i]["has_kept_page"] for i in ids)), "variants": {}}
    for vname, sel in (("primary_all_claims", ids), ("secondary_claims_with_kept_page", [i for i in ids if web[i]["has_kept_page"]])):
        v = {}
        for m in METRICS:
            key = f"{m}@B{BUDGET}"
            w = np.array([web[i][key] for i in sel], float)
            ok = ~np.isnan(w)
            entry = {"n": int(ok.sum()), "web": ci_mean(w[ok]) if ok.any() else None, "corpus": {}, "paired_web_minus_corpus": {}}
            for r in retrievers:
                cv = np.array([corp[i][r][key] for i in sel], float)
                ok2 = ok & ~np.isnan(cv)
                entry["corpus"][r] = ci_mean(cv[ok2]) if ok2.any() else None
                if ok2.sum() > 1:
                    entry["paired_web_minus_corpus"][r] = paired_bootstrap(w[ok2], cv[ok2])
            v[m] = entry
        out["variants"][vname] = v
    return out


def to_markdown(res) -> str:
    f = lambda t: f"{t[0]:.3f} [{t[1][0]:.3f}, {t[1][1]:.3f}]" if t else "-"
    out = ["| variant | metric | n | web | corpus dense | corpus BM25 | corpus hybrid |", "|---|---|---|---|---|---|---|"]
    for vn, v in res["variants"].items():
        for m, e in v.items():
            out.append(f"| {vn} | {m}@512 | {e['n']} | {f(e['web'])} | " + " | ".join(f(e["corpus"].get(r)) for r in ("dense", "bm25", "hybrid")) + " |")
    out += ["", "Paired difference web - corpus (mean over identical claims, percentile bootstrap 95% CI, 10,000 resamples, claim = unit):", "",
            "| variant | metric | n | vs dense | vs BM25 | vs hybrid |", "|---|---|---|---|---|---|"]
    g = lambda d: f"{d['mean_diff']:+.3f} [{d['ci95.0'][0]:+.3f}, {d['ci95.0'][1]:+.3f}] (W/T/L {d['wins']}/{d['ties']}/{d['losses']})" if d else "-"
    for vn, v in res["variants"].items():
        for m, e in v.items():
            out.append(f"| {vn} | {m}@512 | {e['n']} | " + " | ".join(g(e["paired_web_minus_corpus"].get(r)) for r in ("dense", "bm25", "hybrid")) + " |")
    return "\n".join(out)


def main(argv=None):
    from evret import eval_pool as ep
    ap = argparse.ArgumentParser()
    ap.add_argument("--web", default="outputs/web_full_serper")
    ap.add_argument("--out", default="outputs/web_full_serper")
    a = ap.parse_args(argv)
    cfg = json.load(open(os.path.join(CORPUS, "manifest.json"), encoding="utf-8"))["config"]
    bands = list(range(cfg["pool_bands"]))
    claims = ep.load_claims(DEV, os.path.join(CORPUS, "ranks.json"), cfg["band_size"], bands)
    assert len(claims) == 180 and max(c["rank"] for c in claims) < 180
    count, offs = ep.make_token_fns()
    print("anchoring gold answers on the corpus pages ...", flush=True)
    anchored = ep.anchored_answers(CORPUS, claims)
    n_elig = sum(bool(v) for v in anchored.values())
    print("claims with >= 1 anchored answer:", n_elig, flush=True)
    results = load_results(a.web, replay=True)
    web = web_rows(results, claims, anchored, count, offs)
    cache = os.path.join(a.out, "corpus_rows.json")
    if os.path.exists(cache):
        corp = {int(k): v for k, v in json.load(open(cache)).items()}
    else:
        corp = corpus_rows(claims, anchored, CORPUS, bands, count, offs, log=lambda s: print(s, flush=True))
        json.dump(corp, open(cache, "w"))
    res = compare(web, corp)
    res["claims_with_defined_cov_novel"] = int(sum(not np.isnan(web[i][f"cov_novel@B{BUDGET}"]) for i in web))
    json.dump(res, open(os.path.join(a.out, "cov_compare.json"), "w"), indent=1)
    md = to_markdown(res)
    open(os.path.join(a.out, "cov_compare.md"), "w", encoding="utf-8").write(md)
    print(md)


if __name__ == "__main__":
    main()
