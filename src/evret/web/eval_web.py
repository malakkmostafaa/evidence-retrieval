"""WS5 - evaluation layer of the web tool: the ONLY module that joins claims, gold URLs and the search tool.

Gold URLs are used for scoring only; the tool receives the claim text, the claim date and the claim's own URLs.
Smoke set: 10 held-out claims (ranks 180-189 of the D3 ranking) and 5 pooled claims (ranks 0-4). Rank order is label-stratified,
so any prefix is roughly balanced. These 10 held-out claims are SEEN after this run (manual review): do not use them as a
blind test for the web tool again.

usage: python -m evret.web.eval_web --out outputs/web_smoke [--replay]
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import glob
import json
import os
import time
from collections import Counter

from evret.audit import is_factcheck, load_dev, normalize_url
from evret.urls import url_variants
from evret.web.schema import ClaimContext

DEV = r"C:\Users\malak\Desktop\thesis\data\raw\averitec\dev.json"
CORPUS = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "evidence-retrieval", "data", "corpus_v1")
HELD_OUT_RANKS = range(180, 190)
POOLED_RANKS = range(0, 5)
CONDITIONS = {"main": {}, "lenient": {"lenient_dates": True}, "factcheck": {"include_factcheck": True}}


def iso(d: str) -> str | None:
    """AVeriTeC claim_date 'DD-MM-YYYY' -> 'YYYY-MM-DD'."""
    try:
        return datetime.datetime.strptime(d, "%d-%m-%Y").strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return None


def load_smoke_claims(dev_path: str = DEV, ranks_path: str | None = None, which: str = "smoke") -> list[dict]:
    ranks_path = ranks_path or os.path.join(CORPUS, "ranks.json")
    ranks = {int(k): v for k, v in json.load(open(ranks_path, encoding="utf-8")).items()}
    raw = json.load(open(dev_path, encoding="utf-8"))
    by_rank = {r: c for c, r in ranks.items()}
    dev = load_dev(dev_path)
    out = []
    if which == "pool":                            # bands 0..pool_bands-1 of the shared rank table; sealed claims are never loaded
        cfg = json.load(open(os.path.join(CORPUS, "manifest.json"), encoding="utf-8"))["config"]
        groups = (("pooled", range(0, cfg["pool_bands"] * cfg["band_size"])),)
    elif which == "smoke":
        groups = (("pooled", POOLED_RANKS), ("held-out", HELD_OUT_RANKS))
    else:
        groups = (("pooled", range(0, 180)), ("held-out", range(180, 300)))
    for group, rr in groups:
        for r in rr:
            cid = by_rank[r]
            c, rw = dev[cid], raw[cid]
            own = [rw.get(f) for f in ("fact_checking_article", "original_claim_url", "cached_original_claim_url") if rw.get(f)]
            out.append({"claim_id": cid, "rank": r, "group": group, "text": rw["claim"], "label": rw["label"],
                        "claim_date": iso(rw.get("claim_date")), "own_urls": own, "gold_urls": c["gold_urls"],
                        "gold_variants": [url_variants(u) for u in c["gold_urls"] if u]})
    return out


def matches_gold(url: str, gold_variants: list[set]) -> list[int]:
    v = url_variants(url)
    return [i for i, g in enumerate(gold_variants) if v & g]


def score_claim(claim: dict, tool, cond: str) -> dict:
    ctx = ClaimContext(claim_date=claim["claim_date"], exclude_urls=frozenset(claim["own_urls"]),
                       **CONDITIONS[cond])
    t0 = time.perf_counter()
    hits = tool.search_web(claim["text"], k=50, claim_context=ctx)
    wall = time.perf_counter() - t0
    rep = tool.last_report
    gv = claim["gold_variants"]
    gold_in = lambda urls: sorted({i for u in urls for i in matches_gold(u, gv)})
    results = [u.url for u in rep.urls]
    fetched = [u.url for u in rep.urls if u.fetch_status == "ok"]
    kept = [u.url for u in rep.urls if u.removed is None]
    gold_removed = {}
    for u in rep.urls:
        for i in matches_gold(u.url, gv):
            gold_removed[i] = u.removed or "kept"
    return {"claim_id": claim["claim_id"], "rank": claim["rank"], "group": claim["group"], "label": claim["label"],
            "cond": cond, "claim_date": claim["claim_date"], "n_gold": len(gv), "wall_s": round(wall, 2),
            "seconds": {k: round(v, 2) for k, v in rep.seconds.items()}, "counts": rep.counts(),
            "n_passages": rep.n_passages, "search_error": rep.search_error, "query_used": rep.query_used,
            "fallback": rep.fallback,
            "gold": {"in_results": gold_in(results), "in_fetched": gold_in(fetched), "in_kept": gold_in(kept),
                     "in_top5": gold_in([h.url for h in hits[:5]]), "in_top10": gold_in([h.url for h in hits[:10]]),
                     "in_top50": gold_in([h.url for h in hits[:50]]), "gold_fate": {str(k): v for k, v in gold_removed.items()}},
            "urls": [dataclasses.asdict(u) for u in rep.urls],
            "hits": [{"rank": h.rank, "url": h.url, "domain": h.domain, "pub_date": h.pub_date, "date_source": h.date_source,
                      "fetched_from": h.fetched_from, "score": h.score, "dense": h.dense_score, "bm25": h.bm25_score,
                      "flags": h.flags, "text": h.text} for h in hits]}


def lock_provider(cache_dir: str, provider_id: str):
    """A cache directory belongs to ONE provider/backend: mixing providers inside one experiment is not allowed."""
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, "provider.json")
    if os.path.exists(path):
        have = json.load(open(path))["provider"]
        if have != provider_id:
            raise RuntimeError(f"cache {cache_dir} was recorded with {have}; never mix providers within one experiment (asked for {provider_id})")
    else:
        json.dump({"provider": provider_id}, open(path, "w"))


def make_provider(name: str):
    from evret.web.providers import DdgsProvider, SerperProvider
    if name == "serper":
        return SerperProvider()
    if name == "ddgs":
        return DdgsProvider("duckduckgo")
    raise ValueError(name)


def build_tool(cache_dir: str, replay: bool, corpus: str = CORPUS, provider: str = "ddgs"):
    from evret import bm25 as bm
    from evret.chunk import make_counter, tokenizer_file
    from evret.embed import Encoder
    from evret.web.fetch import Fetcher, Wayback
    from evret.web.netlog import NetLog
    from evret.web.pagecache import PageCache
    from evret.web.providers import CachedSearch, DdgsProvider, SearchCache
    from evret.web.schema import Mode
    from evret.web.select import PoolStats
    from evret.web.tool import WebSearchTool
    os.makedirs(cache_dir, exist_ok=True)
    mode = Mode.REPLAY if replay else Mode.LIVE
    netlog = NetLog(os.path.join(cache_dir, "netlog.jsonl"))
    cache = PageCache(cache_dir)
    fetcher = Fetcher(cache, mode, netlog=netlog, workers=4)
    prov = make_provider(provider)
    lock_provider(cache_dir, f"{prov.name}/{prov.backend}")
    search = CachedSearch(prov, SearchCache(os.path.join(cache_dir, "search.sqlite")), mode=mode, netlog=netlog)
    stats_path = os.path.join(cache_dir, "pool_stats.json")
    if os.path.exists(stats_path):
        stats = PoolStats.from_frozen(json.load(open(stats_path)))
        stats.index = None if replay else bm.BM25Index(sorted(glob.glob(os.path.join(corpus, "bm25", "band=*"))))
    else:
        stats = PoolStats.from_index(bm.BM25Index(sorted(glob.glob(os.path.join(corpus, "bm25", "band=*")))))
    enc = Encoder("cpu", "fp32")
    tool = WebSearchTool(search, fetcher, Wayback(fetcher), enc, make_counter(tokenizer_file()), stats)
    return tool, netlog, prov


def load_results(d: str, replay: bool = False) -> list[dict]:
    """results.json (smoke) or results.jsonl (full run; the LAST line of a (condition, claim) wins)."""
    name = "results_replay" if replay else "results"
    if os.path.exists(os.path.join(d, name + ".json")):
        return json.load(open(os.path.join(d, name + ".json")))["results"]
    last = {}
    path = os.path.join(d, name + ".jsonl")
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            if line.strip():
                r = json.loads(line)
                last[(r["cond"], r["claim_id"])] = r
    return list(last.values())


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="outputs/web_smoke")
    ap.add_argument("--cache", default="outputs/web_cache")
    ap.add_argument("--replay", action="store_true")
    ap.add_argument("--provider", choices=["serper", "ddgs"], required=True, help="serper = evaluation runs; ddgs = development only")
    ap.add_argument("--conds", default="main,lenient,factcheck")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--claims", choices=["smoke", "pool", "all"], default="smoke", help="smoke = 15 claims, pool = the 180 pool claims (bands 0-5), all = 300 (needs approval); pool/all write JSONL")
    ap.add_argument("--stats-only", action="store_true", help="only freeze the pool df of all claim queries (reads the local BM25 index, no network, no model)")
    ap.add_argument("--threads", type=int, default=3, help="CPU threads for the embedding model (keep low while the GPU job runs)")
    ap.add_argument("--resume", action="store_true", help="keep results already in results.json (their timings stay cold)")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    claims = load_smoke_claims(which=a.claims)[: a.limit]
    import torch
    torch.set_num_threads(a.threads)
    tool, netlog, prov = build_tool(a.cache, a.replay, provider=a.provider)
    q0 = prov.budget.used() if hasattr(prov, "budget") else None
    stats_path = os.path.join(a.cache, "pool_stats.json")
    if not a.replay:                               # df of every claim query comes from the local index: freeze them all up front
        from evret import bm25 as bm
        for c in claims:
            for t in {bm.term_hash(t) for t in bm.tokenize(c["text"])}:
                tool.stats.idf(t)
        json.dump(tool.stats.freeze(), open(stats_path, "w"))
    if a.stats_only:
        print("frozen df terms:", len(tool.stats.df))
        return
    full = a.claims in ("pool", "all")
    path = os.path.join(a.out, ("results_replay" if a.replay else "results") + (".jsonl" if full else ".json"))
    results = load_results(a.out, a.replay) if a.resume else []
    if a.resume:                                   # a failed search is redone; successful claims keep their (cold) timings
        results = [r for r in results if not r.get("search_error") and r["counts"]["returned"] > 0]
    done = {(r["cond"], r["claim_id"]) for r in results}
    for cond in a.conds.split(","):
        for c in claims:
            if (cond, c["claim_id"]) in done:
                continue
            r = score_claim(c, tool, cond)
            results.append(r)
            print(f"[{cond}] claim {c['claim_id']:>3} ({c['group']}) {r['wall_s']:6.1f}s kept={r['counts']['kept']} "
                  f"passages={r['n_passages']} fb={r['fallback']} gold_top50={r['gold']['in_top50']} of {r['n_gold']}", flush=True)
            json.dump(tool.stats.freeze(), open(stats_path, "w"))        # keep the frozen statistics current (a killed run must not lose them)
            if full:
                with open(path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(r) + "\n")
            else:
                json.dump({"results": results, "stats": tool.stats.freeze()}, open(path, "w"), indent=1)
    json.dump(tool.stats.freeze(), open(os.path.join(a.cache, "pool_stats.json"), "w"))
    manifest = {"manifest_hash": tool.manifest_hash(), "n_network_calls": Counter(r["kind"] for r in netlog.records),
                "mode": "replay" if a.replay else "live", "provider": f"{prov.name}/{prov.backend}/{prov.version}"}
    if q0 is not None:
        manifest.update(live_queries_this_invocation=prov.budget.used() - q0, live_queries_total_on_this_machine=prov.budget.used(),
                        last_credits_reported=getattr(prov, "last_credits", None))
    json.dump(manifest, open(os.path.join(a.out, "manifest_replay.json" if a.replay else "manifest.json"), "w"), indent=1)
    print(manifest)


if __name__ == "__main__":
    main()
