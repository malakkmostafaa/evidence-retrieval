# DECISIONS

Format: Decision / Alternatives considered / Evidence / Reason / Limitations, revisit if.

## D00a: Local development on Windows with a Python 3.11 venv   [engineering]   2026-10-18
- Decision: develop and run locally (VS Code, git repo); native Windows Python 3.11.9 in a venv; PyTorch 2.14.1 + CUDA 13.2; RTX 3060 Laptop GPU (6.4 GB), 16.5 GB RAM.
- Alternatives considered: Colab/Kaggle notebooks with code on Drive; WSL2; Python 3.14 (already installed).
- Evidence: docs/env_report.txt (15 checks, 0 FAIL): GPU vs CPU matmul rel. diff 2.75e-07; BGE-small embeddings GPU vs CPU min cosine 1.000000.
- Reason: data no longer fits Drive comfortably after removing truncation; git commits give stronger provenance than notebook hashes; local GPU removes the Colab/Drive split. 3.11 instead of 3.14 for ML-library compatibility.
- Limitations / revisit if: float16 results may differ slightly on other GPUs; WSL2 needed only if a Docker-based vector DB is chosen later.

## D01: Read the knowledge store ZIPs as streams, never extract   [engineering]   2026-10-18
- Decision: stream each ZIP member line by line (Python zipfile).
- Alternatives considered: extract everything first; extract one ZIP at a time and delete.
- Evidence: no extra disk; originals remain the single source of truth (checksummed in audit_summary.json).
- Reason: disk budget (~57 GB free) and reproducibility.
- Limitations / revisit if: manual inspection needs extracted files (sample records are printed instead).

## D02: Unreadable lines are counted, categorised and sampled, not skipped   [engineering]   2026-10-18
- Decision: split lines only at "\n" (binary readline, never str.splitlines()); strict UTF-8 decoding; every failure counted by kind with up to 20 samples; line accounting must close (lines = records + blank + bad).
- Alternatives considered: skip silently (previous reader); stop at first error.
- Evidence: previous build lost records because splitlines() split at U+2028 inside scraped text (corpus_v2 notes); unit test reproduces the issue.
- Reason: "no data loss" must be demonstrable, not assumed.
- Limitations / revisit if: none known.
