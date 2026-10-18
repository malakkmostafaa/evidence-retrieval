"""Block 1 - read-only audit of the AVeriTeC knowledge store (dev300 ZIP parts).

Nothing is modified, extracted or deleted. The ZIPs are streamed member by member and line by line.

Usage (from the repo root, venv active):
    python -m evret.audit ^
        --zips "C:\\Users\\malak\\Desktop\\ks\\ks_upload" ^
        --subsets "C:\\Users\\malak\\Desktop\\ks\\dev_subsets_seed42.json" ^
        --dev "C:\\Users\\malak\\Desktop\\thesis\\data\\raw\\averitec\\dev.json" ^
        --out outputs\\block01_audit

Outputs (in --out):
    audit_summary.json      all headline numbers + input fingerprints
    audit_per_store.csv     one row per claim store
    audit_per_record.csv.gz one row per record: lengths, hashes, domain, flags (no page text)
    audit_report.md         short human-readable report
    failure_samples.jsonl   up to 20 examples of each failure kind

Design notes (see docs/DECISIONS.md, Block 1):
* D1: ZIPs are streamed, never extracted.
* D2: unreadable lines are counted, categorised and sampled, never silently dropped.
* Lines are split ONLY at b"\\n" (binary readline). str.splitlines() is never used: it also splits at
  U+2028, U+0085, form feed, ... which occur inside scraped text and broke the previous reader.
* Every heuristic here (URL normalisation, PDF detection, fact-check domain list, URL dates) only FLAGS
  records for measurement. Nothing is removed in this block.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import hashlib
import io
import json
import os
import platform
import re
import subprocess
import sys
import time
import zipfile
from collections import Counter, defaultdict
from urllib.parse import parse_qsl, urlencode, urlsplit

OLD_CAP_CHARS = 100_000          # the truncation limit of the previous build (for measuring its impact)
TINY_CHARS = 200                 # "tiny" threshold of the previous build (measured here, not applied)
MAX_SAMPLES = 20                 # failure samples kept per failure kind
LENGTH_BUCKETS = [0, 1, 200, 1_000, 5_000, 10_000, 50_000, 100_000, 200_000, 500_000, 1_000_000, 10**12]

# Candidate fact-checking hosts (ASSUMPTION: a starting list for measurement only; refined in Block 2).
FACTCHECK_HOSTS = {
    "snopes.com", "politifact.com", "factcheck.org", "fullfact.org", "leadstories.com", "checkyourfact.com",
    "africacheck.org", "boomlive.in", "altnews.in", "factly.in", "vishvasnews.com", "newschecker.in",
    "healthfeedback.org", "sciencefeedback.co", "climatefeedback.org", "misbar.com", "factcheck.afp.com",
    "truthorfiction.com", "politifact.org", "poynter.org", "teyit.org", "maldita.es", "newtral.es",
    "chequeado.com", "aosfatos.org", "lupa.uol.com.br", "faktisk.no", "correctiv.org", "pesacheck.org",
    "dubawa.org", "factcheckni.org", "thequint.com/news/webqoof", "logically.ai",
}
FACTCHECK_PATH_RE = re.compile(r"fact[-_]?check|hoax|debunk|webqoof", re.I)
TRACKING_PARAMS = re.compile(r"^(utm_.*|fbclid|gclid|mc_cid|mc_eid|ref|ref_src|cmpid|ocid)$", re.I)
URL_DATE_RE = re.compile(
    r"/((?:19|20)\d{2})/(0[1-9]|1[0-2])(?:/(0[1-9]|[12]\d|3[01]))?(?:/|$)"
    r"|((?:19|20)\d{2})-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])"
)


# --------------------------------------------------------------------------------------- small helpers
def normalize_url(url: str) -> str:
    """Normalise a URL for duplicate/gold matching (ASSUMPTION, reported in the thesis).

    Lower-cased host without 'www.' and default port; scheme ignored (http == https); fragment dropped;
    tracking parameters dropped; remaining query parameters sorted; trailing '/' removed (except root).
    """
    url = (url or "").strip()
    if not url:
        return ""
    try:
        p = urlsplit(url if "://" in url else "http://" + url)
    except ValueError:
        return url.lower()
    host = (p.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    port = p.port if p.port not in (None, 80, 443) else None
    if port:
        host = f"{host}:{port}"
    path = p.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/") or "/"
    query = urlencode(sorted((k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
                             if not TRACKING_PARAMS.match(k)))
    return host + path + ("?" + query if query else "")


def host_of(norm_url: str) -> str:
    return norm_url.split("/", 1)[0]


def is_factcheck(norm_url: str) -> bool:
    host = host_of(norm_url)
    for fc in FACTCHECK_HOSTS:
        if "/" in fc:                                   # host + path prefix entries
            if norm_url.startswith(fc):
                return True
        elif host == fc or host.endswith("." + fc):
            return True
    path = norm_url[len(host):]
    return bool(FACTCHECK_PATH_RE.search(path))


def is_pdf(url: str, text: str) -> bool:
    path = urlsplit(url).path.lower() if url else ""
    return path.endswith(".pdf") or text.lstrip()[:5] == "%PDF-"


def url_date(url: str) -> str:
    m = URL_DATE_RE.search(url or "")
    if not m:
        return ""
    if m.group(1):
        return f"{m.group(1)}-{m.group(2)}" + (f"-{m.group(3)}" if m.group(3) else "")
    return f"{m.group(4)}-{m.group(5)}-{m.group(6)}"


def content_hash(text: str) -> str:
    return hashlib.blake2b(text.encode("utf-8", "surrogatepass"), digest_size=16).hexdigest()


def sha256_file(path: str, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def percentiles(values, ps=(50, 90, 95, 99)):
    if not values:
        return {f"p{p}": None for p in ps} | {"mean": None, "max": None}
    s = sorted(values)
    out = {f"p{p}": s[min(len(s) - 1, max(0, -(-p * len(s) // 100) - 1))] for p in ps}  # nearest rank
    out["mean"] = round(sum(s) / len(s), 1)
    out["max"] = s[-1]
    return out


def bucket_counts(values):
    names = [f"[{LENGTH_BUCKETS[i]:,}, {LENGTH_BUCKETS[i + 1]:,})" for i in range(len(LENGTH_BUCKETS) - 1)]
    names[-1] = f">= {LENGTH_BUCKETS[-2]:,}"
    counts = Counter()
    for v in values:
        for i in range(len(LENGTH_BUCKETS) - 1):
            if LENGTH_BUCKETS[i] <= v < LENGTH_BUCKETS[i + 1]:
                counts[names[i]] += 1
                break
    return {n: counts.get(n, 0) for n in names}


def git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                              timeout=10).stdout.strip() or "unknown"
    except Exception:
        return "unknown"


# --------------------------------------------------------------------------------------- input loaders
def load_subsets(path: str) -> dict[str, set[int]]:
    """Read the frozen subset file. Accepts {name: [ids]}, {name: {"claim_ids": [ids]}} or a bare list."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    found: dict[str, set[int]] = {}

    def as_ids(v):
        if isinstance(v, list) and v and all(isinstance(x, (int, str)) and str(x).strip().lstrip("-").isdigit()
                                             for x in v):
            return {int(x) for x in v}
        return None

    if isinstance(data, list):
        ids = as_ids(data)
        if ids is not None:
            found["subset"] = ids
    elif isinstance(data, dict):
        for k, v in data.items():
            ids = as_ids(v)
            if ids is None and isinstance(v, dict):
                for kk, vv in v.items():
                    ids = as_ids(vv)
                    if ids is not None:
                        k = f"{k}.{kk}" if kk not in ("claim_ids", "ids") else k
                        break
            if ids is not None:
                found[k] = ids
    if not found:
        raise ValueError(f"No list of claim ids found in {path}; top-level type {type(data).__name__}")
    return found


def load_dev(path: str) -> list[dict]:
    """AVeriTeC dev annotations: a JSON list; the claim id is the list index (checked in the report)."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("dev.json is expected to be a list of claims")
    claims = []
    for i, c in enumerate(data):
        gold = []
        for q in c.get("questions") or []:
            for a in q.get("answers") or []:
                u = a.get("source_url")
                if u:
                    gold.append(u)
        claims.append({
            "claim_id": i,
            "label": c.get("label"),
            "claim_date": c.get("claim_date"),
            "gold_urls": gold,
            "original_claim_url": c.get("original_claim_url") or "",
            "fact_checking_article": c.get("fact_checking_article") or "",
        })
    return claims


# --------------------------------------------------------------------------------------- core reader
class FailureLog:
    def __init__(self):
        self.counts = Counter()
        self.samples = defaultdict(list)

    def add(self, kind, where, detail):
        self.counts[kind] += 1
        if len(self.samples[kind]) < MAX_SAMPLES:
            self.samples[kind].append({"kind": kind, "where": where, "detail": str(detail)[:500]})


def iter_store_lines(raw: io.BufferedIOBase):
    """Yield (line_no, bytes) splitting ONLY at b'\\n'. Binary readline never splits at U+2028 etc."""
    line_no = 0
    while True:
        line = raw.readline()
        if not line:
            return
        line_no += 1
        yield line_no, line


def parse_record(line: bytes, where: str, fails: FailureLog):
    """Return a dict or None. Decoding is strict so that broken bytes are counted, not hidden."""
    try:
        s = line.decode("utf-8")
    except UnicodeDecodeError as e:
        fails.add("utf8_decode_error", where, e)
        s = line.decode("utf-8", errors="replace")      # still parsed so the record is measured
    if not s.strip():
        return "blank"
    try:
        obj = json.loads(s)
    except json.JSONDecodeError as e:
        fails.add("json_error", where, f"{e}; starts with {s[:120]!r}")
        return None
    if not isinstance(obj, dict):
        fails.add("not_a_dict", where, type(obj).__name__)
        return None
    return obj


def record_text(obj: dict, where: str, fails: FailureLog, stats: Counter):
    """Join url2text into one text. The joiner ('\\n') is a Block 3 decision; here we measure its inputs."""
    v = obj.get("url2text")
    if v is None:
        stats["url2text_missing_or_null"] += 1
        return "", 0
    if isinstance(v, str):
        stats["url2text_is_str"] += 1
        return v, 1
    if isinstance(v, list):
        stats["url2text_is_list"] += 1
        parts = []
        for item in v:
            if isinstance(item, str):
                parts.append(item)
            else:
                stats["url2text_non_str_items"] += 1
                fails.add("url2text_non_str_item", where, type(item).__name__)
                parts.append(json.dumps(item, ensure_ascii=False) if item is not None else "")
        stats["url2text_items_total"] += len(parts)
        stats["url2text_items_with_newline"] += sum("\n" in p for p in parts)
        stats["url2text_items_ending_sentence"] += sum(p.rstrip()[-1:] in ".!?\"'" for p in parts if p.strip())
        return "\n".join(parts), len(parts)
    stats["url2text_other_type"] += 1
    fails.add("url2text_other_type", where, type(v).__name__)
    return str(v), 1


PER_RECORD_FIELDS = ["zip", "member", "line_no", "claim_id_file", "claim_id_record", "type", "query", "url",
                     "norm_url", "host", "is_pdf", "is_factcheck", "url_date", "n_items", "n_chars", "n_words",
                     "is_empty", "is_tiny", "content_hash", "n_u2028", "n_nul", "n_cr"]


def audit(zip_dir: str, subsets_path: str | None, dev_path: str | None, out_dir: str,
          hash_zips: bool = True, verbose: bool = True) -> dict:
    t0 = time.time()
    os.makedirs(out_dir, exist_ok=True)
    log = print if verbose else (lambda *a, **k: None)

    zips = sorted(os.path.join(zip_dir, n) for n in os.listdir(zip_dir) if n.lower().endswith(".zip"))
    if not zips:
        raise FileNotFoundError(f"no .zip files in {zip_dir}")
    subsets = load_subsets(subsets_path) if subsets_path else {}
    dev = load_dev(dev_path) if dev_path else []

    fails = FailureLog()
    stats = Counter()
    layouts = Counter()
    type_counts = Counter()
    type_samples = defaultdict(list)
    host_counts = Counter()
    lengths_all, lengths_web, lengths_pdf = [], [], []
    words_all = []
    store_rows = []
    member_seen: dict[int, list[str]] = defaultdict(list)
    key_count = Counter()            # (norm_url, content_hash) -> occurrences across all stores
    key_stores = defaultdict(set)    # (norm_url, content_hash) -> claim ids
    url_hashes = defaultdict(set)    # norm_url -> set(content_hash)
    hash_urls = defaultdict(set)     # content_hash -> set(norm_url), non-empty texts only
    url_has_text = {}                # norm_url -> True if any record with this URL has non-empty text
    store_urls: dict[int, dict[str, bool]] = {}   # claim -> {norm_url: has_text}
    beyond_cap_chars = 0
    total_chars = 0

    rec_path = os.path.join(out_dir, "audit_per_record.csv.gz")
    with gzip.open(rec_path, "wt", encoding="utf-8", newline="") as rec_f:
        rec_w = csv.DictWriter(rec_f, fieldnames=PER_RECORD_FIELDS)
        rec_w.writeheader()
        for zpath in zips:
            zname = os.path.basename(zpath)
            log(f"reading {zname} ...")
            with zipfile.ZipFile(zpath) as zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    base = info.filename.replace("\\", "/").rsplit("/", 1)[-1]
                    stem, ext = os.path.splitext(base)
                    if ext.lower() not in (".json", ".jsonl") or not stem.isdigit():
                        stats["zip_members_skipped_not_store"] += 1
                        fails.add("unexpected_zip_member", f"{zname}/{info.filename}", info.file_size)
                        continue
                    cid = int(stem)
                    member_seen[cid].append(f"{zname}/{info.filename}")
                    if len(member_seen[cid]) > 1:          # same store in two places: audit only the first
                        fails.add("duplicate_store_member", f"{zname}/{info.filename}", member_seen[cid])
                        continue
                    srow = Counter()
                    s_urls: dict[str, bool] = {}
                    with zf.open(info) as raw:
                        head = raw.peek(64)[:64] if hasattr(raw, "peek") else b""
                        first = head.lstrip()[:1]
                        layout = "json_array" if first == b"[" else ("empty_file" if not first else "jsonl")
                        layouts[layout] += 1
                        if layout == "json_array":                # whole file is one JSON list
                            data = raw.read()
                            try:
                                records = json.loads(data.decode("utf-8"))
                                lines = [(i + 1, r) for i, r in enumerate(records)]
                            except (UnicodeDecodeError, json.JSONDecodeError) as e:
                                fails.add("json_array_error", f"{zname}/{info.filename}", e)
                                lines = []
                        else:
                            lines = iter_store_lines(raw)
                        for line_no, item in lines:
                            where = f"{zname}/{info.filename}:{line_no}"
                            srow["lines"] += 1
                            if isinstance(item, bytes):
                                obj = parse_record(item, where, fails)
                            elif isinstance(item, dict):
                                obj = item
                            else:
                                fails.add("not_a_dict", where, type(item).__name__)
                                obj = None
                            if obj == "blank":
                                srow["blank_lines"] += 1
                                continue
                            if obj is None:
                                srow["bad_lines"] += 1
                                continue
                            srow["records"] += 1
                            for field in ("claim_id", "type", "query", "url", "url2text"):
                                if field not in obj:
                                    stats[f"missing_field_{field}"] += 1
                            rec_cid = obj.get("claim_id")
                            if rec_cid is not None and str(rec_cid).strip() != str(cid):
                                stats["claim_id_mismatch_file_vs_record"] += 1
                                fails.add("claim_id_mismatch", where, f"file {cid} record {rec_cid}")
                            text, n_items = record_text(obj, where, fails, stats)
                            url = obj.get("url") or ""
                            if not url:
                                stats["records_without_url"] += 1
                            nurl = normalize_url(url)
                            host = host_of(nurl)
                            n_chars = len(text)
                            empty = not text.strip()
                            pdf = is_pdf(url, text)
                            fc = bool(nurl) and is_factcheck(nurl)
                            udate = url_date(url)
                            chash = content_hash(text)
                            qtype = str(obj.get("type"))
                            type_counts[qtype] += 1
                            if len(type_samples[qtype]) < 5:
                                type_samples[qtype].append(str(obj.get("query"))[:200])
                            host_counts[host] += 1
                            total_chars += n_chars
                            beyond_cap_chars += max(0, n_chars - OLD_CAP_CHARS)
                            lengths_all.append(n_chars)
                            (lengths_pdf if pdf else lengths_web).append(n_chars)
                            n_words = len(text.split())
                            words_all.append(n_words)
                            srow["empty"] += empty
                            srow["tiny"] += (not empty and n_chars < TINY_CHARS)
                            srow["pdf"] += pdf
                            srow["factcheck"] += fc
                            srow["over_cap"] += n_chars > OLD_CAP_CHARS
                            srow["chars"] += n_chars
                            key = (nurl, chash)
                            key_count[key] += 1
                            key_stores[key].add(cid)
                            url_hashes[nurl].add(chash)
                            if not empty:
                                hash_urls[chash].add(nurl)
                            url_has_text[nurl] = url_has_text.get(nurl, False) or not empty
                            s_urls[nurl] = s_urls.get(nurl, False) or not empty
                            rec_w.writerow({
                                "zip": zname, "member": info.filename, "line_no": line_no,
                                "claim_id_file": cid, "claim_id_record": rec_cid, "type": qtype,
                                "query": obj.get("query"), "url": url, "norm_url": nurl, "host": host,
                                "is_pdf": int(pdf), "is_factcheck": int(fc), "url_date": udate,
                                "n_items": n_items, "n_chars": n_chars, "n_words": n_words,
                                "is_empty": int(empty), "is_tiny": int(not empty and n_chars < TINY_CHARS),
                                "content_hash": chash, "n_u2028": text.count("\u2028"),
                                "n_nul": text.count("\x00"), "n_cr": text.count("\r"),
                            })
                            stats["records_with_url_date"] += bool(udate)
                            stats["records_with_u2028"] += "\u2028" in text
                            stats["records_with_nul"] += "\x00" in text
                    store_urls[cid] = s_urls
                    store_rows.append({"claim_id": cid, "zip": zname, "member": info.filename,
                                       "compressed_bytes": info.compress_size, "bytes": info.file_size,
                                       "layout": layout, **{k: srow.get(k, 0) for k in (
                                           "lines", "blank_lines", "bad_lines", "records", "empty", "tiny",
                                           "pdf", "factcheck", "over_cap", "chars")},
                                       "unique_urls": len(s_urls)})

    # ---------------------------------------------------------------- aggregate statistics
    n_rec = len(lengths_all)
    store_ids = {r["claim_id"] for r in store_rows}
    exact_dup_records = sum(c - 1 for c in key_count.values() if c > 1)
    cross_store_keys = sum(1 for s in key_stores.values() if len(s) > 1)
    url_multi_content = sum(1 for h in url_hashes.values() if len(h) > 1)
    content_multi_url = sum(1 for u in hash_urls.values() if len(u) > 1)
    n_empty = sum(r["empty"] for r in store_rows)
    over_cap = sum(1 for v in lengths_all if v > OLD_CAP_CHARS)

    subset_checks = {}
    for name, ids in subsets.items():
        subset_checks[name] = {
            "n_ids": len(ids),
            "with_store": len(ids & store_ids),
            "without_store": sorted(ids - store_ids)[:50],
            "out_of_dev_range": sorted(i for i in ids if dev and not (0 <= i < len(dev)))[:50],
        }
    names = list(subsets)
    for a in names:
        for b in names:
            if a != b and subsets[a] <= subsets[b]:
                subset_checks.setdefault("_relations", []).append(f"{a} is a subset of {b}")
    if subsets:
        all_sub = set().union(*subsets.values())
        subset_checks["_stores_not_in_any_subset"] = sorted(store_ids - all_sub)[:50]
        subset_checks["_n_stores_not_in_any_subset"] = len(store_ids - all_sub)

    gold = {}
    if dev:
        g = Counter()
        g_pooled = Counter()
        claims_all_gold_text = 0
        claims_no_gold_text = 0
        leak = Counter()
        for c in dev:
            cid = c["claim_id"]
            if cid not in store_urls:
                continue
            own = store_urls[cid]
            nurls = {normalize_url(u) for u in c["gold_urls"] if u}
            g["claims_with_store"] += 1
            g["claims_without_gold_urls"] += not nurls
            states = []
            for u in nurls:
                if u in own:
                    st = "own_store_with_text" if own[u] else "own_store_empty_text"
                else:
                    st = "absent_from_own_store"
                g[st] += 1
                states.append(st)
                if u in url_has_text:
                    g_pooled["pooled_with_text" if url_has_text[u] else "pooled_empty_text"] += 1
                else:
                    g_pooled["absent_from_all_stores"] += 1
            if nurls:
                claims_all_gold_text += all(s == "own_store_with_text" for s in states)
                claims_no_gold_text += not any(s == "own_store_with_text" for s in states)
            for field in ("original_claim_url", "fact_checking_article"):
                u = normalize_url(c[field])
                if u:
                    leak[f"{field}_given"] += 1
                    leak[f"{field}_in_own_store"] += u in own
                    leak[f"{field}_in_any_store"] += u in url_has_text
        gold = {"dev_size": len(dev), "gold_urls_by_state_own_store": dict(g),
                "gold_urls_by_state_all_stores": dict(g_pooled),
                "claims_all_gold_urls_with_text_in_own_store": claims_all_gold_text,
                "claims_no_gold_url_with_text_in_own_store": claims_no_gold_text,
                "leakage_urls": dict(leak),
                "label_counts_for_claims_with_store": dict(Counter(c["label"] for c in dev
                                                                   if c["claim_id"] in store_ids))}

    summary = {
        "block": "01_audit", "created": dt.datetime.now().isoformat(timespec="seconds"),
        "runtime_s": None,
        "inputs": {
            "zip_dir": zip_dir,
            "zips": [{"name": os.path.basename(z), "bytes": os.path.getsize(z),
                      "sha256": sha256_file(z) if hash_zips else "skipped"} for z in zips],
            "subsets_file": subsets_path, "subsets_sha256": sha256_file(subsets_path) if subsets_path else None,
            "dev_file": dev_path, "dev_sha256": sha256_file(dev_path) if dev_path else None,
        },
        "environment": {"python": platform.python_version(), "os": f"{platform.system()} {platform.release()}",
                        "git_commit": git_commit()},
        "inventory": {"n_zips": len(zips), "n_stores": len(store_rows), "store_layouts": dict(layouts),
                      "duplicate_store_members": fails.counts.get("duplicate_store_member", 0),
                      "claim_id_min": min(store_ids) if store_ids else None,
                      "claim_id_max": max(store_ids) if store_ids else None,
                      "uncompressed_bytes": sum(r["bytes"] for r in store_rows)},
        "subsets": subset_checks,
        "reading": {"lines": sum(r["lines"] for r in store_rows),
                    "blank_lines": sum(r["blank_lines"] for r in store_rows),
                    "bad_lines": sum(r["bad_lines"] for r in store_rows),
                    "records": n_rec, "failures_by_kind": dict(fails.counts),
                    "accounting_ok": sum(r["lines"] for r in store_rows) ==
                    n_rec + sum(r["blank_lines"] + r["bad_lines"] for r in store_rows)},
        "schema": {k: v for k, v in stats.items() if k.startswith(("missing_field", "url2text", "claim_id",
                                                                   "records_without_url"))},
        "text": {
            "total_chars": total_chars,
            "empty_records": n_empty, "empty_share": round(n_empty / n_rec, 4) if n_rec else None,
            "tiny_records_under_200": sum(r["tiny"] for r in store_rows),
            "pdf_records": len(lengths_pdf), "web_records": len(lengths_web),
            "chars_percentiles_all": percentiles(lengths_all),
            "chars_percentiles_nonempty": percentiles([v for v in lengths_all if v > 0]),
            "chars_percentiles_web": percentiles(lengths_web),
            "chars_percentiles_pdf": percentiles(lengths_pdf),
            "words_percentiles_all": percentiles(words_all),
            "chars_histogram": bucket_counts(lengths_all),
            "records_with_u2028": stats["records_with_u2028"], "records_with_nul": stats["records_with_nul"],
        },
        "old_cap_impact": {
            "cap_chars": OLD_CAP_CHARS,
            "records_over_cap": over_cap,
            "records_over_cap_share": round(over_cap / n_rec, 4) if n_rec else None,
            "pdf_records_over_cap": sum(1 for v in lengths_pdf if v > OLD_CAP_CHARS),
            "chars_beyond_cap": beyond_cap_chars,
            "chars_beyond_cap_share_of_all": round(beyond_cap_chars / total_chars, 4) if total_chars else None,
            "note": "counted on raw records before deduplication",
        },
        "query_types": {"counts": dict(type_counts.most_common()), "samples": dict(type_samples)},
        "duplicates": {
            "exact_duplicate_records_(same_norm_url_and_text)": exact_dup_records,
            "keys_shared_by_more_than_one_store": cross_store_keys,
            "unique_(url,text)_keys": len(key_count),
            "unique_norm_urls": len(url_hashes),
            "urls_with_more_than_one_text_version": url_multi_content,
            "nonempty_texts_under_more_than_one_url": content_multi_url,
        },
        "domains": {"n_hosts": len(host_counts), "top_30_hosts": host_counts.most_common(30),
                    "factcheck_flagged_records": sum(r["factcheck"] for r in store_rows),
                    "factcheck_list_note": "candidate host list + path regex; an ASSUMPTION for measurement"},
        "dates": {"records_with_url_date": stats["records_with_url_date"],
                  "share": round(stats["records_with_url_date"] / n_rec, 4) if n_rec else None},
        "gold": gold,
    }
    summary["runtime_s"] = round(time.time() - t0, 1)

    with open(os.path.join(out_dir, "audit_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    with open(os.path.join(out_dir, "audit_per_store.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(store_rows[0].keys()) if store_rows else ["claim_id"])
        w.writeheader()
        w.writerows(sorted(store_rows, key=lambda r: r["claim_id"]))
    with open(os.path.join(out_dir, "failure_samples.jsonl"), "w", encoding="utf-8") as f:
        for kind, items in fails.samples.items():
            for it in items:
                f.write(json.dumps(it, ensure_ascii=False) + "\n")
    with open(os.path.join(out_dir, "audit_report.md"), "w", encoding="utf-8") as f:
        f.write(render_report(summary))
    log(f"done in {summary['runtime_s']} s -> {out_dir}")
    return summary


def render_report(s: dict) -> str:
    t, c, r, d = s["text"], s["old_cap_impact"], s["reading"], s["duplicates"]
    lines = [
        "# Block 1 - knowledge store audit", "",
        f"Created {s['created']} in {s['runtime_s']} s; git {s['environment']['git_commit'][:12]}.", "",
        "## Inventory and reading",
        f"- {s['inventory']['n_zips']} ZIPs, {s['inventory']['n_stores']} stores, layouts {s['inventory']['store_layouts']}, "
        f"{s['inventory']['uncompressed_bytes'] / 1e9:.2f} GB uncompressed",
        f"- lines {r['lines']:,} = records {r['records']:,} + blank {r['blank_lines']:,} + bad {r['bad_lines']:,} "
        f"-> accounting {'OK' if r['accounting_ok'] else 'MISMATCH'}",
        f"- failures by kind: {r['failures_by_kind'] or 'none'}",
        f"- subsets: {json.dumps(s['subsets'])[:800]}", "",
        "## Text",
        f"- empty records {t['empty_records']:,} ({t['empty_share']}); tiny (<200 chars) {t['tiny_records_under_200']:,}",
        f"- PDF {t['pdf_records']:,} / web {t['web_records']:,}",
        f"- chars, non-empty: {t['chars_percentiles_nonempty']}",
        f"- chars, PDF: {t['chars_percentiles_pdf']}",
        "", "## Impact of the old 100,000-character cap",
        f"- {c['records_over_cap']:,} records over the cap ({c['records_over_cap_share']}); "
        f"{c['pdf_records_over_cap']:,} of them PDFs",
        f"- {c['chars_beyond_cap']:,} characters beyond the cap = {c['chars_beyond_cap_share_of_all']} of all characters",
        "", "## Query types", f"- {s['query_types']['counts']}",
        "", "## Duplicates",
    ] + [f"- {k}: {v:,}" for k, v in d.items()] + [
        "", "## Domains and dates",
        f"- fact-check flagged records: {s['domains']['factcheck_flagged_records']:,}",
        f"- records with a date in the URL: {s['dates']['records_with_url_date']:,} ({s['dates']['share']})",
        "", "## Gold evidence", f"```\n{json.dumps(s['gold'], indent=2)}\n```", "",
    ]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--zips", required=True, help="folder with the knowledge store ZIP parts")
    ap.add_argument("--subsets", default=None, help="frozen subset id file (JSON)")
    ap.add_argument("--dev", default=None, help="AVeriTeC dev.json")
    ap.add_argument("--out", default=os.path.join("outputs", "block01_audit"))
    ap.add_argument("--no-hash", action="store_true", help="skip sha256 of the ZIPs (faster, for debugging)")
    a = ap.parse_args(argv)
    audit(a.zips, a.subsets, a.dev, a.out, hash_zips=not a.no_hash)


if __name__ == "__main__":
    sys.exit(main())
