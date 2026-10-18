# Block 1 - knowledge store audit

Created 2026-10-18T07:06:30 in 757.3 s; git 58bc887bdb08.

## Inventory and reading
- 8 ZIPs, 300 stores, layouts {'jsonl': 300}, 21.66 GB uncompressed
- lines 301,754 = records 301,754 + blank 0 + bad 0 -> accounting OK
- failures by kind: none
- subsets: {"dev300": {"n_ids": 300, "with_store": 300, "without_store": [], "out_of_dev_range": []}, "dev50_debug": {"n_ids": 50, "with_store": 50, "without_store": [], "out_of_dev_range": []}, "_relations": ["dev50_debug is a subset of dev300"], "_stores_not_in_any_subset": [], "_n_stores_not_in_any_subset": 0}

## Text
- empty records 64,512 (0.2138); tiny (<200 chars) 5,482
- PDF 50,712 / web 251,042
- chars, non-empty: {'p50': 6789, 'p90': 163747, 'p95': 465590, 'p99': 1349849, 'mean': 86973.4, 'max': 38503280}
- chars, PDF: {'p50': 76228, 'p90': 770556, 'p95': 1127235, 'p99': 2554736, 'mean': 291116.4, 'max': 38503280}

## Impact of the old 100,000-character cap
- 30,957 records over the cap (0.1026); 22,998 of them PDFs
- 14,883,094,114 characters beyond the cap = 0.7213 of all characters

## Query types
- {'question_duplicate': 47705, 'gpt_url_only': 35137, 'gpt_question': 31900, 'background_questions': 29093, 'most_similar': 28887, 'same_entity_questions': 25524, 'provenance': 22752, 'NER': 20268, 'background': 18747, 'question': 16964, 'answer': 15717, 'claim+question': 6932, 'claim': 1488, 'gold': 640}

## Duplicates
- exact_duplicate_records_(same_norm_url_and_text): 86,528
- keys_shared_by_more_than_one_store: 32,336
- unique_(url,text)_keys: 215,226
- unique_norm_urls: 213,557
- urls_with_more_than_one_text_version: 1,424
- nonempty_texts_under_more_than_one_url: 1,072

## Domains and dates
- fact-check flagged records: 5,872
- records with a date in the URL: 44,090 (0.1461)

## Gold evidence
```
{
  "dev_size": 500,
  "gold_urls_by_state_own_store": {
    "claims_with_store": 300,
    "claims_without_gold_urls": 0,
    "own_store_with_text": 376,
    "own_store_empty_text": 262
  },
  "gold_urls_by_state_all_stores": {
    "pooled_with_text": 379,
    "pooled_empty_text": 259
  },
  "claims_all_gold_urls_with_text_in_own_store": 124,
  "claims_no_gold_url_with_text_in_own_store": 69,
  "leakage_urls": {
    "fact_checking_article_given": 300,
    "fact_checking_article_in_own_store": 0,
    "fact_checking_article_in_any_store": 0,
    "original_claim_url_given": 156,
    "original_claim_url_in_own_store": 10,
    "original_claim_url_in_any_store": 11
  },
  "label_counts_for_claims_with_store": {
    "Refuted": 183,
    "Supported": 73,
    "Not Enough Evidence": 21,
    "Conflicting Evidence/Cherrypicking": 23
  }
}
```
