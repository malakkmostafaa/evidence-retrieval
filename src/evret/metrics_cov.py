"""Answer-coverage metrics (CovUnion, CovNovel, AnswerRecall, SourceHit/Recall/MRR) - SHARED METRICS MODULE.

Ported from legacy_retrieval_v1/src/retrieval/{metrics,text,selection}.py with IDENTICAL LOGIC. Only these things changed:
  * imports (no `src.*` packages);
  * a passage is identified by `doc_key` = canonical URL (evret.urls.canonical) instead of the old `doc_ord`;
  * `build_context` takes an `offsets_fn(text) -> [(start, end), ...]` (token character offsets, no special tokens)
    instead of a tokenizer object;
  * URL normalisation for gold answers uses evret.urls.canonical (Wayback-aware) instead of the old `norm_url`;
  * the anchoring helpers take the page texts as input exactly as the legacy `anchor_claim` did.
Do not change the constants or the arithmetic without a new DECISIONS entry; tests/test_metrics_cov.py compares this
module with the legacy functions on identical inputs.

Notation: G(c) = gold pages of claim c. A(c) = anchored gold answers of c ("answers" below: dicts with a 'tokens'
frozenset). T(a) = distinct content tokens of answer a. ranked = passages in retrieval order.
  SourceHit@k / SourceRecall@k / SourceMRR   page level: do the first k passages come from G(c)?
  AnswerRecall@k   share of answers for which ONE of the first k passages holds >= THETA (0.8) of T(a)
  CovUnion@B       mean over answers of |T(a) ∩ tokens(context)| / |T(a)|, context = top passages up to B tokens
  CovNovel@B       the same with T(a) minus the claim's own content tokens (amendment A1); answers with fewer than
                   MIN_ANSWER_TOKENS novel tokens are not scored (NaN if none)
"""
from __future__ import annotations

import re
from collections import defaultdict

import numpy as np

from evret.urls import canonical

THETA = 0.8
MIN_ANSWER_TOKENS = 3
ANCHOR_WINDOW = 200
ANCHOR_THETA = 0.8

# ------------------------------------------------------------------------------------------ text (legacy text.py)
_SURROGATE = re.compile("[" + chr(0xD800) + "-" + chr(0xDFFF) + "]")
_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
STOPWORDS = frozenset("""a an the and or but if of to in on at by for with from as is are was were be been being it its
this that these those he she they we you i his her their our your not no do does did have has had will would can could
should may might than then so such there here which who whom whose what when where why how about into over after before
between during against up down out off again further once only own same too very s t just also""".split())


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def content_tokens(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in STOPWORDS]


# ------------------------------------------------------------------------------------------ gold answers (selection.py)
def answer_text(a: dict) -> str:
    """Boolean answers are just Yes/No; their content is in `boolean_explanation`."""
    if a.get("answer_type") == "Boolean" and (a.get("boolean_explanation") or "").strip():
        return a["boolean_explanation"]
    return a.get("answer") or ""


def gold_answers(claim: dict) -> list[dict]:
    out = []
    for qi, q in enumerate(claim.get("questions") or []):
        for ai, a in enumerate(q.get("answers") or []):
            toks = frozenset(content_tokens(answer_text(a)))
            out.append({"q": qi, "a": ai, "type": a.get("answer_type"), "tokens": toks,
                        "scorable": len(toks) >= MIN_ANSWER_TOKENS, "url": canonical(a.get("source_url") or "")})
    return out


def best_window_recall(doc_tokens: list[str], ans: frozenset, window: int = ANCHOR_WINDOW) -> float:
    """max over windows of `window` consecutive tokens of |ans ∩ tokens in window| / |ans|."""
    if not ans:
        return 0.0
    pos = [(i, t) for i, t in enumerate(doc_tokens) if t in ans]
    cnt, covered, left, best = defaultdict(int), 0, 0, 0
    for right in range(len(pos)):
        t = pos[right][1]
        if cnt[t] == 0:
            covered += 1
        cnt[t] += 1
        while pos[right][0] - pos[left][0] >= window:
            u = pos[left][1]
            cnt[u] -= 1
            if cnt[u] == 0:
                covered -= 1
            left += 1
        best = max(best, covered)
    return best / len(ans)


def anchor_claim(claim: dict, texts_by_url: dict[str, list[str]], window=ANCHOR_WINDOW, theta=ANCHOR_THETA) -> list[dict]:
    """-> gold answers annotated with 'anchor_recall' and 'anchored'. texts_by_url: canonical URL -> page texts."""
    cache: dict[str, list[list[str]]] = {}
    res = []
    for g in gold_answers(claim):
        g = dict(g)
        r = 0.0
        if g["scorable"]:
            for u in [g["url"]] if g["url"] else []:
                if u not in cache:
                    cache[u] = [tokenize(t) for t in texts_by_url.get(u, [])]
                for dt in cache[u]:
                    r = max(r, best_window_recall(dt, g["tokens"], window))
        g["anchor_recall"] = r
        g["anchored"] = bool(g["scorable"] and r >= theta)
        res.append(g)
    return res


# ------------------------------------------------------------------------------------------ metrics (metrics.py)
class Passage:
    __slots__ = ("doc_key", "text", "n_tokens", "hash", "_set")

    def __init__(self, doc_key, text, n_tokens, text_hash):
        self.doc_key, self.text, self.n_tokens, self.hash, self._set = doc_key, text, n_tokens, text_hash, None

    @property
    def tokens(self) -> frozenset:
        if self._set is None:
            self._set = frozenset(content_tokens(self.text))
        return self._set


def clean_for_tokenizer(s: str) -> str:
    """Lone surrogates cannot be encoded by the tokenizer; replace them by U+FFFD (same length, offsets unchanged)."""
    return s if s.isascii() else _SURROGATE.sub("�", s)


def passage_from_hit(hit, count_tokens) -> Passage:
    """Search-tool Hit -> Passage. `count_tokens(text)` = number of tokens WITHOUT special tokens (as in the legacy
    code). The key is the canonical URL, so a Wayback-wrapped copy and the original count as the same page."""
    return Passage(canonical(hit.url), hit.text, count_tokens(hit.text), hash(hit.text))


def build_context(ranked: list[Passage], budget: int, offsets_fn=None, dedupe: bool = True) -> list[Passage]:
    """Fill exactly `budget` tokens (if enough text exists): whole passages in rank order, last one truncated at a token
    boundary. Passages with identical text (same hash) are used once."""
    ctx, used, seen = [], 0, set()
    for p in ranked:
        if used >= budget:
            break
        if dedupe and p.hash in seen:
            continue
        seen.add(p.hash)
        room = budget - used
        if p.n_tokens <= room:
            ctx.append(p)
            used += p.n_tokens
        else:
            offs = offsets_fn(p.text)
            cut = offs[room - 1][1] if room <= len(offs) else len(p.text)
            ctx.append(Passage(p.doc_key, p.text[:cut], room, -1))
            used += room
    return ctx


def union_recall(ans: frozenset, ctx: list[Passage]) -> float:
    if not ans:
        return 0.0
    have = set()
    for p in ctx:
        have |= p.tokens
    return len(ans & have) / len(ans)


def best_recall(ans: frozenset, ctx: list[Passage]) -> float:
    return max((len(ans & p.tokens) / len(ans) for p in ctx), default=0.0) if ans else 0.0


def passage_metrics(anchored: list[dict], ctx: list[Passage], theta: float = THETA) -> dict:
    n = len(anchored)
    cov = float(np.mean([union_recall(a["tokens"], ctx) for a in anchored]))
    found = float(np.mean([best_recall(a["tokens"], ctx) >= theta for a in anchored]))
    return {"cov_union": cov, "answer_found": found, "ctx_tokens": int(sum(p.n_tokens for p in ctx)), "n_answers": n}


def source_metrics(gold_docs: set, ranked: list[Passage], ks=(5, 10)) -> dict:
    out = {}
    for k in ks:
        top = ranked[:k]
        docs = {p.doc_key for p in top}
        out[f"source_hit@{k}"] = float(bool(docs & gold_docs))
        out[f"source_recall@{k}"] = len(docs & gold_docs) / len(gold_docs) if gold_docs else 0.0
    rr = 0.0
    for r, p in enumerate(ranked, 1):
        if p.doc_key in gold_docs:
            rr = 1.0 / r
            break
    out["source_mrr"] = rr
    return out


def novel_answers(anchored: list[dict], claim_tokens: frozenset) -> list[frozenset]:
    """Amendment A1: answer tokens that are NOT in the claim. Answers with fewer than MIN_ANSWER_TOKENS novel tokens
    are not scored by the novel metric."""
    out = [frozenset(a["tokens"]) - claim_tokens for a in anchored]
    return [t for t in out if len(t) >= MIN_ANSWER_TOKENS]


def _mean_cov(sets: list[frozenset], ctx: list) -> float:
    return float(np.mean([union_recall(t, ctx) for t in sets])) if sets else float("nan")


def claim_row(anchored, gold_docs, ranked, budget, ks, offsets_fn, theta=THETA, claim_tokens=frozenset(),
              extra_budgets=(), src_ks=None) -> dict:
    row = dict(source_metrics(gold_docs, ranked, tuple(src_ks) if src_ks else ks))
    ctx = build_context(ranked, budget, offsets_fn)
    for k, v in passage_metrics(anchored, ctx, theta).items():
        row[f"{k}@B{budget}"] = v
    row[f"source_hit@B{budget}"] = float(bool({p.doc_key for p in ctx} & gold_docs))
    nov = novel_answers(anchored, frozenset(claim_tokens))
    row["n_novel_answers"] = len(nov)
    row[f"cov_novel@B{budget}"] = _mean_cov(nov, ctx)
    tot = sum(p.n_tokens for p in ctx)
    row[f"ctx_gold_frac@B{budget}"] = (sum(p.n_tokens for p in ctx if p.doc_key in gold_docs) / tot) if tot else 0.0
    for B in extra_budgets:                                   # budget sensitivity (A3)
        cB = build_context(ranked, B, offsets_fn)
        row[f"cov_union@B{B}"] = float(np.mean([union_recall(a["tokens"], cB) for a in anchored]))
        row[f"cov_novel@B{B}"] = _mean_cov(nov, cB)
    for k in ks:
        top = ranked[:k]
        m = passage_metrics(anchored, top, theta)
        row[f"answer_recall@{k}"] = m["answer_found"]
        row[f"cov_union@{k}"] = m["cov_union"]
        row[f"cov_novel@{k}"] = _mean_cov(nov, top)
        row[f"ctx_tokens@{k}"] = m["ctx_tokens"]
    return row


def gold_keys(claim_gold_urls) -> set:
    """Canonical keys of a claim's gold URLs (for source_metrics)."""
    return {canonical(u) for u in claim_gold_urls if u}
