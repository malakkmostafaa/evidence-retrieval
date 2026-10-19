"""WS5 - numbers and the manual-review list from outputs/web_smoke/results.json.

usage: python -m evret.web.report_web outputs/web_smoke
Writes <dir>/summary.md (tables) and <dir>/manual_review.md.
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter, defaultdict

from evret.web.eval_web import load_results
from evret.audit import is_factcheck, normalize_url
from evret.urls import canonical

STEPS = ("search", "wayback", "fetch", "extract", "chunk", "embed", "select")


def pct(a, b):
    return f"{100 * a / b:.0f}%" if b else "-"


def funnel(rs):
    c = Counter()
    for r in rs:
        for u in r["urls"]:
            c["returned"] += 1
            c[u["removed"] or "kept"] += 1
            if u["wayback"] in ("found", "none", "error"):
                c["lookup_" + u["wayback"]] += 1
            if u["date_class"]:
                c["class_" + u["date_class"]] += 1
            if u["date_source"] and u["removed"] in (None, "dated_after", "date_unknown"):
                c["src_" + u["date_source"]] += 1
    return c


def summary(results):
    by = defaultdict(list)
    for r in results:
        by[r["cond"]].append(r)
    out = ["## Funnel (URLs over all claims; each URL counted once)\n"]
    conds = list(by)
    reasons = sorted({k for c in conds for k in funnel(by[c]) if not k.startswith(("lookup_", "class_", "src_", "returned"))} - {"kept"})
    out.append("| step | " + " | ".join(conds) + " |\n|---|" + "---|" * len(conds))
    fs = {c: funnel(by[c]) for c in conds}
    rows = ["returned"] + reasons + ["kept"]
    for k in rows:
        out.append(f"| {k} | " + " | ".join(f"{fs[c][k]} ({pct(fs[c][k], fs[c]['returned'])})" for c in conds) + " |")
    out.append("\n## Wayback coverage (URLs that reached the lookup)\n")
    out.append("| cond | looked up | snapshot found | none | error | dated <= | dated after | unknown |\n|---|---|---|---|---|---|---|---|")
    for c in conds:
        f = fs[c]
        n = f["lookup_found"] + f["lookup_none"] + f["lookup_error"]
        out.append(f"| {c} | {n} | {f['lookup_found']} ({pct(f['lookup_found'], n)}) | {f['lookup_none']} | {f['lookup_error']} | "
                   f"{f['class_dated_le']} | {f['class_dated_after']} | {f['class_unknown']} |")
    out.append("\n## Gold-URL hits (claims with >= 1 gold URL; n claims = %d per condition)\n" % len(by[conds[0]]))
    out.append("| cond | group | claims | in engine results | in fetched pages | in kept pages | top-5 | top-10 | top-50 |\n|---|---|---|---|---|---|---|---|---|")
    for c in conds:
        for g in ("pooled", "held-out", "all"):
            rs = [r for r in by[c] if g == "all" or r["group"] == g]
            n = len(rs)
            f = lambda k: sum(1 for r in rs if r["gold"][k])
            out.append(f"| {c} | {g} | {n} | {f('in_results')} | {f('in_fetched')} | {f('in_kept')} | {f('in_top5')} | {f('in_top10')} | {f('in_top50')} |")
    out.append("\nFate of every gold URL that the engine returned (main condition):\n")
    fate = Counter(v for r in by.get("main", []) for v in r["gold"]["gold_fate"].values())
    n_gold = sum(r["n_gold"] for r in by.get("main", []))
    out.append(f"{n_gold} gold URLs in total; returned by the engine: {sum(fate.values())}; fate: " + (", ".join(f"{k}: {v}" for k, v in fate.most_common()) or "-"))
    out.append("\n## Search outcome (queries)\n")
    for c in conds:
        ok = [r for r in by[c] if r["counts"]["returned"] > 0]
        out.append(f"- {c}: {len(ok)} of {len(by[c])} claim queries returned results; {len(by[c]) - len(ok)} returned no results (failed or empty answer): claims "
                   f"" + ", ".join(str(r["claim_id"]) for r in by[c] if r["counts"]["returned"] == 0))
    out.append("\n## Seconds per claim (main condition; cold = the claim's pages were not cached yet, i.e. Wayback time > 0.5 s)\n")
    rs = [r for r in by.get("main", []) if r["seconds"]["wayback"] > 0.5]
    if rs:
        tot = sum(r["wall_s"] for r in rs)
        out.append("| step | mean s/claim | share of step time |\n|---|---|---|")
        st = {s: sum(r["seconds"][s] for r in rs) / len(rs) for s in STEPS}
        ssum = sum(st.values())
        for s in STEPS:
            out.append(f"| {s} | {st[s]:.1f} | {pct(st[s], ssum)} |")
        out.append(f"| **total (wall)** | {tot / len(rs):.1f} | |")
        out.append(f"\nn = {len(rs)} cold claims (of {len(by['main'])}).")
        out.append(f"\nPassages per claim (mean): {sum(r['n_passages'] for r in rs) / len(rs):.1f}; claims with 0 passages: {sum(r['n_passages'] == 0 for r in rs)}.")
    return "\n".join(out)


def manual_review(results) -> str:
    out = ["# Manual review list\n", "Top-5 passages per claim (main condition), then every page kept by any condition that comes from a "
           "fact-check-looking domain or has date_source 'none'.\n"]
    main = [r for r in results if r["cond"] == "main"]
    for r in main:
        out.append(f"\n## claim {r['claim_id']} ({r['group']}, {r['label']}, date {r['claim_date']})\n")
        if not r["hits"]:
            out.append("_no passages (see funnel: " + ", ".join(f"{k}={v}" for k, v in r["counts"].items() if v and k != "returned") + ")_\n")
        for h in r["hits"][:5]:
            out.append(f"{h['rank']}. {h['url']}  [{h['pub_date'] or 'no date'} / {h['date_source']} / {h['fetched_from']}] "
                       f"hybrid={h['score']:.4f} dense={h['dense']:.3f} bm25={h['bm25']}\n   > " + h["text"][:400].replace("\n", " ") + "\n")
    out.append("\n## Pages kept in an ablation that the main condition removes\n")
    seen = set()
    for r in results:
        for u in r["urls"]:
            if u["removed"] is not None:
                continue
            fc = is_factcheck(normalize_url(u["url"])) or is_factcheck(canonical(u["url"]))
            if (fc or u["date_source"] == "none") and (r["claim_id"], u["url"]) not in seen:
                seen.add((r["claim_id"], u["url"]))
                out.append(f"- claim {r['claim_id']} [{r['cond']}] {u['url']}  ({'fact-check-looking' if fc else ''} date_source={u['date_source']}, "
                           f"pub_date={u['pub_date'] or '-'}, {u['n_chunks']} chunks)")
    return "\n".join(out)


def main(argv=None):
    d = (argv or sys.argv[1:])[0]
    results = load_results(d)
    open(os.path.join(d, "summary.md"), "w", encoding="utf-8").write(summary(results))
    open(os.path.join(d, "manual_review.md"), "w", encoding="utf-8").write(manual_review(results))
    print(summary(results))


if __name__ == "__main__":
    main()
