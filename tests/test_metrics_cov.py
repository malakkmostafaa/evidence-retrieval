"""metrics_cov: (a) hand-computed cases, (b) golden test against the LEGACY functions (imported from the legacy folder in
this test only), (c) mutation checks were run by hand and are listed in docs/LOG.md."""
import importlib
import math
import random
import sys
import types

import numpy as np
import pytest

from evret import metrics_cov as mc
from evret.stats import paired_bootstrap

LEGACY_ROOT = r"C:\Users\malak\Desktop\Bachelor Thesis\legacy_retrieval_v1"


# ----------------------------------------------------------------------------------------------- (a) by hand
def test_content_tokens():
    assert mc.content_tokens("The Cats, and 5 dogs! Not_house") == ["cats", "5", "dogs", "house"]   # '_' separates; stop words gone
    assert mc.tokenize("The Cats") == ["the", "cats"]


def P(key, text, n, h=None):
    return mc.Passage(key, text, n, text if h is None else h)


def word_offsets(text):                                             # one token per word
    out, i = [], 0
    for w in text.split():
        j = text.index(w, i)
        out.append((j, j + len(w)))
        i = j + len(w)
    return out


def test_union_and_best_recall():
    ans = frozenset("ab bc cd de".split())
    ctx = [P("u1", "ab bc zz", 3), P("u2", "bc cd yy", 3)]
    assert mc.union_recall(ans, ctx) == 3 / 4                      # ab, bc, cd found anywhere
    assert mc.best_recall(ans, ctx) == 2 / 4                       # best single passage has two of four
    assert mc.union_recall(frozenset(), ctx) == 0.0 and mc.best_recall(ans, []) == 0.0


def test_build_context_fills_exactly_and_dedupes():
    r = [P("u", "w1 w2 w3 w4 w5", 5, 1), P("u", "w1 w2 w3 w4 w5", 5, 1), P("v", "x1 x2 x3 x4 x5", 5, 2),
         P("w", "y1 y2 y3 y4 y5", 5, 3)]
    ctx = mc.build_context(r, 12, word_offsets)                     # dup skipped; 5 + 5 whole, third cut to 2 tokens
    assert [p.text for p in ctx] == ["w1 w2 w3 w4 w5", "x1 x2 x3 x4 x5", "y1 y2"]
    assert sum(p.n_tokens for p in ctx) == 12
    c3 = mc.build_context(r, 3, word_offsets)
    assert len(c3) == 1 and c3[0].text == "w1 w2 w3"


def test_novel_answers_drop_claim_tokens_and_short_answers():
    claim = frozenset({"x"})
    a1 = {"tokens": frozenset("x a b c".split())}                   # novel {a,b,c}: 3 tokens, kept
    a2 = {"tokens": frozenset("x a b".split())}                     # novel {a,b}: 2 < 3, not scored
    assert mc.novel_answers([a1, a2], claim) == [frozenset("a b c".split())]


def test_source_metrics_by_hand():
    ranked = [P("o", "t", 1), P("g1", "t", 1), P("g1", "t", 1), P("o", "t", 1)]
    m = mc.source_metrics({"g1", "g2"}, ranked, (1, 2, 4))
    assert (m["source_hit@1"], m["source_hit@2"]) == (0.0, 1.0)
    assert m["source_recall@2"] == 0.5 and m["source_mrr"] == 0.5
    assert mc.source_metrics({"zz"}, ranked, (2,))["source_mrr"] == 0.0


def test_claim_row_and_nan_for_no_novel_answers():
    ans = [{"tokens": frozenset("ab bc cd de".split())}]
    ranked = [P("g", "ab bc cd xx", 4, 1), P("o", "de yy zz", 3, 2)]
    row = mc.claim_row(ans, {"g"}, ranked, 100, (1, 2), word_offsets, claim_tokens=frozenset("ab bc".split()))
    assert row["cov_union@B100"] == 1.0 and row["cov_union@1"] == 0.75 and row["answer_found@B100"] == 0.0
    assert row["n_novel_answers"] == 0 and math.isnan(row["cov_novel@B100"])        # novel {cd,de}: only 2 tokens
    row = mc.claim_row(ans, {"g"}, ranked, 100, (1, 2), word_offsets, claim_tokens=frozenset())
    assert row["n_novel_answers"] == 1 and row["cov_novel@1"] == 0.75 and row["ctx_gold_frac@B100"] == 4 / 7


def test_answer_text_gold_answers_and_anchoring():
    claim = {"questions": [{"answers": [
        {"answer": "Yes", "answer_type": "Boolean", "boolean_explanation": "the budget doubled in 2019",
         "source_url": "https://web.archive.org/web/2020/https://a.com/p"},
        {"answer": "No", "answer_type": "Boolean", "boolean_explanation": "", "source_url": "https://b.com/q"},
        {"answer": "five percent rise", "answer_type": "Extractive", "source_url": "https://c.com/r"}]}]}
    g = mc.gold_answers(claim)
    assert g[0]["tokens"] == frozenset({"budget", "doubled", "2019"}) and g[0]["scorable"]
    assert g[0]["url"] == "a.com/p"                                  # Wayback wrapper removed
    assert g[1]["tokens"] == frozenset() and not g[1]["scorable"]      # "No" is a stop word
    assert g[2]["scorable"] and len(g[2]["tokens"]) == 3             # five percent rise
    texts = {"a.com/p": ["the budget " + "pad " * 300 + "doubled in 2019"], "c.com/r": ["five percent rise seen"]}
    an = mc.anchor_claim(claim, texts)
    # a.com/p: 'budget' is 300+ tokens away from 'doubled' / '2019' (window 200): best window holds 2 of 3 tokens
    assert [x["anchored"] for x in an] == [False, False, True]
    assert math.isclose(an[0]["anchor_recall"], 2 / 3) and an[2]["anchor_recall"] == 1.0


def test_best_window_recall_by_hand():
    doc = ["a", "x", "x", "x", "b"]
    assert mc.best_window_recall(doc, frozenset({"a", "b"}), window=3) == 0.5       # a and b are 4 apart
    assert mc.best_window_recall(doc, frozenset({"a", "b"}), window=5) == 1.0
    assert mc.best_window_recall([], frozenset({"a"})) == 0.0


def test_paired_bootstrap_by_hand():
    r = paired_bootstrap([1, 1, 1, 0], [0, 0, 1, 0], n_boot=500)
    assert r["mean_diff"] == 0.5 and (r["wins"], r["ties"], r["losses"]) == (2, 2, 0)
    assert r["ci95.0"][0] <= 0.5 <= r["ci95.0"][1]


# ----------------------------------------------------------------------------------------------- (b) golden
@pytest.fixture(scope="module")
def legacy():
    """Import the legacy modules from the legacy folder. `src.utils.urls` is not in that folder, so a stub with the
    same job (URL normalisation) is injected; both implementations then use the same function."""
    saved = {k: v for k, v in sys.modules.items() if k == "src" or k.startswith("src.")}
    for k in saved:
        del sys.modules[k]
    sys.path.insert(0, LEGACY_ROOT)
    stub = types.ModuleType("src.utils.urls")
    stub.norm_url = lambda u: mc.canonical(u or "")
    try:
        sys.modules["src.utils"] = types.ModuleType("src.utils")
        sys.modules["src.utils.urls"] = stub
        yield types.SimpleNamespace(metrics=importlib.import_module("src.retrieval.metrics"),
                                    selection=importlib.import_module("src.retrieval.selection"),
                                    text=importlib.import_module("src.retrieval.text"),
                                    stats=importlib.import_module("src.retrieval.stats"))
    finally:
        sys.path.remove(LEGACY_ROOT)
        for k in [k for k in sys.modules if k == "src" or k.startswith("src.")]:
            del sys.modules[k]
        sys.modules.update(saved)


WORDS = "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi omicron pi rho sigma tau the of and".split()


def rtext(rng, n):
    return " ".join(rng.choice(WORDS) for _ in range(n))


class FakeTok:
    def offsets(self, texts):
        return [word_offsets(t) for t in texts]


def test_golden_text_and_answers(legacy):
    rng = random.Random(1)
    for _ in range(60):
        t = rtext(rng, rng.randint(0, 30)) + rng.choice(["", " 5%!", " Café_x"])
        assert mc.content_tokens(t) == legacy.text.content_tokens(t) and mc.tokenize(t) == legacy.text.tokenize(t)
    for _ in range(40):
        claim = {"questions": [{"answers": [
            {"answer": rtext(rng, rng.randint(0, 6)), "answer_type": rng.choice(["Boolean", "Extractive"]),
             "boolean_explanation": rtext(rng, rng.randint(0, 6)), "source_url": f"https://s{rng.randint(0, 3)}.com/p"}
            for _ in range(3)]}]}
        texts = {mc.canonical(f"https://s{i}.com/p"): [rtext(rng, 400), rtext(rng, 50)] for i in range(4)}
        assert mc.anchor_claim(claim, texts) == legacy.selection.anchor_claim(claim, texts)
        doc = [rng.choice(WORDS) for _ in range(300)]
        ans = frozenset(rng.sample(WORDS, 5))
        assert mc.best_window_recall(doc, ans) == legacy.selection.best_window_recall(doc, ans)
        assert mc.best_window_recall(doc, ans, 20) == legacy.selection.best_window_recall(doc, ans, 20)


def test_golden_metrics_and_claim_row(legacy):
    rng = random.Random(2)
    for case in range(60):
        n_p = rng.randint(0, 12)
        texts = [rtext(rng, rng.randint(1, 40)) for _ in range(n_p)]
        keys = [rng.randint(0, 4) for _ in range(n_p)]
        ntok = [len(t.split()) for t in texts]
        hashes = [rng.randint(0, 8) for _ in range(n_p)]                  # collisions on purpose: dedupe path
        new = [mc.Passage(k, t, n, h) for k, t, n, h in zip(keys, texts, ntok, hashes)]
        old = [legacy.metrics.Passage(k, t, n, h) for k, t, n, h in zip(keys, texts, ntok, hashes)]
        answers = [{"tokens": frozenset(rng.sample(WORDS, rng.randint(1, 6)))} for _ in range(rng.randint(1, 4))]
        claim_tok = frozenset(rng.sample(WORDS, rng.randint(0, 6)))
        gold = set(rng.sample(range(5), rng.randint(0, 3)))
        kw = dict(ks=(1, 3, 5), theta=0.8, claim_tokens=claim_tok, extra_budgets=(7, 25))
        for budget in (1, 10, 60, 5000):
            r_new = mc.claim_row(answers, gold, new, budget, offsets_fn=word_offsets, **kw)
            r_old = legacy.metrics.claim_row(answers, gold, old, budget, tok=FakeTok(), **kw)
            assert r_new.keys() == r_old.keys()
            for k in r_new:
                a, b = r_new[k], r_old[k]
                assert (math.isnan(a) and math.isnan(b)) or a == b, (case, budget, k, a, b)
        for B in (5, 30):
            cn = mc.build_context(new, B, word_offsets)
            co = legacy.metrics.build_context(old, B, FakeTok())
            assert [(p.text, p.n_tokens) for p in cn] == [(p.text, p.n_tokens) for p in co]


def test_golden_paired_bootstrap(legacy):
    rng = np.random.default_rng(3)
    a, b = rng.random(25), rng.random(25)
    assert paired_bootstrap(a, b, n_boot=300) == legacy.stats.paired_bootstrap(a, b, n_boot=300)
