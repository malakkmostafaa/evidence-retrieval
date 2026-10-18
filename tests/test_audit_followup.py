"""Tests for Block 1b on a synthetic per-record file. Every expected number is worked out by hand.

Fixture (9 records; n_chars in brackets):
  claim 0: claim A[150000,pdf]  question A[150000,pdf]  gold B[1000]  gold C[empty]  answer D[1000, same text as B]
  claim 1: claim A[150000,pdf]  question E[500]  gold E[500]  claim B[2000, a DIFFERENT text version of B]
Unique (url, text) keys: (A,h1) (B,h2) (C,h0 empty) (D,h2) (E,h3) (B,h4)  -> 6 keys, 5 non-empty.
"""
import csv
import gzip
import json

import pytest

from evret.audit import PER_RECORD_FIELDS, normalize_url
from evret.audit_followup import followup

A, B, C, D, E, F = (f"https://{x}.example/p" for x in "abcdef")


def row(cid, typ, url, h, n, pdf=0, empty=0):
    d = dict.fromkeys(PER_RECORD_FIELDS, "")
    d.update(claim_id_file=cid, type=typ, url=url, norm_url=normalize_url(url), content_hash=h,
             n_chars=n, is_pdf=pdf, is_empty=empty)
    return d


ROWS = [
    row(0, "claim", A, "h1", 150000, pdf=1), row(0, "question", A, "h1", 150000, pdf=1),
    row(0, "gold", B, "h2", 1000), row(0, "gold", C, "h0", 0, empty=1), row(0, "answer", D, "h2", 1000),
    row(1, "claim", A, "h1", 150000, pdf=1), row(1, "question", E, "h3", 500), row(1, "gold", E, "h3", 500),
    row(1, "claim", B, "h4", 2000),
]


def claim(*urls):
    return {"label": "Refuted", "claim_date": "1-1-2020",
            "questions": [{"answers": [{"source_url": u} for u in urls]}]}


@pytest.fixture()
def result(tmp_path):
    with gzip.open(tmp_path / "audit_per_record.csv.gz", "wt", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=PER_RECORD_FIELDS)
        w.writeheader()
        w.writerows(ROWS)
    dev = [claim(B, C), claim(E, F), claim()]            # claim 2 has no store: must be ignored
    (tmp_path / "dev.json").write_text(json.dumps(dev), encoding="utf-8")
    s = followup(str(tmp_path), str(tmp_path / "dev.json"), chars_per_chunk=500, dim=384)
    return s, tmp_path


def test_size_after_dedup(result):
    z = result[0]["size_after_dedup"]
    assert z["raw_records"] == 9 and z["raw_chars_nonempty"] == 455_000
    assert z["unique_keys_(url,text)"] == 6 and z["unique_nonempty_keys"] == 5
    assert z["unique_chars"] == 154_500
    assert z["unique_pdf_chars"] == 150_000 and z["unique_web_chars"] == 4_500
    assert z["dedup_removed_char_share"] == pytest.approx(1 - 154_500 / 455_000, abs=1e-4)
    assert z["unique_chars_beyond_old_cap"] == 50_000
    assert z["unique_chars_if_identical_texts_under_different_urls_also_merged"] == 153_500
    assert z["projection_upper_(url,text)_unique"]["chunks"] == 309
    assert z["projection_lower_(text)_unique"]["chunks"] == 307
    assert z["projection_upper_(url,text)_unique"]["float16_vectors_gb"] == round(309 * 384 * 2 / 1e9, 2)


def test_query_types(result):
    t = result[0]["query_types"]
    assert {k: v["records"] for k, v in t.items()} == {"claim": 3, "gold": 3, "question": 2, "answer": 1}
    assert t["gold"]["empty_share"] == pytest.approx(1 / 3, abs=1e-4)
    # text reached ONLY through one type: B(h2) only by gold, D only by answer, B(h4) only by claim;
    # A is reached by claim AND question, E by question AND gold -> exclusive to nobody
    assert (t["gold"]["exclusive_nonempty_keys"], t["gold"]["exclusive_chars"]) == (1, 1000)
    assert (t["answer"]["exclusive_nonempty_keys"], t["answer"]["exclusive_chars"]) == (1, 1000)
    assert (t["claim"]["exclusive_nonempty_keys"], t["claim"]["exclusive_chars"]) == (1, 2000)
    assert t["question"]["exclusive_nonempty_keys"] == 0


def test_gold_type_vs_dev_json(result):
    g = result[0]["gold_type_vs_dev_json"]
    assert (g["claims_compared"], g["exact_match"], g["mismatch"]) == (2, 1, 1)
    assert g["dev_urls_without_gold_type_record"] == 1          # F is in dev.json but has no 'gold' record
    assert g["gold_type_urls_not_in_dev"] == 0
    assert g["mismatch_examples"][0]["claim_id"] == 1


def test_outputs_written(result):
    _, d = result
    assert (d / "audit_followup.json").exists() and (d / "audit_followup.md").exists()
