"""Blinded 50-passage relabelling sheet from the new tool (design: docs/reports/corpus_tool_v1.md, section "Relabelling").

Candidates: top-5 chunks of dense, BM25 and hybrid (default filters, own-article URLs excluded) for the pooled claims
that have >= 1 anchored answer. Sample: 17 dense + 17 BM25 + 16 hybrid candidates (drawn arm by arm, seed 42, no passage
twice, at most 2 passages per claim). The sheet shows the FULL chunk text. The key (which arm(s) returned the passage) is
written to a separate file that must not be opened before the labels come back.
"""
import csv
import json
import os
import random
import re
import sys

import numpy as np

from evret import bm25 as bm
from evret import embed as em
from evret import eval_pool as ev
from evret import search as sr

SEED, N_PER_ARM, TOP = 42, {"dense": 17, "bm25": 17, "hybrid": 16}, 5
root = "data/corpus_v1"
out_dir = os.path.join("outputs", "corpus_v1", "relabel")
os.makedirs(out_dir, exist_ok=True)

ing = json.load(open(f"{root}/manifest.json", encoding="utf-8"))
bands = list(range(6))
claims = ev.load_claims("C:/Users/malak/Desktop/thesis/data/raw/averitec/dev.json", f"{root}/ranks.json",
                        ing["config"]["band_size"], bands)
anchored = ev.anchored_answers(root, claims)
claims = [c for c in claims if anchored[c["claim_id"]]]
print("eligible claims:", len(claims))

corpus = sr.Corpus(root, bands)
enc = em.Encoder(dtype="fp32")
dense = sr.DenseExact(corpus, em.load_vectors(root, bands), enc)
sparse = sr.BM25(corpus, bm.BM25Index([f"{root}/bm25/band={b}" for b in bands]))
rets = {"dense": dense, "bm25": sparse, "hybrid": sr.Hybrid(dense, sparse)}
filters = [sr.Filters(exclude_norm_urls=c["exclude"]) for c in claims]
cands = {}                                             # arm -> list of (claim_idx, chunk_id, rank)
texts = {}
for arm, r in rets.items():
    hits = r.search_batch([c["text"] for c in claims], TOP, filters)
    cands[arm] = [(i, h.chunk_id, h.rank) for i, hs in enumerate(hits) for h in hs]
    for i, hs in enumerate(hits):
        for h in hs:
            texts[h.chunk_id] = h.text

rng = random.Random(SEED)
chosen, per_claim = {}, {}
for arm in ("dense", "bm25", "hybrid"):
    pool = [t for t in cands[arm] if (t[0], t[1]) not in chosen]
    rng.shuffle(pool)
    n = 0
    for i, cid, rank in pool:
        if n >= N_PER_ARM[arm]:
            break
        if (i, cid) in chosen or per_claim.get(i, 0) >= 2:
            continue
        chosen[(i, cid)] = {"first_arm": arm}
        per_claim[i] = per_claim.get(i, 0) + 1
        n += 1
# record every arm that returned a chosen passage (with its rank)
for arm in rets:
    for i, cid, rank in cands[arm]:
        if (i, cid) in chosen:
            chosen[(i, cid)].setdefault("arms", {})[arm] = rank

order = list(chosen)
rng.shuffle(order)
ctrl = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
n_ctrl = 0
with open(os.path.join(out_dir, "relabel_sheet_TO_LABEL.csv"), "w", encoding="utf-8-sig", newline="") as f:
    w = csv.writer(f)
    w.writerow(["row", "claim", "passage", "relevance_0_1_2"])
    for row, (i, cid) in enumerate(order):
        t = texts[cid]
        n_ctrl += len(ctrl.findall(t))
        w.writerow([row, claims[i]["text"], ctrl.sub(" ", t), ""])
key = [{"row": row, "claim_id": claims[i]["claim_id"], "chunk_id": cid, "first_arm": chosen[(i, cid)]["first_arm"],
        "arms_and_ranks": chosen[(i, cid)]["arms"]} for row, (i, cid) in enumerate(order)]
json.dump(key, open(os.path.join(out_dir, "relabel_KEY_do_not_open.json"), "w"), indent=1)
print("rows", len(order), "control characters replaced by spaces:", n_ctrl,
      "claims used:", len({i for i, _ in order}))
