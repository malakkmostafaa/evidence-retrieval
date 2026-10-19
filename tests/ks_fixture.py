"""Tiny synthetic knowledge store (6 claims) used by the ingest tests. Written by hand; expectations in the tests.

Documents (url, text) and the stores that contain them (claim ids):
  A  a.example/x   "alpha ..."            claims 0 (twice), 3   (shared document)
  B  b.example/y   "beta ..."             claim 1  (url2text is a list of items joined with "\\n")
  C  c.example/z   text with U+2028, NUL, non-BMP, lone surrogate     claims 2, 4
  D  d.example/w   "delta ..."            claim 5 only
  E  e.example/v   "" (empty)             claims 0 and 1
  A2 a.example/x   different text, same URL as A     claim 3
  F  f.example/p.pdf  text starting with "%PDF-"     claim 2
  G  snopes.com/fact-check/q  short "g"   claim 1  (tiny, factcheck)
"""
import json
import os
import zipfile

TEXT = {
    "A": "alpha alpha alpha " * 20,
    "B": "beta beta. Second sentence.\nNew line " * 20,
    "C": "café line sep \x00nul \U0001F600 emoji \ud800 lone " * 10,
    "D": "delta " * 50,
    "E": "",
    "A2": "alpha but a different version " * 20,
    "F": "%PDF-1.4 binary-ish text " * 20,
    "G": "g",
}
URL = {"A": "https://www.a.example/x/", "B": "http://b.example/y", "C": "https://c.example/z?utm_source=t",
       "D": "https://d.example/w", "E": "https://e.example/v", "A2": "https://a.example/x",
       "F": "https://f.example/p.pdf", "G": "https://snopes.com/fact-check/q"}
STORES = {0: ["A", "A", "E"], 1: ["B", "E", "G"], 2: ["C", "F"], 3: ["A", "A2"], 4: ["C"], 5: ["D"]}
LABELS = {0: "Refuted", 1: "Supported", 2: "Refuted", 3: "Supported", 4: "Refuted", 5: "Supported"}


def rec(cid, doc, typ="question", i=0):
    t = TEXT[doc]
    return {"claim_id": cid, "type": typ, "query": f"q{cid}-{i}", "url": URL[doc],
            "url2text": t.split("\n") if doc == "B" else [t]}


def joined(doc):
    """The text the ingest must produce: url2text items joined with '\\n'."""
    return "\n".join(rec(0, doc)["url2text"])


def build(root):
    zdir = os.path.join(root, "zips")
    os.makedirs(zdir, exist_ok=True)
    for part, cids in (("part1", [0, 1, 2]), ("part2", [3, 4, 5])):
        with zipfile.ZipFile(os.path.join(zdir, f"{part}.zip"), "w", zipfile.ZIP_DEFLATED) as zf:
            for cid in cids:
                lines = [json.dumps(rec(cid, d, i=i)) for i, d in enumerate(STORES[cid])]
                zf.writestr(f"store/{cid}.json", ("\n".join(lines) + "\n").encode("utf-8"))
    dev = [{"label": LABELS[c], "claim_date": "1-1-2020", "questions": []} for c in range(6)]
    with open(os.path.join(root, "dev.json"), "w", encoding="utf-8") as f:
        json.dump(dev, f)
    with open(os.path.join(root, "subsets.json"), "w", encoding="utf-8") as f:
        json.dump({"dev300": list(range(6))}, f)
    return zdir, os.path.join(root, "dev.json"), os.path.join(root, "subsets.json")
