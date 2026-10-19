"""Embed pool bands one after another as soon as their chunks are complete (and the previous band is embedded).

    python scripts/run_pool_embed.py --corpus data/corpus_v1 --bands 1 2 3 4 5
"""
import argparse
import glob
import json
import os
import sys
import time

from evret import chunk as ck
from evret import embed as em


def band_chunked(corpus, b):
    docs = glob.glob(os.path.join(corpus, "documents", f"band={b}", "rank_*.parquet"))
    chunks = glob.glob(os.path.join(corpus, "chunks", f"band={b}", "rank_*.parquet"))
    tmps = glob.glob(os.path.join(corpus, "chunks", f"band={b}", "*.tmp"))
    return len(docs) > 0 and len(docs) == len(chunks) and not tmps


def band_embedded(corpus, b):
    p = em.manifest_path(corpus)
    if not os.path.exists(p):
        return False
    return json.load(open(p, encoding="utf-8")).get("bands", {}).get(str(b), {}).get("complete", False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--bands", type=int, nargs="+", required=True)
    a = ap.parse_args()
    enc = None
    for b in a.bands:
        while not (band_chunked(a.corpus, b) and (b == 0 or band_embedded(a.corpus, b - 1))):
            time.sleep(30)
        ck.write_chunk_manifest(a.corpus)
        if enc is None:
            enc = em.Encoder()
        em.embed_band(a.corpus, b, enc)
        print(f"band {b} embedded", flush=True)


if __name__ == "__main__":
    sys.exit(main())
