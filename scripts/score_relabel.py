"""Score the returned labels with the rules fixed in docs/reports/corpus_tool_v1.md. Run ONLY after the labelled CSV is back.
Usage: python scripts/score_relabel.py <labelled.csv>"""
import csv, json, sys
import numpy as np
from evret import eval_labels as el, eval_pool as ev, metrics_cov as mc

root = "data/corpus_v1"
csv.field_size_limit(2**31 - 1)
rows = list(csv.DictReader(open(sys.argv[1], encoding="utf-8-sig", newline="")))
key = {k["row"]: k for k in json.load(open("outputs/corpus_v1/relabel/relabel_KEY_do_not_open.json"))}
ing = json.load(open(f"{root}/manifest.json", encoding="utf-8"))
claims = {c["claim_id"]: c for c in ev.load_claims("C:/Users/malak/Desktop/thesis/data/raw/averitec/dev.json",
                                                    f"{root}/ranks.json", ing["config"]["band_size"], list(range(6)))}
anchored = ev.anchored_answers(root, list(claims.values()))
lab, soft, nov, arms = [], [], [], []
for r in rows:
    k = key[int(r["row"])]
    c = claims[k["claim_id"]]
    p = mc.Passage("x", r["passage"], 0, 0)
    ans = anchored[k["claim_id"]]
    ct = frozenset(mc.content_tokens(c["text"]))
    lab.append(int(r["relevance_0_1_2"]))
    soft.append(max(mc.best_recall(a["tokens"], [p]) for a in ans))
    n = mc.novel_answers(ans, ct)
    nov.append(max((mc.best_recall(t, [p]) for t in n), default=np.nan))
    arms.append(k["first_arm"])
lab, soft, nov = np.array(lab), np.array(soft), np.array(nov)
res = el.label_stats(lab, soft, nov)
rng = np.random.default_rng(42)
for name, s in (("all_answer_words", soft), ("novel_words_only", nov)):
    ok = ~np.isnan(s)
    l, s2 = lab[ok], s[ok]
    bs = []
    for _ in range(10000):
        i = rng.integers(0, len(l), len(l))
        if (l[i] == 2).any() and (l[i] < 2).any():
            bs.append(el.auc(s2[i][l[i] == 2], s2[i][l[i] < 2]))
    res[name]["auc_ci95"] = [float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))]
res["label_counts"] = {int(v): int((lab == v).sum()) for v in (0, 1, 2)}
res["label_counts_by_first_arm"] = {a: {int(v): int(((lab == v) & (np.array(arms) == a)).sum()) for v in (0, 1, 2)} for a in set(arms)}
json.dump(res, open("outputs/corpus_v1/relabel/relabel_scores.json", "w"), indent=1)
print(json.dumps(res, indent=1))
