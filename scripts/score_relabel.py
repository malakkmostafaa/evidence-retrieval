"""Score the returned labels with the rules fixed in docs/reports/corpus_tool_v1.md. Run ONLY after the labelled CSV is back.
Usage: python scripts/score_relabel.py <labelled.csv>"""
import csv, json, sys
import numpy as np
from evret import eval_labels as el, eval_pool as ev, metrics_cov as mc

root = "data/corpus_v1"
csv.field_size_limit(2**31 - 1)
import io, subprocess
raw = open(sys.argv[1], "rb").read()
try:                                           # Excel may re-save as cp1252: decode that way, take ONLY the labels from it
    txt = raw.decode("utf-8-sig")
except UnicodeDecodeError:
    txt = raw.decode("cp1252", errors="replace")
labels = {r["row"]: r["relevance_0_1_2"] for r in csv.DictReader(io.StringIO(txt, newline=""))}
# passages and claims come from the ORIGINAL sheet (git, the version written by make_relabel_sheet.py), not from the re-saved file
orig = subprocess.run(["git", "show", "0502d9b:outputs/corpus_v1/relabel/relabel_sheet_TO_LABEL.csv"], capture_output=True).stdout.decode("utf-8-sig")
rows = list(csv.DictReader(io.StringIO(orig, newline="")))
for r in rows:
    r["relevance_0_1_2"] = labels[r["row"]]
assert all(r["relevance_0_1_2"] in ("0", "1", "2") for r in rows) and len(rows) == 50
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

# Spearman bootstrap CIs (added after the first run; same seed/rules: resample passages, 10,000 draws)
rng = np.random.default_rng(43)
for name, s in (("all_answer_words", soft), ("novel_words_only", nov)):
    ok = ~np.isnan(s)
    l, s2 = lab[ok], s[ok]
    bs = []
    for _ in range(10000):
        i = rng.integers(0, len(l), len(l))
        if len(set(l[i])) > 1 and len(set(s2[i])) > 1:
            bs.append(el.spearman(l[i], s2[i]))
    res[name]["spearman_ci95"] = [float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))]
json.dump(res, open("outputs/corpus_v1/relabel/relabel_scores.json", "w"), indent=1)
print(json.dumps({k: v for k, v in res.items() if k.endswith("words") or k.endswith("only")}, indent=1))
