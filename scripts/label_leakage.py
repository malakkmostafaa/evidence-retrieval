"""Step 5: find the source URL of the 100 labelled passages by text match in the new corpus and flag passages that come from
the claim's own fact_checking_article / original_claim_url (Wayback-unwrapped). Pool claims only (sealed documents do not exist)."""
import json, os, re, sys
import numpy as np
from evret import bm25 as bm, eval_labels as el, eval_pool as ev, metrics_cov as mc, search as sr
from evret.urls import url_variants

root = "data/corpus_v1"
rows = el.load_rows()
dev_path = "C:/Users/malak/Desktop/thesis/data/raw/averitec/dev.json"
dev = json.load(open(dev_path, encoding="utf-8"))
ranks = {int(k): v for k, v in json.load(open(f"{root}/ranks.json")).items()}
corpus = sr.Corpus(root, [0, 1, 2, 3, 4, 5])
ret = sr.BM25(corpus, bm.BM25Index([f"{root}/bm25/band={b}" for b in range(6)]))
ws = lambda s: re.sub(r"\s+", " ", s).strip()
res = []
for i, r in enumerate(rows):
    cid = int(r["claim_id"])
    if ranks[cid] >= 180:
        res.append({"row": i, "status": "sealed_claim_not_matchable"})
        continue
    p = ws(r["passage"])
    words = p.split()
    q = " ".join(words[:40])
    hits = ret.search(q, 30, sr.Filters(exclude_flags=frozenset()))
    probes = [p[o:o + 100] for o in (0, 200, 400) if len(p) >= o + 100]
    found = set()
    for h in hits:
        t = ws(h.text)
        if any(pr in t for pr in probes):
            found.add(h.url)
    excl = set()
    for f in ("fact_checking_article", "original_claim_url", "cached_original_claim_url"):
        excl |= url_variants(dev[cid].get(f) or "")
    own = [u for u in found if url_variants(u) & excl]
    res.append({"row": i, "status": "matched" if found else "unmatched", "urls": sorted(found)[:5], "own_article": bool(own)})
json.dump(res, open("outputs/corpus_v1/label_leakage.json", "w"), indent=1)
from collections import Counter
print(Counter(r["status"] for r in res), "own:", sum(r.get("own_article", False) for r in res))
