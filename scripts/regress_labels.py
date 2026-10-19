"""Regression of the ported metrics against the 100 manual labels. Sealed-claim rows are never anchored."""
import json
import numpy as np
from evret import eval_labels as el, metrics_cov as mc

rows = el.load_rows()
dev = json.load(open("C:/Users/malak/Desktop/thesis/data/raw/averitec/dev.json", encoding="utf-8"))
ranks = {int(k): v for k, v in json.load(open("data/corpus_v1/ranks.json")).items()}
lab = np.array([r["label"] for r in rows])
sv = np.array([[r["soft_saved"], r["novel_saved"]] for r in rows])
pool = np.array([ranks[int(r["claim_id"])] < 180 for r in rows])
cids = {int(r["claim_id"]) for r, p in zip(rows, pool) if p}
T = el.page_texts("data/corpus_v1", {a["url"] for c in cids for a in mc.gold_answers(dev[c]) if a["url"]})
cache = {}
def anch(c):
    if ranks[c] >= 180:
        return None
    if c not in cache:
        cache[c] = [a for a in mc.anchor_claim(dev[c], T) if a["anchored"]]
    return cache[c]
A = el.score_rows(rows, dev, anch)
U = el.score_rows(rows, dev, lambda c: [a for a in mc.gold_answers(dev[c]) if a["scorable"]])
eq = lambda x, y: np.isclose(x, y, equal_nan=True).all(1)
rd = lambda d: {k: {a: round(b, 3) if isinstance(b, float) else b for a, b in v.items()} for k, v in d.items()}
out = {
    "v1_saved_all100": rd(el.label_stats(lab, sv[:, 0], sv[:, 1])),
    "v2_ported_anchored_pool57": rd(el.label_stats(lab[pool], A[pool, 0], A[pool, 1])),
    "v2_saved_same57_rows": rd(el.label_stats(lab[pool], sv[pool, 0], sv[pool, 1])),
    "v3_ported_unanchored_all100": rd(el.label_stats(lab, U[:, 0], U[:, 1])),
    "exact_rows": {"pool_anchored": f"{int(eq(A, sv)[pool].sum())}/{int(pool.sum())}",
                   "all100_unanchored": f"{int(eq(U, sv).sum())}/100",
                   "sealed43_unanchored": f"{int(eq(U, sv)[~pool].sum())}/{int((~pool).sum())}"},
    "differing_pool_rows": [{"row": int(i), "claim_id": int(rows[i]["claim_id"]), "ported": A[i].round(4).tolist(),
                             "saved": sv[i].round(4).tolist()} for i in np.where(pool & ~eq(A, sv))[0]],
}
json.dump(out, open("outputs/corpus_v1/label_regression.json", "w"), indent=1)
print(json.dumps(out, indent=1))
