# LOG

Three lines per session: tried / happened / next. Failed attempts belong here.

## 2026-10-18
- Tried: restarted the data stage after supervisor feedback (no truncation). Block 0 environment; Block 1 audit of the 300 dev stores (12.6 min run); Block 1b second pass (size after de-duplication, query types, gold check).
- Happened: Python 3.14 replaced by 3.11 for library compatibility (failed attempt). Audit closed its accounting (301,754 lines = 301,754 records, 0 bad). 72.1% of all characters lie beyond the old 100,000-character cap. My first gold test passed with a deliberately injected bug because the fixture could not tell the two cases apart; fixed by adding a discriminating case.
- Next: run Block 1b, send audit_followup.md; Block 2 (corpus design: pool/holdout, gold-derived query types, dates, size control).

## 2026-10-19 (corpus tool, S0-S1)
- Tried: S0 plan; S1 ingest (pass 1 on 4 spawn workers, pass 2 only for the 180 pool stores); fixture tests + mutation checks; verification against the audit.
- Happened: ingest 359 s; 215,226 documents = audit exactly; 200/200 sampled documents byte-identical. Failed attempts: (1) first chunker regex `(?:\S+\s*){180}` backtracked catastrophically on short texts and hung the test run (fixed with possessive quantifiers, Python >= 3.11); (2) a split-at-whitespace mutation survived the first version of the chunk test (added a "no word is cut" assertion); (3) old split file not found.
- Next: chunk band 0 (running), embed benchmark, BM25 build, search tool.

## 2026-10-19 (corpus tool, S2-S4)
- Tried: chunker (regex-based generator), band 0 chunking, embed benchmark, BM25, search tool and tests.
- Happened: band 0 = 1.58M chunks in 557 s (stragglers: one 134M-character store ran alone at the end); embed speed 300 chunks/s (GPU throttled to 652 MHz). Failed attempts: first chunker tests hung (regex backtracking, see above); two stale pytest processes kept burning CPU until killed. Embedding of band 0 and chunking of bands 1-5 run in the background.
- Next: BM25 for band 0, S5 evaluation on band-0 claims, then bands 1-5 as they finish.

## 2026-10-19 (metrics port)
- Tried: ported legacy answer-coverage metrics to evret.metrics_cov; hand + golden + mutation tests; regression on the 100 labels; text-match leakage check; S5 now reports CovNovel@512 etc.
- Happened: saved legacy values reproduce the reported AUCs exactly only if NaN novel rows are dropped (my first run scored them 0: 0.717 instead of 0.752; wrong guess, fixed). Scorable-only answers reproduce 77/100 rows; adding the legacy anchoring step reproduces 55/57 pool rows. Remaining pool rows: row 35 (claim 164) differs 0.2273 vs 0.2222 because an answer is anchored on the full-length page now but was not on the old 100k-truncated text; row 68 (claim 181): gold URL is empty in the new store (a m.economictimes.com copy has text), the old run had text. Equivalent mutant: 'p.n_tokens < room' in build_context (a passage exactly filling the budget is cut at its last token = whole text).
- Next: ask Malak about reading sealed gold pages for anchoring, and about the old chunker (pack_200_250 in legacy chunker.py differs from my word-based packer).

## 2026-10-19 (decision)
- Tried: compared my chunker with the legacy one. Happened: they differ (D9a); Malak decided to keep mine. Next: wait for bands 2-5 embeddings, then re-run S5 on all six bands and finish docs/reports/corpus_tool_v1.md (add the CovNovel@512 table from outputs/corpus_v1/eval_bands_0_1.json).

## 2026-10-19 (full pool)
- Tried: whole-pool embedding check and S5 on all 180 pool claims. Happened: all checks pass (self-retrieval 300/300, 0 truncations, 0 leaks in 54,000 hits); dense and hybrid better than BM25, dense vs hybrid not separable. Report: docs/reports/corpus_tool_v1.md. Free disk 18.4 GB.
- Next: sealed bands stay untouched; optional 50-passage relabelling and chunker comparison are proposals only.

## 2026-10-20 (relabelling)
- Tried: report fixes (one unreachable-gold definition, n per table); relabelling design and blinded sheet (50 passages, 43 claims, 17/17/16 dense/BM25/hybrid, full chunk text); scoring script written but not run. Happened: label wording confirmed by Malak. Key file and labels not opened. Next: Malak labels outputs/corpus_v1/relabel/relabel_sheet_TO_LABEL.csv and returns it; then `python scripts/score_relabel.py <file>`.
