"""S5 - evaluation layer: the ONLY module that joins claims, gold URLs and the search tool.

Gold URLs are used for scoring only; the retrievers receive the claim text and `exclude_norm_urls`.
Evaluated claims = pooled claims whose band is finished; the searched corpus = all finished bands.

Metrics (chunk level): SourceHit@k = a gold URL appears among the URLs of the top-k chunks.
  claim hit rate = share of claims with >= 1 gold URL in the top-k; gold recall = mean share of a claim's gold URLs found.
  Both are reported on "reachable" claims (>= 1 gold URL has a non-empty, non-tiny, non-fact-check indexed document) and
  on all evaluated claims (unreachable claims count as 0).
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time

import numpy as np
import psutil

from evret import metrics_cov as mc
from evret.audit import load_dev
from evret.urls import url_variants

K_LIST = (10, 50)


def load_claims(dev_path: str, ranks_path: str, band_size: int, finished_bands: list[int]) -> list[dict]:
    raw = json.load(open(dev_path, encoding="utf-8"))
    ranks = {int(k): v for k, v in json.load(open(ranks_path, encoding="utf-8")).items()}
    dev = load_dev(dev_path)
    out = []
    for c in dev:
        cid = c["claim_id"]
        if cid not in ranks or ranks[cid] // band_size not in finished_bands:
            continue
        r = raw[cid]
        excl = set()
        for field in ("fact_checking_article", "original_claim_url", "cached_original_claim_url"):
            excl |= url_variants(r.get(field) or "")
        gold = [url_variants(u) for u in c["gold_urls"] if u]
        out.append({"claim_id": cid, "rank": ranks[cid], "band": ranks[cid] // band_size, "text": r["claim"],
                    "label": r["label"], "gold_urls": c["gold_urls"], "raw_gold_urls": c["gold_urls"], "gold_variants": gold,
                    "exclude": frozenset(excl), "raw": r})
    out.sort(key=lambda x: x["rank"])
    return out


def hit_matches(hit_url: str, variants: set[str]) -> bool:
    return bool(url_variants(hit_url) & variants)


def source_hit(hit_urls: list[str], gold_variants: list[set], k: int) -> tuple[bool, float]:
    """(any gold URL among the first k hit URLs, share of gold URLs found)."""
    if not gold_variants:
        return False, 0.0
    found = sum(any(hit_matches(u, g) for u in hit_urls[:k]) for g in gold_variants)
    return found > 0, found / len(gold_variants)


def reachable_flags(corpus, claim) -> list[bool]:
    """Per gold URL: is there an indexed (chunked), non-fact-check document under that URL?"""
    have = set(np.unique(corpus.doc_id).tolist())
    out = []
    for g in claim["gold_variants"]:
        ok = False
        for v in g:
            for d in corpus.url_to_docs.get(v, ()):
                if d in have and not corpus.docs["is_factcheck"][d]:
                    ok = True
        out.append(ok)
    return out


def gold_state(corpus, variants, have) -> str:
    """Why a gold URL is (not) reachable: reachable | factcheck_flag | empty_text | tiny_text | not_in_index."""
    docs = [d for v in variants for d in corpus.url_to_docs.get(v, ())]
    if not docs:
        return "not_in_index"
    if any(d in have and not corpus.docs["is_factcheck"][d] for d in docs):
        return "reachable"
    if any(d in have for d in docs):
        return "factcheck_flag"
    if any(not corpus.docs["is_empty"][d] and corpus.docs["is_tiny"][d] for d in docs):
        return "tiny_text"
    return "empty_text"


def bootstrap(per_claim: dict, names: list[str], n_boot: int = 10000, seed: int = 7) -> dict:
    """per_claim[name] = array over claims (same order). Percentile 95% CI of the mean by resampling CLAIMS, and CI of
    the paired mean difference for every pair (same resampled claims for all methods)."""
    rng = np.random.default_rng(seed)
    n = len(per_claim[names[0]])
    idx = rng.integers(0, n, size=(n_boot, n))
    out = {"mean": {}, "ci95": {}, "paired_diff": {}}
    for nm in names:
        a = np.asarray(per_claim[nm], dtype=float)
        bs = a[idx].mean(1)
        out["mean"][nm] = round(float(a.mean()), 4)
        out["ci95"][nm] = [round(float(np.percentile(bs, 2.5)), 4), round(float(np.percentile(bs, 97.5)), 4)]
    for i, x in enumerate(names):
        for y in names[i + 1:]:
            d = np.asarray(per_claim[x], float) - np.asarray(per_claim[y], float)
            bs = d[idx].mean(1)
            lo, hi = float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))
            out["paired_diff"][f"{x} - {y}"] = {"mean": round(float(d.mean()), 4), "ci95": [round(lo, 4), round(hi, 4)],
                                                 "excludes_zero": bool(lo > 0 or hi < 0)}
    return out


COV_BUDGET = 512


def make_token_fns():
    """(count_tokens, offsets_fn) from the BGE tokenizer, WITHOUT special tokens (as in the legacy code)."""
    from tokenizers import Tokenizer
    from evret.embed import snapshot_dir
    tok = Tokenizer.from_file(os.path.join(snapshot_dir(), "tokenizer.json"))
    tok.no_truncation()
    return (lambda t: len(tok.encode(mc.clean_for_tokenizer(t), add_special_tokens=False).ids),
            lambda t: tok.encode(mc.clean_for_tokenizer(t), add_special_tokens=False).offsets)


def anchored_answers(corpus_root: str, claims: list[dict]) -> dict:
    """claim_id -> anchored gold answers (legacy rule: scorable and found in a 200-token window of the cited page)."""
    from evret.eval_labels import page_texts
    urls = {a["url"] for c in claims for a in mc.gold_answers(c["raw"]) if a["url"]}
    texts = page_texts(corpus_root, urls)
    return {c["claim_id"]: [a for a in mc.anchor_claim(c["raw"], texts) if a["anchored"]] for c in claims}


def coverage(claims, hits_by_claim, anchored, budget=COV_BUDGET, ks=(5, 10)) -> dict:
    """Per-claim legacy metrics (CovNovel@B, CovUnion@B, AnswerRecall@k, SourceHit/MRR on the ranked chunks) for the claims
    that have >= 1 anchored answer. Returns {metric: array over eligible claims}, plus the eligible claim ids."""
    count, offs = make_token_fns()
    rows, ids = [], []
    for c, hits in zip(claims, hits_by_claim):
        ans = anchored[c["claim_id"]]
        if not ans:
            continue
        ranked = [mc.passage_from_hit(h, count) for h in hits]
        rows.append(mc.claim_row(ans, mc.gold_keys(c["raw_gold_urls"]), ranked, budget, ks, offs,
                                 claim_tokens=frozenset(mc.content_tokens(c["text"]))))
        ids.append(c["claim_id"])
    keys = rows[0].keys() if rows else []
    return {"claim_ids": ids, **{k: np.array([r[k] for r in rows], float) for k in keys}}


def evaluate(corpus, retrievers: dict, claims: list[dict], pool_docs: int, corpus_root: str, log=print) -> dict:
    from evret.search import Filters
    res = {"n_claims": len(claims), "variants": {}}
    reach = [reachable_flags(corpus, c) for c in claims]
    n_reach_claims = sum(any(r) for r in reach)
    have = set(np.unique(corpus.doc_id).tolist())
    from collections import Counter
    states = Counter(gold_state(corpus, g, have) for c in claims for g in c["gold_variants"])
    res["gold_url_states"] = dict(states)
    res["gold"] = {"gold_urls": sum(len(c["gold_variants"]) for c in claims),
                   "gold_urls_reachable": sum(sum(r) for r in reach), "claims_with_reachable_gold": n_reach_claims,
                   "claims_without_gold_url": sum(not c["gold_variants"] for c in claims)}
    leaks = {"sealed_or_unknown_doc_returned": 0, "own_article_returned": 0, "hits_checked": 0}
    store = {}
    per = {}
    anchored = anchored_answers(corpus_root, claims)
    res["coverage_eligible_claims"] = sum(bool(v) for v in anchored.values())
    cov_all = {}
    for vname, flags in (("default (fact-check excluded)", frozenset({"factcheck", "tiny"})),
                         ("ablation (fact-check included)", frozenset({"tiny"}))):
        res["variants"][vname] = {}
        for rname, ret in retrievers.items():
            filters = [Filters(exclude_norm_urls=c["exclude"], exclude_flags=flags) for c in claims]
            t0 = time.time()
            hits = ret.search_batch([c["text"] for c in claims], max(K_LIST), filters)
            dt = time.time() - t0
            store[(vname, rname)] = hits
            cov_all[(vname, rname)] = coverage(claims, hits, anchored)
            row = {"seconds_batch": round(dt, 2), "ms_per_query_batch": round(1000 * dt / len(claims), 1)}
            for k in K_LIST:
                anyk, recall, anyk_r, recall_r = [], [], [], []
                for c, h, rc in zip(claims, hits, reach):
                    a, r = source_hit([x.url for x in h], c["gold_variants"], k)
                    anyk.append(a)
                    recall.append(r)
                    if any(rc):
                        anyk_r.append(a)
                        recall_r.append(r)
                row[f"SourceHit@{k}_reachable_claims"] = round(float(np.mean(anyk_r)), 4) if anyk_r else None
                row[f"GoldRecall@{k}_reachable_claims"] = round(float(np.mean(recall_r)), 4) if recall_r else None
                row[f"SourceHit@{k}_all_claims"] = round(float(np.mean(anyk)), 4)
            res["variants"][vname][rname] = row
            for k in K_LIST:
                for key, sel in (("any", 0), ("recall", 1)):
                    per[(vname, k, key, rname)] = [source_hit([x.url for x in h], c["gold_variants"], k)[sel]
                                                   for c, h in zip(claims, hits)]
            for c, h in zip(claims, hits):
                for x in h:
                    leaks["hits_checked"] += 1
                    leaks["sealed_or_unknown_doc_returned"] += not (0 <= x.doc_id < pool_docs)
                    leaks["own_article_returned"] += hit_matches(x.url, set(c["exclude"]))
            log(f"  {vname} / {rname}: {row}")
    res["reachable_claims"] = n_reach_claims
    res["coverage"] = {}
    B = COV_BUDGET
    for vname in res["variants"]:
        for metric in (f"cov_novel@B{B}", f"cov_union@B{B}", "answer_recall@10", f"cov_novel@10", "source_hit@10"):
            arrs = {r: cov_all[(vname, r)][metric] for r in retrievers}
            ok = ~np.isnan(np.vstack(list(arrs.values()))).any(0)
            if ok.sum() < 2:
                continue
            res["coverage"][f"{vname} | {metric}"] = {"n_claims": int(ok.sum()), **bootstrap({r: a[ok] for r, a in arrs.items()}, list(retrievers))}
    mask = np.array([any(r) for r in reach])
    res["bootstrap_reachable_claims"] = {}
    for vname in res["variants"]:
        for k in K_LIST:
            for key in ("any", "recall"):
                pc = {r: np.asarray(per[(vname, k, key, r)], float)[mask] for r in retrievers}
                res["bootstrap_reachable_claims"][f"{vname} | {'SourceHit' if key == 'any' else 'GoldRecall'}@{k}"] =                     bootstrap(pc, list(retrievers))
    res["leakage_checks"] = leaks
    return res, store


def examples(claims, store, n=5, seed=1, vname="default (fact-check excluded)") -> str:
    rng = random.Random(seed)
    pick = rng.sample(range(len(claims)), min(n, len(claims)))
    out = []
    for i in sorted(pick):
        c = claims[i]
        out += [f"### Claim {c['claim_id']} (rank {c['rank']}, label {c['label']})", f"> {c['text']}", "",
                "Gold URLs: " + "; ".join(c["gold_urls"][:6]), ""]
        for rname in ("dense", "bm25", "hybrid"):
            out.append(f"**{rname}**")
            for x in store[(vname, rname)][i][:5]:
                star = " **[GOLD]**" if any(hit_matches(x.url, g) for g in c["gold_variants"]) else ""
                snip = " ".join(x.text.split())[:240]
                out.append(f"{x.rank}. `{x.score:.4f}` {x.url}{star} {x.flags or ''}  \n   {snip}")
            out.append("")
    return "\n".join(out)


def main(argv=None):
    import torch
    from evret import bm25 as bm
    from evret import embed as em
    from evret import search as sr
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--dev", required=True)
    ap.add_argument("--bands", type=int, nargs="+", required=True, help="finished bands to search and evaluate")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    ing = json.load(open(os.path.join(a.corpus, "manifest.json"), encoding="utf-8"))
    band_size = ing["config"]["band_size"]
    proc = psutil.Process()
    corpus = sr.Corpus(a.corpus, a.bands)
    enc = em.Encoder(dtype="fp32", device="cuda" if torch.cuda.is_available() else "cpu")
    dense = sr.DenseExact(corpus, em.load_vectors(a.corpus, a.bands), enc)
    sparse = sr.BM25(corpus, bm.BM25Index([os.path.join(a.corpus, "bm25", f"band={b}") for b in a.bands]))
    rets = {"dense": dense, "bm25": sparse, "hybrid": sr.Hybrid(dense, sparse)}
    claims = load_claims(a.dev, os.path.join(a.corpus, "ranks.json"), band_size, a.bands)
    pool_docs = ing["counts"]["documents_pool"]
    # single-query latency (not batched)
    lat = {}
    for rname, r in rets.items():
        ts = []
        for c in claims[:10]:
            t0 = time.time()
            r.search(c["text"], 10, sr.Filters(exclude_norm_urls=c["exclude"]))
            ts.append(time.time() - t0)
        lat[rname] = {"ms_per_query_single_median": round(1000 * float(np.median(ts)), 1)}
    res, store = evaluate(corpus, rets, claims, pool_docs, a.corpus)
    res["latency"] = lat
    import shutil
    res["free_disk_gb"] = round(shutil.disk_usage(a.corpus).free / 1e9, 1)
    res["peak_ram_gb"] = round(proc.memory_info().peak_wset / 1e9, 2) if hasattr(proc.memory_info(), "peak_wset") else None
    res["bands"] = a.bands
    res["n_chunks_searched"] = corpus.n
    os.makedirs(a.out, exist_ok=True)
    tag = "_".join(map(str, a.bands))
    with open(os.path.join(a.out, f"eval_bands_{tag}.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1)
    with open(os.path.join(a.out, f"examples_bands_{tag}.md"), "w", encoding="utf-8") as f:
        f.write(examples(claims, store))
    print(json.dumps({k: v for k, v in res.items() if k != "variants"}, indent=1))


if __name__ == "__main__":
    sys.exit(main())
