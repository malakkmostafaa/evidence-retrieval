# LOG

Three lines per session: tried / happened / next. Failed attempts belong here.

## 2026-10-18
- Tried: restarted the data stage after supervisor feedback (no truncation). Block 0 environment; Block 1 audit of the 300 dev stores (12.6 min run); Block 1b second pass (size after de-duplication, query types, gold check).
- Happened: Python 3.14 replaced by 3.11 for library compatibility (failed attempt). Audit closed its accounting (301,754 lines = 301,754 records, 0 bad). 72.1% of all characters lie beyond the old 100,000-character cap. My first gold test passed with a deliberately injected bug because the fixture could not tell the two cases apart; fixed by adding a discriminating case.
- Next: run Block 1b, send audit_followup.md; Block 2 (corpus design: pool/holdout, gold-derived query types, dates, size control).
