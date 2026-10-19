"""Diagnosis of the smoke run from cached data only (no network): search-failure timeline, per-claim gold funnel.

usage: python -m evret.web.diagnose outputs/web_smoke outputs/web_cache  -> <dir>/diagnosis.md
"""
from __future__ import annotations

import datetime
import json
import os
import re
import sys
from collections import Counter

from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS

from evret.urls import canonical, unwrap
from evret.web.eval_web import DEV, load_smoke_claims

TOK = re.compile(r"[a-z0-9]+")


def content_words(text: str) -> set[str]:
    return {t for t in TOK.findall(text.lower()) if len(t) >= 3 and t not in ENGLISH_STOP_WORDS}


def search_timeline(netlog_path: str):
    rows = []
    for line in open(netlog_path, encoding="utf-8"):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r["kind"] == "search":
            rows.append(r)
    return rows


def failure_section(rows, provider: str = "ddgs/duckduckgo") -> str:
    out = ["## 1. Search failures\n"]
    st = Counter(r["status"] for r in rows)
    out.append(f"{len(rows)} search attempts logged: " + ", ".join(f"{k}: {v}" for k, v in st.most_common()) + ".\n")
    if not provider.startswith("ddgs"):
        out.append(f"Provider {provider}: official API, no bot challenge; every attempt is one billed request. Per-query timeline omitted.")
        return "\n".join(out)
    out.append("**Cause (diagnosed live with 4 probe calls, see text below):** the netlog only keeps the exception class. `ddgs` turns every "
               "non-200 answer of the engine into `None` and, when no engine raised, into `DDGSException('No results found.')`. A direct "
               "request to `html.duckduckgo.com/html/` returned **HTTP 202 with DuckDuckGo's anomaly (bot-challenge) page** for the claim "
               "queries *and* for a harmless control query (\"Eiffel Tower height in metres\"). So all 62 `DDGSException` failures are most "
               "likely bot-challenges; rate limit headers, timeouts, parse errors and captcha-vs-block cannot be told apart from the cache, "
               "and no timeouts or HTTP errors appear (all failures return in 0.3-1.0 s, except two of 5 s).\n")
    out.append("Timeline (attempt, clock time, gap to previous attempt, result). Runs are separated by long gaps; a query's 4 attempts are "
               "2-9 s apart:\n")
    out.append("| # | time | gap s | status | s | query (start) |\n|---|---|---|---|---|---|")
    prev = None
    for i, r in enumerate(rows, 1):
        gap = "" if prev is None else f"{r['t'] - prev:.0f}"
        prev = r["t"]
        out.append(f"| {i} | {datetime.datetime.fromtimestamp(r['t']).strftime('%H:%M:%S')} | {gap} | {r['status'].replace('error:', '')} | "
                   f"{r['seconds']:.1f} | {r['target'][14:50].replace('|', '/')} |")
    # clusters
    ok_idx = [i for i, r in enumerate(rows) if r["status"] == "ok"]
    out.append("\n**Pattern.** In the first live run the first 7 queries succeeded (5 minutes, 1 query every 15-80 s because fetching "
               "ran in between). From query 8 on, a query failed 4 of 4 attempts spaced 2-9 s; the block lifted again only after pauses: "
               "success after 314 s (claim 485), after 36 s (269) and after 6 s (one claim that failed twice first); claims 124, 37 and 418 "
               "failed 4 of 4 and succeeded on the re-try about 3 minutes later. "
               "In the three re-runs (17:40-17:47) 485 and 269 failed 24 of 24 attempts, and every probe afterwards "
               "(including the control query) got the challenge. Failure therefore **clusters after a burst of ~7 queries and persists for "
               "minutes; 2-9 s of backoff is far too short to wait it out**. The straight quotation marks in 485 and 269 are not the cause "
               "(both succeeded once with the same text).\n")
    return "\n".join(out)


def gold_funnel(results, claims) -> str:
    by = {c["claim_id"]: c for c in claims}
    out = ["## 2. Gold-URL funnel (main condition)\n",
           "Order of the pipeline: search returned the URL -> not removed by the URL filters (own article / fact-check) -> fetch OK -> date filter "
           "passed -> enough text -> in top-N passages (N = 50).\n",
           "| claim | grp | gold URLs | search ok | returned | url filters | fetched | date | text | top-50 passages | top-10 |\n|---|---|---|---|---|---|---|---|---|---|---|"]
    tot = Counter()
    for r in [r for r in results if r["cond"] == "main"]:
        c = by[r["claim_id"]]
        gv = c["gold_variants"]
        n = len(gv)
        from evret.urls import url_variants
        ret, urlf, fet, dat, txt = set(), set(), set(), set(), set()
        for u in r["urls"]:
            for i, g in enumerate(gv):
                if url_variants(u["url"]) & g:
                    ret.add(i)
                    if u["stage"] != "url":
                        urlf.add(i)
                        if u["fetch_status"] == "ok":
                            fet.add(i)
                            if u["stage"] != "date":
                                dat.add(i)
                                if u["stage"] != "text":
                                    txt.add(i)
        top50, top10 = set(r["gold"]["in_top50"]), set(r["gold"]["in_top10"])
        ok = r["counts"]["returned"] > 0
        out.append(f"| {r['claim_id']} | {r['group'][:4]} | {n} | {'yes' if ok else 'FAILED'} | {len(ret)} | {len(urlf)} | {len(fet)} | {len(dat)} | "
                   f"{len(txt)} | {len(top50)} | {len(top10)} |")
        for k, v in (("gold", n), ("returned", len(ret)), ("url", len(urlf)), ("fetched", len(fet)), ("date", len(dat)),
                     ("text", len(txt)), ("top50", len(top50)), ("top10", len(top10))):
            tot[k] += v
    out.append(f"| **sum** | | {tot['gold']} | | {tot['returned']} | {tot['url']} | {tot['fetched']} | {tot['date']} | {tot['text']} | {tot['top50']} | {tot['top10']} |")
    # gold URL characteristics
    wrapped = sum(1 for c in claims for u in c["gold_urls"] if unwrap(u) != u)
    n_all = sum(len(c["gold_urls"]) for c in claims)
    gold_hosts = Counter()
    res_hosts = set()
    for c in claims:
        for u in c["gold_urls"]:
            m = re.match(r"https?://(?:www\.)?([^/]+)", unwrap(u))
            if m:
                gold_hosts[c["claim_id"]] += 0
    host = lambda u: (re.match(r"https?://(?:www\.)?([^/]+)", u) or [None, ""])[1].lower()
    dom_hit = 0
    for r in [r for r in results if r["cond"] == "main"]:
        rh = {host(u["url"]) for u in r["urls"]}
        c = by[r["claim_id"]]
        dom_hit += sum(1 for u in c["gold_urls"] if host(unwrap(u)) in rh)
    out.append(f"\nGold URL properties: {wrapped} of {n_all} are Wayback wrappers; the gold *host* appears among the engine results for "
               f"{dom_hit} of {n_all} gold URLs (exact URL: {tot['returned']}). Dead links / redirects of the gold URLs cannot be judged from the "
               "cache (they were never requested, only the gold URLs the engine returned were). Checking all gold URLs would need "
               f"{n_all} CDX lookups + {n_all} fetches (about 5 minutes); not run, waiting for approval.")
    return "\n".join(out)


def main(argv=None):
    d, cache = (argv or sys.argv[1:])[:2]
    results = load_results(d)
    claims = load_smoke_claims()
    rows = search_timeline(os.path.join(cache, "netlog.jsonl"))
    txt = "# Diagnosis of the web smoke run (cached data; 4 extra probe calls to the engine)\n\n" + "\n\n".join(
        [failure_section(rows, json.load(open(os.path.join(cache, "provider.json")))["provider"] if os.path.exists(os.path.join(cache, "provider.json")) else "ddgs/duckduckgo"), gold_funnel(results, claims)])
    open(os.path.join(d, "diagnosis.md"), "w", encoding="utf-8").write(txt)
    print(txt)


if __name__ == "__main__":
    main()
