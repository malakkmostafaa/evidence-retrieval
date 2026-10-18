# Block 1b - size after de-duplication, query types, gold check

## Size
- raw non-empty characters: 20,633,926,838
- unique (url, text) characters: 10,600,102,626 (0.4863 of raw removed by exact de-duplication)
- of which PDF: 7,150,784,674 (0.6746); beyond the old 100k cap: 7,106,430,386 (0.6704)
- if identical texts under different URLs are also merged: 10,482,097,134
- PROJECTION (assumes 746 chars/chunk, 384-d float16): 14,051,069 to 14,209,253 chunks, 10.79 to 10.91 GB of vectors

## Query types

| type | records | empty | mean chars (non-empty) | share of raw chars | exclusive keys | exclusive chars |
|---|---|---|---|---|---|---|
| question_duplicate | 47,705 | 0.2407 | 170624.6 | 0.2995 | 20,323 | 2,268,142,310 |
| gpt_url_only | 35,137 | 0.2152 | 52999.1 | 0.0708 | 19,647 | 774,334,847 |
| gpt_question | 31,900 | 0.2023 | 39326.0 | 0.0485 | 16,489 | 380,907,363 |
| background_questions | 29,093 | 0.1871 | 22046.1 | 0.0253 | 15,921 | 257,064,398 |
| most_similar | 28,887 | 0.2276 | 199493.7 | 0.2157 | 13,301 | 1,877,804,908 |
| same_entity_questions | 25,524 | 0.2097 | 49537.2 | 0.0484 | 14,599 | 397,266,263 |
| provenance | 22,752 | 0.2213 | 46014.1 | 0.0395 | 9,501 | 394,483,377 |
| NER | 20,268 | 0.1862 | 9996.5 | 0.008 | 9,869 | 79,698,877 |
| background | 18,747 | 0.2029 | 41098.1 | 0.0298 | 8,930 | 256,152,686 |
| question | 16,964 | 0.1819 | 50792.5 | 0.0342 | 7,980 | 218,800,936 |
| answer | 15,717 | 0.2298 | 190676.8 | 0.1119 | 7,305 | 1,008,044,212 |
| claim+question | 6,932 | 0.2481 | 243099.9 | 0.0614 | 2,865 | 517,316,709 |
| claim | 1,488 | 0.2359 | 122136.1 | 0.0067 | 640 | 34,957,584 |
| gold | 640 | 0.4141 | 16197.3 | 0.0003 | 223 | 3,047,733 |

## 'gold' records vs dev.json gold URLs
```
{
  "claims_compared": 300,
  "exact_match": 300,
  "mismatch": 0,
  "dev_urls_without_gold_type_record": 0,
  "gold_type_urls_not_in_dev": 0,
  "mismatch_examples": []
}
```
