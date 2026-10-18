"""Tests for Block 1 (knowledge store audit), run on a tiny synthetic knowledge store.

Every expected number below is worked out by hand from the fixture, so a passing test means the audit
counts exactly what it claims to count.  Run:  pytest -q
"""
import csv
import gzip
import json
import zipfile

import pytest

from evret.audit import audit, is_factcheck, normalize_url, url_date


def line(obj) -> bytes:
    # ensure_ascii=False keeps U+2028 as a raw character inside the JSON line, as in real scraped data
    return (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")


def rec(cid, url, text, qtype="claim", query="q"):
    return {"claim_id": str(cid), "type": qtype, "query": query, "url": url, "url2text": text}


@pytest.fixture()
def ks(tmp_path):
    zdir = tmp_path / "zips"
    zdir.mkdir()
    store0 = b"".join([
        line(rec(0, "https://www.example.com/news/2020/05/story?utm_source=x", ["Line one.", "Line two."])),
        line(rec(0, "https://example.org/a", ["before after " + "x" * 300])),   # U+2028 inside text
        b'{"claim_id": "0", "url": \n',                                                # broken JSON line
        b"\n",                                                                         # blank line
        line(rec(0, "https://example.net/empty", [])),                                 # empty text
        line(rec(0, "http://example.com/news/2020/05/story", ["Line one.", "Line two."])),  # exact duplicate
        line(rec(0, "https://gov.example/report.pdf", ["word " * 30_000], qtype="question")),  # 150,000 chars
        line(rec(0, "https://www.snopes.com/fact-check/foo/", ["Snopes says false."])),
        line(rec(0, "https://gold.example/page", ["gold evidence text"])),
    ])
    store1 = b"".join([
        line(rec(1, "https://www.example.com/news/2020/05/story", ["Line one.", "Line two."])),  # cross-store
        line(rec(1, "https://gold.example/empty", [""])),                              # gold page, empty text
        line(rec(1, "https://str.example/x", "plain string text")),                    # url2text is a str
        line(rec(7, "https://other.example/y", ["claim id mismatch"])),                # record says claim 7
    ])
    with zipfile.ZipFile(zdir / "part01.zip", "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("0.json", store0)
    with zipfile.ZipFile(zdir / "part02.zip", "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("1.json", store1)
        z.writestr("readme.txt", "not a store")
    dev = [
        {"claim": "c0", "label": "Refuted", "claim_date": "1-6-2020",
         "questions": [{"question": "q", "answers": [{"answer": "a", "source_url": "https://gold.example/page"},
                                                     {"answer": "b", "source_url": "https://missing.example/x"}]}],
         "original_claim_url": "https://example.org/a",
         "fact_checking_article": "https://www.snopes.com/fact-check/foo/"},
        {"claim": "c1", "label": "Supported", "claim_date": "2-6-2020",
         # gold.example/page is in claim 0's store only: absent from claim 1's own store, present in the pool
         "questions": [{"question": "q", "answers": [{"answer": "a", "source_url": "https://gold.example/empty"},
                                                     {"answer": "b", "source_url": "https://gold.example/page"}]}]},
        {"claim": "c2", "label": "Supported", "questions": []},
    ]
    (tmp_path / "dev.json").write_text(json.dumps(dev), encoding="utf-8")
    (tmp_path / "subsets.json").write_text(json.dumps({"seed": 42, "dev300": [0, 1, 2], "debug50": [0]}),
                                           encoding="utf-8")
    out = tmp_path / "out"
    s = audit(str(zdir), str(tmp_path / "subsets.json"), str(tmp_path / "dev.json"), str(out), verbose=False)
    return s, out


def test_inventory_and_line_accounting(ks):
    s, _ = ks
    assert s["inventory"]["n_stores"] == 2
    assert s["inventory"]["store_layouts"] == {"jsonl": 2}
    r = s["reading"]
    assert (r["lines"], r["records"], r["blank_lines"], r["bad_lines"]) == (13, 11, 1, 1)
    assert r["accounting_ok"] is True
    assert r["failures_by_kind"] == {"json_error": 1, "unexpected_zip_member": 1, "claim_id_mismatch": 1}


def test_u2028_is_not_a_line_break(ks):
    s, _ = ks
    # the record with U+2028 is read as ONE record (otherwise there would be extra json errors)
    assert s["text"]["records_with_u2028"] == 1
    # ...whereas str.splitlines() WOULD split it - this is why the reader never uses splitlines()
    assert len(json.dumps({"t": "a b"}, ensure_ascii=False).splitlines()) == 2


def test_text_and_old_cap(ks):
    s, _ = ks
    assert s["text"]["empty_records"] == 2
    assert s["text"]["pdf_records"] == 1
    c = s["old_cap_impact"]
    assert c["records_over_cap"] == 1 and c["pdf_records_over_cap"] == 1
    assert c["chars_beyond_cap"] == 150_000 - 100_000
    assert s["schema"]["url2text_is_str"] == 1 and s["schema"]["url2text_is_list"] == 10
    assert s["schema"]["claim_id_mismatch_file_vs_record"] == 1


def test_duplicates_flags_dates(ks):
    s, _ = ks
    d = s["duplicates"]
    assert d["exact_duplicate_records_(same_norm_url_and_text)"] == 2   # 3 copies of the same page
    assert d["keys_shared_by_more_than_one_store"] == 1
    assert s["domains"]["factcheck_flagged_records"] == 1
    assert s["dates"]["records_with_url_date"] == 3
    assert s["query_types"]["counts"] == {"claim": 10, "question": 1}


def test_gold_and_leakage(ks):
    s, _ = ks
    g = s["gold"]
    assert g["gold_urls_by_state_own_store"] == {"claims_with_store": 2, "claims_without_gold_urls": 0,
                                                 "own_store_with_text": 1, "absent_from_own_store": 2,
                                                 "own_store_empty_text": 1}
    assert g["gold_urls_by_state_all_stores"] == {"pooled_with_text": 2, "absent_from_all_stores": 1,
                                                  "pooled_empty_text": 1}
    assert g["claims_all_gold_urls_with_text_in_own_store"] == 0
    assert g["claims_no_gold_url_with_text_in_own_store"] == 1
    assert g["leakage_urls"]["original_claim_url_in_own_store"] == 1
    assert g["leakage_urls"]["fact_checking_article_in_own_store"] == 1


def test_subsets(ks):
    s, _ = ks
    assert s["subsets"]["dev300"]["with_store"] == 2
    assert s["subsets"]["dev300"]["without_store"] == [2]
    assert "debug50 is a subset of dev300" in s["subsets"]["_relations"]
    assert "seed" not in s["subsets"]          # non-list fields are ignored


def test_per_record_file_has_no_text_and_one_row_per_record(ks):
    s, out = ks
    with gzip.open(out / "audit_per_record.csv.gz", "rt", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == s["reading"]["records"] == 11
    assert "url2text" not in rows[0] and "text" not in rows[0]
    pdf = [r for r in rows if r["is_pdf"] == "1"]
    assert len(pdf) == 1 and pdf[0]["n_chars"] == "150000"


def test_helpers():
    assert normalize_url("https://WWW.Example.com/a/?utm_source=x&b=2&a=1#frag") == "example.com/a?a=1&b=2"
    assert normalize_url("http://example.com:80/") == "example.com/"
    assert is_factcheck(normalize_url("https://www.politifact.com/x")) is True
    assert is_factcheck(normalize_url("https://news.example/factcheck-the-claim")) is True
    assert is_factcheck(normalize_url("https://bls.gov/news")) is False
    assert url_date("https://site.com/2019/10/04/title") == "2019-10-04"
    assert url_date("https://site.com/story-2021-03-15.html") == "2021-03-15"
    assert url_date("https://site.com/about") == ""
