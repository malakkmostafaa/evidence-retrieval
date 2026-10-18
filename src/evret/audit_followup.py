"""Block 1b - second pass over the Block 1 audit output (no ZIP access; runs in seconds).

Block 1 counted duplicates as RECORDS. Chunk counts and disk use depend on CHARACTERS, so this pass converts
the duplicate analysis into characters. It also answers two questions the first pass raised:
  (1) how much text is left after exact de-duplication, and how much of it lies beyond the old 100k cap?
  (2) are the records of type 'gold' exactly the annotators' evidence URLs listed in dev.json?
And it tabulates the query 'type' values (records, empty share, size, and the text that ONLY that type
reaches), because the leakage policy of Block 2 depends on which types are derived from gold annotations.

Usage (repo root, venv active):
    python -m evret.audit_followup --audit-dir outputs\\block01_audit --dev "C:\\...\\dev.json"

Reads   <audit-dir>/audit_per_record.csv.gz   (written by Block 1)   [+ dev.json for the gold check]
Writes  <audit-dir>/audit_followup.json and audit_followup.md

Nothing is removed from any data. 'Unique' means 'first occurrence of an exact (normalised URL, text) pair'.
Projections (chunks, GB) are ASSUMPTIONS, labelled as such; they are replaced by measurements in later blocks.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import os
import sys
from collections import Counter, defaultdict

from evret.audit import OLD_CAP_CHARS, load_dev, normalize_url

CHARS_PER_CHUNK_DEFAULT = 746   # previous build: 2.29e9 chars -> 3.07e6 chunks (ASSUMES the same chunker settings)
EMBED_DIM_DEFAULT = 384         # provisional (BGE-small); float16 = 2 bytes per number


def read_records(path: str):
    csv.field_size_limit(2**31 - 1)           # sys.maxsize overflows on Windows
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        yield from csv.DictReader(f)


def followup(audit_dir: str, dev_path: str | None = None, chars_per_chunk: int = CHARS_PER_CHUNK_DEFAULT,
             dim: int = EMBED_DIM_DEFAULT) -> dict:
    path = os.path.join(audit_dir, "audit_per_record.csv.gz")
    keys: dict[tuple[str, str], list] = {}        # (norm_url, text hash) -> [n_chars, is_pdf, is_empty, {types}]
    type_acc: dict[str, Counter] = defaultdict(Counter)
    gold_type_urls: dict[int, set[str]] = defaultdict(set)
    claims_seen: set[int] = set()
    raw_records = raw_chars_nonempty = 0

    for r in read_records(path):
        n, pdf, empty, t = int(r["n_chars"]), r["is_pdf"] == "1", r["is_empty"] == "1", r["type"]
        cid = int(r["claim_id_file"])
        claims_seen.add(cid)
        raw_records += 1
        raw_chars_nonempty += 0 if empty else n
        acc = type_acc[t]
        acc["records"] += 1
        acc["empty"] += empty
        acc["chars"] += 0 if empty else n
        k = (r["norm_url"], r["content_hash"])
        e = keys.get(k)
        if e is None:
            keys[k] = [n, pdf, empty, {t}]
        else:
            e[3].add(t)
        if t == "gold":
            gold_type_urls[cid].add(r["norm_url"])

    # ---- (1) size after exact de-duplication
    nonempty = [e for e in keys.values() if not e[2]]
    u_chars = sum(e[0] for e in nonempty)
    u_pdf = sum(e[0] for e in nonempty if e[1])
    u_beyond = sum(max(0, e[0] - OLD_CAP_CHARS) for e in nonempty)
    by_text: dict[str, int] = {}
    for (_, h), e in keys.items():
        if not e[2] and h not in by_text:
            by_text[h] = e[0]
    text_unique_chars = sum(by_text.values())

    def proj(chars: int) -> dict:
        chunks = int(round(chars / chars_per_chunk))
        return {"chars": chars, "chunks": chunks, "float16_vectors_gb": round(chunks * dim * 2 / 1e9, 2)}

    size = {
        "raw_records": raw_records, "raw_chars_nonempty": raw_chars_nonempty,
        "unique_keys_(url,text)": len(keys), "unique_nonempty_keys": len(nonempty),
        "unique_chars": u_chars, "unique_pdf_chars": u_pdf, "unique_web_chars": u_chars - u_pdf,
        "unique_pdf_share": round(u_pdf / u_chars, 4) if u_chars else None,
        "dedup_removed_char_share": round(1 - u_chars / raw_chars_nonempty, 4) if raw_chars_nonempty else None,
        "unique_chars_beyond_old_cap": u_beyond,
        "unique_chars_beyond_old_cap_share": round(u_beyond / u_chars, 4) if u_chars else None,
        "unique_chars_if_identical_texts_under_different_urls_also_merged": text_unique_chars,
        "assumptions": {"chars_per_chunk": chars_per_chunk, "embedding_dim": dim,
                        "note": "ASSUMPTION: previous build's chars-per-chunk ratio; replaced by a measurement in Block 4"},
        "projection_upper_(url,text)_unique": proj(u_chars),
        "projection_lower_(text)_unique": proj(text_unique_chars),
    }

    # ---- query types, including the text only that type reaches
    excl: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for e in nonempty:
        if len(e[3]) == 1:
            (t,) = tuple(e[3])
            excl[t][0] += 1
            excl[t][1] += e[0]
    types = {}
    for t, acc in sorted(type_acc.items(), key=lambda kv: -kv[1]["records"]):
        ne = acc["records"] - acc["empty"]
        types[t] = {"records": acc["records"], "empty_share": round(acc["empty"] / acc["records"], 4),
                    "mean_chars_nonempty": round(acc["chars"] / ne, 1) if ne else None,
                    "share_of_raw_chars": round(acc["chars"] / raw_chars_nonempty, 4) if raw_chars_nonempty else None,
                    "exclusive_nonempty_keys": excl[t][0], "exclusive_chars": excl[t][1],
                    "exclusive_share_of_unique_chars": round(excl[t][1] / u_chars, 4) if u_chars else None}

    # ---- (2) are 'gold'-type records exactly the dev.json gold URLs?
    gold = None
    if dev_path:
        c: Counter = Counter()
        examples = []
        for claim in load_dev(dev_path):
            cid = claim["claim_id"]
            if cid not in claims_seen:
                continue
            dev_urls = {normalize_url(u) for u in claim["gold_urls"] if u}
            typ = gold_type_urls.get(cid, set())
            c["claims_compared"] += 1
            if typ == dev_urls:
                c["exact_match"] += 1
            else:
                c["mismatch"] += 1
                c["dev_urls_without_gold_type_record"] += len(dev_urls - typ)
                c["gold_type_urls_not_in_dev"] += len(typ - dev_urls)
                if len(examples) < 10:
                    examples.append({"claim_id": cid, "dev_only": sorted(dev_urls - typ)[:3],
                                     "gold_type_only": sorted(typ - dev_urls)[:3]})
        gold = {**{k: c.get(k, 0) for k in ("claims_compared", "exact_match", "mismatch",
                                            "dev_urls_without_gold_type_record", "gold_type_urls_not_in_dev")},
                "mismatch_examples": examples}

    summary = {"block": "01b_followup", "audit_dir": audit_dir, "size_after_dedup": size,
               "query_types": types, "gold_type_vs_dev_json": gold}
    with open(os.path.join(audit_dir, "audit_followup.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    with open(os.path.join(audit_dir, "audit_followup.md"), "w", encoding="utf-8") as f:
        f.write(render(summary))
    return summary


def render(s: dict) -> str:
    z = s["size_after_dedup"]
    out = ["# Block 1b - size after de-duplication, query types, gold check", "",
           "## Size", f"- raw non-empty characters: {z['raw_chars_nonempty']:,}",
           f"- unique (url, text) characters: {z['unique_chars']:,} "
           f"({z['dedup_removed_char_share']} of raw removed by exact de-duplication)",
           f"- of which PDF: {z['unique_pdf_chars']:,} ({z['unique_pdf_share']}); "
           f"beyond the old 100k cap: {z['unique_chars_beyond_old_cap']:,} ({z['unique_chars_beyond_old_cap_share']})",
           f"- if identical texts under different URLs are also merged: {z['unique_chars_if_identical_texts_under_different_urls_also_merged']:,}",
           f"- PROJECTION (assumes {z['assumptions']['chars_per_chunk']} chars/chunk, "
           f"{z['assumptions']['embedding_dim']}-d float16): "
           f"{z['projection_lower_(text)_unique']['chunks']:,} to {z['projection_upper_(url,text)_unique']['chunks']:,} chunks, "
           f"{z['projection_lower_(text)_unique']['float16_vectors_gb']} to "
           f"{z['projection_upper_(url,text)_unique']['float16_vectors_gb']} GB of vectors", "",
           "## Query types", "", "| type | records | empty | mean chars (non-empty) | share of raw chars | exclusive keys | exclusive chars |",
           "|---|---|---|---|---|---|---|"]
    for t, v in s["query_types"].items():
        out.append(f"| {t} | {v['records']:,} | {v['empty_share']} | {v['mean_chars_nonempty']} | "
                   f"{v['share_of_raw_chars']} | {v['exclusive_nonempty_keys']:,} | {v['exclusive_chars']:,} |")
    out += ["", "## 'gold' records vs dev.json gold URLs", f"```\n{json.dumps(s['gold_type_vs_dev_json'], indent=2)}\n```", ""]
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--audit-dir", required=True)
    ap.add_argument("--dev", default=None)
    ap.add_argument("--chars-per-chunk", type=int, default=CHARS_PER_CHUNK_DEFAULT)
    ap.add_argument("--dim", type=int, default=EMBED_DIM_DEFAULT)
    a = ap.parse_args(argv)
    s = followup(a.audit_dir, a.dev, a.chars_per_chunk, a.dim)
    print(render(s))


if __name__ == "__main__":
    sys.exit(main())
