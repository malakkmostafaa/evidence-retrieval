"""Own-store removal evaluation (pre-registered in docs/reports/own_store_removal_prereg.md). EVALUATION ONLY: it reads
the private provenance table (origins.parquet) and hands the retrievers nothing but a per-query list of document ids to
exclude. Same claims, retrievers, filters and metrics as the v1 report (evret.eval_pool)."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time

import numpy as np
import pyarrow.parquet as pq

from evret import eval_pool as ev

METRICS_SRC = [("SourceHit@10", "any", 10), ("SourceHit@50", "any", 50), ("GoldRecall@10", "recall", 10),
               ("GoldRecall@50", "recall", 50)]


def provenance(root: str, claim_ids: list[int], pool_claims: set[int], n_pool_docs: int):
    """-> (own[c] = pool doc ids in c's store, exclusive[c] = those that appear in no other POOL store)."""
    o = pq.read_table(os.path.join(root, "origins.parquet"), columns=["doc_id", "claim_id"])
    d = o.column("doc_id").to_numpy().astype(np.int64)
    c = o.column("claim_id").to_numpy().astype(np.int64)
    pair = np.unique(d * 1000 + c)
    dd, cl = pair // 1000, pair % 1000
    in_pool_store = np.isin(cl, list(pool_claims))
    n_pool_stores = np.bincount(dd[in_pool_store], minlength=n_pool_docs + 1)
    own, excl = {}, {}
    for cid in claim_ids:
        docs = dd[(cl == cid) & (dd < n_pool_docs)]
        own[cid] = frozenset(int(x) for x in docs)
        excl[cid] = frozenset(int(x) for x in docs[n_pool_stores[docs] == 1])
    return own, excl


def per_claim_metrics(claims, hits, reach_mask, anchored):
    """metric -> array over the reachable claims (source metrics) or (claim ids, array) for the coverage metrics."""
    out = {}
    for name, key, k in METRICS_SRC:
        sel = 0 if key == "any" else 1
        out[name] = np.array([ev.source_hit([x.url for x in h], c["gold_variants"], k)[sel]
                              for c, h in zip(claims, hits)], float)[reach_mask]
    cov = ev.coverage(claims, hits, anchored)
    B = ev.COV_BUDGET
    ids = cov["claim_ids"]
    for name in (f"cov_novel@B{B}", f"cov_union@B{B}", "answer_recall@10"):
        out[name] = (ids, cov[name])
    return out


def main(argv=None):
    import torch
    from evret import bm25 as bm
    from evret import embed as em
    from evret import search as sr
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--dev", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    root = a.corpus
    t_start, started = time.time(), time.strftime("%Y-%m-%d %H:%M:%S")
    ing = json.load(open(os.path.join(root, "manifest.json"), encoding="utf-8"))
    bands = list(range(ing["config"]["pool_bands"]))
    claims = ev.load_claims(a.dev, os.path.join(root, "ranks.json"), ing["config"]["band_size"], bands)
    corpus = sr.Corpus(root, bands)
    enc = em.Encoder(dtype="fp32", device="cuda" if torch.cuda.is_available() else "cpu")
    dense = sr.DenseExact(corpus, em.load_vectors(root, bands), enc)
    index = bm.BM25Index([os.path.join(root, "bm25", f"band={b}") for b in bands])
    bm_frozen, bm_exact = sr.BM25(corpus, index, False), sr.BM25(corpus, index, True)
    hy_frozen, hy_exact = sr.Hybrid(dense, bm_frozen), sr.Hybrid(dense, bm_exact)

    pool_claims = {c for c, r in ((int(k), v) for k, v in
                                  json.load(open(os.path.join(root, "ranks.json"))).items()) if r < 180}
    own, excl = provenance(root, [c["claim_id"] for c in claims], pool_claims, ing["counts"]["documents_pool"])
    reach = np.array([any(r) for r in (ev.reachable_flags(corpus, c) for c in claims)])
    anchored = ev.anchored_answers(root, claims)
    texts = [c["text"] for c in claims]
    queries_filters = {
        "normal": [sr.Filters(exclude_norm_urls=c["exclude"]) for c in claims],
        "primary": [sr.Filters(exclude_norm_urls=c["exclude"], exclude_doc_ids=own[c["claim_id"]]) for c in claims],
        "secondary": [sr.Filters(exclude_norm_urls=c["exclude"], exclude_doc_ids=excl[c["claim_id"]]) for c in claims],
    }
    # (label, variant, retriever object)
    runs = [("normal", "normal", {"dense": dense, "bm25": bm_frozen, "hybrid": hy_frozen}),
            ("primary", "primary", {"dense": dense, "bm25": bm_exact, "hybrid": hy_exact}),
            ("primary_frozen_stats", "primary", {"bm25": bm_frozen, "hybrid": hy_frozen}),
            ("secondary", "secondary", {"dense": dense, "bm25": bm_exact, "hybrid": hy_exact})]
    res = {"n_claims": len(claims), "n_reachable_claims": int(reach.sum()),
           "removed_per_claim": {}, "runs": {}, "paired_vs_normal": {}, "checks": {}}
    for v, fs in (("primary", [own[c["claim_id"]] for c in claims]), ("secondary", [excl[c["claim_id"]] for c in claims])):
        nd = np.array([len(x) for x in fs])
        res["removed_per_claim"][v] = {"docs_mean": round(float(nd.mean()), 1), "docs_min": int(nd.min()),
                                       "docs_max": int(nd.max())}
    # chunks removed per claim (exact, from the chunk table)
    for v in ("primary", "secondary"):
        ch = [sum(b - a_ for a_, b in corpus.excluded_ranges(f)) for f in queries_filters[v]]
        res["removed_per_claim"][v]["chunks_mean"] = round(float(np.mean(ch)), 1)
        res["removed_per_claim"][v]["share_of_pool_chunks_mean"] = round(float(np.mean(ch)) / corpus.n, 5)
    store, leak = {}, {"removed_doc_returned": 0, "own_article_returned": 0, "hits_checked": 0}
    for label, v, rets in runs:
        for rname, r in rets.items():
            t0 = time.time()
            hits = r.search_batch(texts, 50, queries_filters[v])
            dt = time.time() - t0
            store[(label, rname)] = per_claim_metrics(claims, hits, reach, anchored)
            for c, h in zip(claims, hits):
                removed = own[c["claim_id"]] if v == "primary" else (excl[c["claim_id"]] if v == "secondary" else frozenset())
                for x in h:
                    leak["hits_checked"] += 1
                    leak["removed_doc_returned"] += x.doc_id in removed
                    leak["own_article_returned"] += ev.hit_matches(x.url, set(c["exclude"]))
            print(label, rname, f"{dt:.0f}s", flush=True)
    res["checks"]["leakage"] = leak

    def mean_of(m):
        return float(np.mean(m[1])) if isinstance(m, tuple) else float(np.mean(m))
    for label, _, rets in runs:
        res["runs"][label] = {r: {k: round(mean_of(m), 4) for k, m in store[(label, r)].items()} for r in rets}
    # paired differences against the normal run, same claims
    for label in ("primary", "primary_frozen_stats", "secondary"):
        res["paired_vs_normal"][label] = {}
        for rname in {r for (l, r) in store if l == label}:
            res["paired_vs_normal"][label][rname] = {}
            for metric, m_new in store[(label, rname)].items():
                m_old = store[("normal", rname)][metric]
                if isinstance(m_new, tuple):
                    ids_n, ids_o = m_new[0], m_old[0]
                    keep = [i for i, x in enumerate(ids_n) if x in set(ids_o)]
                    new = np.array([m_new[1][i] for i in keep])
                    old = np.array([m_old[1][list(ids_o).index(ids_n[i])] for i in keep])
                    ok = ~(np.isnan(new) | np.isnan(old))
                    new, old = new[ok], old[ok]
                else:
                    new, old = m_new, m_old
                b = ev.bootstrap({"removed": new, "normal": old}, ["removed", "normal"])
                d = b["paired_diff"]["removed - normal"]
                res["paired_vs_normal"][label][rname][metric] = {
                    "n": int(len(new)), "normal": b["mean"]["normal"], "removed": b["mean"]["removed"],
                    "diff": d["mean"], "ci95": d["ci95"], "excludes_zero": d["excludes_zero"]}
    # frozen vs recomputed BM25 statistics (primary variant)
    cmp = {}
    for rname in ("bm25", "hybrid"):
        for metric, m_e in store[("primary", rname)].items():
            m_f = store[("primary_frozen_stats", rname)][metric]
            e = m_e[1] if isinstance(m_e, tuple) else m_e
            f = m_f[1] if isinstance(m_f, tuple) else m_f
            cmp[f"{rname} | {metric}"] = {"recomputed": round(float(np.nanmean(e)), 4), "frozen": round(float(np.nanmean(f)), 4),
                                         "max_abs_per_claim_diff": round(float(np.nanmax(np.abs(np.asarray(e) - np.asarray(f)))), 4)}
    res["checks"]["frozen_vs_recomputed_bm25_primary"] = cmp
    res["free_disk_gb"] = round(shutil.disk_usage(root).free / 1e9, 1)
    # ---------------------------------------------------------------- per-claim export + regression check
    reach_ids = [c["claim_id"] for c, r in zip(claims, reach) if r]
    percl, problems = {}, []
    old = json.load(open(os.path.join(a.out, "own_store_removal.json"), encoding="utf-8"))
    for (label, rname), mets in store.items():
        for metric, m in mets.items():
            ids, vals = (m[0], m[1]) if isinstance(m, tuple) else (reach_ids, m)
            vals = np.asarray(vals, float)
            ok = ~np.isnan(vals)
            percl.setdefault(label, {}).setdefault(rname, {})[metric] = {
                "n": int(ok.sum()), "n_total": int(len(vals)),
                "values": {str(i): (float(v) if not np.isnan(v) else None) for i, v in zip(ids, vals)}}
            # aggregate to compare with: the value this run reported (paired table) and the value of the earlier run
            agg_new = None
            if label == "normal":
                agg_new = res["paired_vs_normal"]["primary"][rname][metric]["normal"]
            elif label in res["paired_vs_normal"]:
                agg_new = res["paired_vs_normal"][label][rname][metric]["removed"]
            if agg_new is not None and abs(float(np.nanmean(vals)) - agg_new) > 5e-5:
                problems.append((label, rname, metric, "per-claim mean vs this run's aggregate", float(np.nanmean(vals)), agg_new))
            if label in old["paired_vs_normal"] and label != "normal":
                o = old["paired_vs_normal"][label][rname][metric]["removed"]
                if abs(float(np.nanmean(vals)) - o) > 0.001:
                    problems.append((label, rname, metric, "vs earlier run own_store_removal.json", float(np.nanmean(vals)), o))
            if label == "normal":
                o = old["paired_vs_normal"]["primary"][rname][metric]["normal"]
                if abs(float(np.nanmean(vals)) - o) > 0.001:
                    problems.append((label, rname, metric, "normal vs earlier run", float(np.nanmean(vals)), o))
    res["regression_check"] = {"tolerance": 0.001, "n_compared": sum(len(m) for r in percl.values() for m in r.values()),
                               "problems": problems}
    if problems:
        print("REGRESSION CHECK FAILED:", problems[:10], flush=True)
        with open(os.path.join(a.out, "own_store_removal_rerun_FAILED.json"), "w", encoding="utf-8") as f:
            json.dump(res, f, indent=1)
        return 1
    fz = json.load(open("docs/corpus_v1_freeze.json", encoding="utf-8"))
    import subprocess
    meta = {"git_commit": subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip(),
            "src_clean": subprocess.run(["git", "status", "--porcelain", "--", "src", "scripts", "tests"],
                                        capture_output=True, text=True).stdout.strip() == "",
            "corpus_v1_freeze": {k: fz[k] for k in ("chunks_digest", "vectors_digest", "bm25_digest",
                                                    "documents_shards_digest", "ranks_sha256")},
            "started": started, "finished": time.strftime("%Y-%m-%d %H:%M:%S"),
            "run_seconds": round(time.time() - t_start), "bootstrap_seed": 7,
            "claim_sets": {"evaluated": len(claims), "reachable": int(reach.sum())},
            "rerun_of": "docs/reports/own_store_removal_prereg.md (no design change)"}
    with open(os.path.join(a.out, "own_store_removal_per_claim.json"), "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "variants": percl}, f)
    res["meta"] = meta
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "own_store_removal_rerun.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1)
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
