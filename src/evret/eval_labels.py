"""Regression test of the ported metrics against the 100 manual relevance labels of the earlier experiments (read-only
inputs in legacy_retrieval_v1/manual_labels). Evaluation-side module: it knows claims and gold answers.

Per labelled (claim, passage): soft_best = max over the claim's answers of best_recall(answer tokens, [passage]);
novel_best = the same over novel answers (claim tokens removed, >= MIN_ANSWER_TOKENS left; NaN if none).
Which answers count: "scorable" (>= 3 content tokens) or "anchored" (scorable AND found inside a 200-token window of the
cited page, which needs the page text: only available here for claims whose documents were written, i.e. pool claims).
"""
from __future__ import annotations

import csv
import glob
import json
import os

import numpy as np
import pyarrow.parquet as pq

from evret import metrics_cov as mc
from evret.ingest import decode_text
from evret.urls import canonical

LEGACY = r"C:\Users\malak\Desktop\Bachelor Thesis\legacy_retrieval_v1\manual_labels"


def load_rows(path: str | None = None) -> list[dict]:
    csv.field_size_limit(2**31 - 1)
    with open(path or os.path.join(LEGACY, "manual_vs_soft_overlap.csv"), encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["soft_saved"] = float(r["soft_best"]) if r["soft_best"] != "" else np.nan
        r["novel_saved"] = float(r["novel_best"]) if r["novel_best"] != "" else np.nan
        r["label"] = int(r["relevance_0_1_2"])
    return rows


def page_texts(corpus: str, urls: set[str]) -> dict[str, list[str]]:
    """canonical URL -> texts of all stored documents under that URL (pool documents only)."""
    idx = pq.read_table(os.path.join(corpus, "doc_index_pool.parquet"),
                        columns=["doc_id", "norm_url", "min_rank", "is_empty"]).to_pydict()
    want: dict[int, str] = {}
    for did, nu, mr, emp in zip(idx["doc_id"], idx["norm_url"], idx["min_rank"], idx["is_empty"]):
        c = canonical(nu)
        if c in urls and not emp:
            want[did] = (c, mr)
    out: dict[str, list[str]] = {}
    by_rank: dict[int, list[int]] = {}
    for did, (c, mr) in want.items():
        by_rank.setdefault(mr, []).append(did)
    for mr, dids in by_rank.items():
        f = glob.glob(os.path.join(corpus, "documents", "band=*", f"rank_{mr:03d}.parquet"))[0]
        t = pq.read_table(f, columns=["doc_id", "text_utf8"])
        ids = t.column("doc_id").to_pylist()
        for d in dids:
            out.setdefault(want[d][0], []).append(decode_text(t.column("text_utf8")[ids.index(d)].as_py()))
    return out


def score_rows(rows, dev, answers_for_claim) -> np.ndarray:
    """-> array [n, 2] of (soft_best, novel_best) for the ported code. answers_for_claim(claim_id) -> list of answer dicts
    or None (not computable)."""
    out = np.full((len(rows), 2), np.nan)
    for i, r in enumerate(rows):
        ans = answers_for_claim(int(r["claim_id"]))
        if ans is None:
            continue
        p = mc.Passage("x", r["passage"], 0, 0)
        ct = frozenset(mc.content_tokens(r["claim"]))
        out[i, 0] = max((mc.best_recall(a["tokens"], [p]) for a in ans), default=np.nan)
        out[i, 1] = max((mc.best_recall(t, [p]) for t in mc.novel_answers(ans, ct)), default=np.nan)
    return out


# ---------------------------------------------------------------------------------------------- statistics (numpy)
def auc(pos_scores, neg_scores) -> float:
    """Mann-Whitney AUC with ties counted 1/2."""
    pos, neg = np.asarray(pos_scores, float), np.asarray(neg_scores, float)
    gt = (pos[:, None] > neg[None, :]).sum() + 0.5 * (pos[:, None] == neg[None, :]).sum()
    return float(gt / (len(pos) * len(neg)))


def rankdata(x) -> np.ndarray:
    x = np.asarray(x, float)
    order = np.argsort(x, kind="mergesort")
    ranks = np.empty(len(x))
    i = 0
    while i < len(x):
        j = i
        while j + 1 < len(x) and x[order[j + 1]] == x[order[i]]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def spearman(x, y) -> float:
    rx, ry = rankdata(x), rankdata(y)
    return float(np.corrcoef(rx, ry)[0, 1])


def label_stats(labels, soft, novel) -> dict:
    """AUCs and Spearman as reported in amendment A1. The 'all answer words' score is defined for every row; the 'novel
    words only' score is undefined (NaN) when no answer has >= 3 novel tokens and those rows are DROPPED (this reproduces the
    reported 0.75 / 0.71 / 0.44 from the saved values; scoring them 0 gives 0.72 / 0.68 / 0.38)."""
    labels = np.asarray(labels)
    out = {}
    for name, sc in (("all_answer_words", np.asarray(soft, float)), ("novel_words_only", np.asarray(novel, float))):
        k = ~np.isnan(sc)
        l, s = labels[k], sc[k]
        out[name] = {"auc_2_vs_01": auc(s[l == 2], s[l < 2]), "auc_ge1_vs_0": auc(s[l >= 1], s[l == 0]),
                     "spearman_3level": spearman(l, s), "n": int(k.sum())}
    return out
