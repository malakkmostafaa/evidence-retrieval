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
