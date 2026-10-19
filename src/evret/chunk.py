"""S2 - chunking: boundary-aware word packing (pack_200_250) with a hard token/character cap.

PROVISIONAL DEFAULT (not an experiment result). Rules:
* A word is a maximal run of non-whitespace characters (`\\S+`; Python's Unicode whitespace, so U+2028 separates
  words and NUL is an ordinary character). Offsets are Python code-point offsets into the document text.
* A chunk has at most MAX_WORDS (250) words. It ends at the FIRST sentence/line boundary at or after word TARGET (200):
  the word ends with . ! or ? (optionally followed by closing quotes/brackets) or is followed by whitespace that contains
  "\\n". If there is none up to word 250, it ends at word 250.
* The next chunk starts OVERLAP (20) words before the end of the previous one. The last chunk is emitted only if it
  contains words not yet covered.
* Cap: a chunk whose [CLS] ... [SEP] token count exceeds MAX_TOKENS (500) or whose length exceeds MAX_CHARS (5000) is
  split into contiguous pieces (halving at the whitespace nearest to the middle, else exactly in the middle) until every
  piece satisfies both limits. Nothing is dropped.
* Empty and tiny (<200 chars) documents are not chunked.
Memory: the packer is a generator that scans the text with regular expressions; it never builds a list of words.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import multiprocessing as mp
import os
import re
import sqlite3
import sys
import time
from typing import Callable, Iterator

import pyarrow as pa
import pyarrow.parquet as pq

from evret import audit
from evret.ingest import decode_text

TARGET, MAX_WORDS, OVERLAP = 200, 250, 20
MAX_TOKENS, MAX_CHARS = 500, 5000
SKIP = TARGET - OVERLAP                        # words skipped by regex before the boundary search starts (180)
MODEL_REVISION = "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"
FLAG_FACTCHECK, FLAG_PDF, FLAG_SPLIT, FLAG_HARD = 1, 2, 4, 8       # chunk flag bits (HARD: ended at 250 words)

_WORD = re.compile(r"\S+")
_WS = re.compile(r"\s*")
_CLOSERS = "\"')]}”’»"
_END = ".!?"


def _skip_re(n: int):
    return re.compile(r"(?:\S++\s*+){%d}" % n)           # possessive quantifiers: no catastrophic backtracking


def _is_boundary(text: str, end: int) -> bool:
    """Is the word ending at `end` (exclusive) a sentence/line boundary?"""
    c = text[end - 1]
    if c in _END:
        return True
    if c in _CLOSERS and end >= 2 and text[end - 2] in _END:
        return True
    g = _WS.match(text, end).end()
    return "\n" in text[end:g]


def pack(text: str, target: int = TARGET, max_words: int = MAX_WORDS, overlap: int = OVERLAP
         ) -> Iterator[tuple[int, int, bool]]:
    """Yield (start, end, hard) char spans. `hard` is True when the chunk ended at max_words without a boundary."""
    skip = target - overlap
    skip_re = _skip_re(skip)
    first = _WORD.search(text)
    if first is None:
        return
    p = first.start()
    while True:
        m = skip_re.match(text, p)
        if m is None:                                   # fewer than `skip` words remain: one final chunk
            last_end = p
            for w in _WORD.finditer(text, p):
                last_end = w.end()
            yield p, last_end, False
            return
        starts: list[int] = []                          # starts[j] = start of word number skip + j (relative to p)
        n, end, hard, last_end = skip, None, False, m.end()
        for w in _WORD.finditer(text, m.end()):
            starts.append(w.start())
            last_end = w.end()
            n += 1
            if n >= target and _is_boundary(text, last_end):
                end = last_end
                break
            if n >= max_words:
                end, hard = last_end, True
                break
        if end is None:                                 # the text ended inside the window: final chunk
            yield p, (last_end if starts else _prev_word_end(text, m.end())), False
            return
        yield p, end, hard
        if _WORD.search(text, end) is None:
            return
        p = starts[n - overlap - skip]                  # start of word number (n - overlap)


def _prev_word_end(text: str, pos: int) -> int:
    """End of the last word that ends at or before `pos` (pos = start-or-end of text after the skipped words)."""
    i = pos
    while i > 0 and text[i - 1].isspace():
        i -= 1
    return i


def _hash64(text: str) -> int:
    return int.from_bytes(hashlib.blake2b(text.encode("utf-8", "surrogatepass"), digest_size=8).digest(), "big",
                          signed=True)


def _clean_for_tokenizer(s: str) -> str:
    return re.sub("[\ud800-\udfff]", "�", s) if not s.isascii() else s


def split_to_caps(text: str, s: int, e: int, count: Callable[[list[str]], list[int]],
                  max_tokens: int = MAX_TOKENS, max_chars: int = MAX_CHARS) -> list[tuple[int, int, int]]:
    """Return contiguous (start, end, n_tokens) pieces covering [s, e) that all satisfy both caps."""
    out: list[tuple[int, int, int]] = []
    stack = [(s, e)]
    while stack:
        a, b = stack.pop()
        n = count([text[a:b]])[0]
        if n <= max_tokens and b - a <= max_chars:
            out.append((a, b, n))
            continue
        if b - a < 2:                                                      # cannot split further (cap too small)
            out.append((a, b, n))
            continue
        mid = (a + b) // 2
        cut = mid
        for d in range(0, min(60, (b - a) // 2)):                         # nearest whitespace to the middle
            for c in (mid - d, mid + d):
                if a < c < b and text[c].isspace():
                    cut = c
                    break
            else:
                continue
            break
        stack.append((cut, b))
        stack.append((a, cut))
    return sorted(out)


def make_counter(tokenizer_file: str) -> Callable[[list[str]], list[int]]:
    from tokenizers import Tokenizer
    tok = Tokenizer.from_file(tokenizer_file)
    tok.no_truncation()
    tok.no_padding()

    def count(texts: list[str]) -> list[int]:
        return [len(e.ids) for e in tok.encode_batch([_clean_for_tokenizer(t) for t in texts])]
    return count


def chunk_document(text: str, count: Callable[[list[str]], list[int]], batch: int = 512
                   ) -> Iterator[tuple[int, int, int, bool, bool]]:
    """Yield (start, end, n_tokens, split, hard) for one document; memory bounded by `batch` chunks."""
    buf: list[tuple[int, int, bool]] = []

    def flush():
        ns = count([text[s:e] for s, e, _ in buf])
        for (s, e, hard), n in zip(buf, ns):
            if n <= MAX_TOKENS and e - s <= MAX_CHARS:
                yield s, e, n, False, hard
            else:
                for a, b, nn in split_to_caps(text, s, e, count):
                    yield a, b, nn, True, hard
        buf.clear()
    for span in pack(text):
        buf.append(span)
        if len(buf) >= batch:
            yield from flush()
    if buf:
        yield from flush()


# ------------------------------------------------------------------------------------------------- worker
CHUNK_SCHEMA = pa.schema([("doc_id", pa.int64()), ("ord", pa.int32()), ("start", pa.int64()),
                          ("end", pa.int64()), ("n_tokens", pa.int16()), ("text_hash", pa.int64()),
                          ("flags", pa.int16()), ("text_utf8", pa.large_binary())])


def chunk_shard(task: dict) -> dict:
    out = task["out"]
    if os.path.exists(out):
        return {"shard": task["shard"], "skipped": True}
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    count = make_counter(task["tokenizer"])
    pf = pq.ParquetFile(task["shard"])
    os.makedirs(os.path.dirname(out), exist_ok=True)
    tmp = out + ".tmp"
    cols: dict[str, list] = {c: [] for c in CHUNK_SCHEMA.names}
    n_chunks = n_split_docs = max_tok = n_docs = 0
    chars = 0
    t0 = time.time()
    with pq.ParquetWriter(tmp, CHUNK_SCHEMA, compression="zstd", compression_level=3) as w:
        def write():
            if cols["doc_id"]:
                w.write_table(pa.table(cols, schema=CHUNK_SCHEMA))
                for v in cols.values():
                    v.clear()
        for g in range(pf.num_row_groups):
            t = pf.read_row_group(g, columns=["doc_id", "text_utf8", "is_empty", "is_tiny", "is_factcheck", "is_pdf"])
            for i in range(t.num_rows):
                if t.column("is_empty")[i].as_py() or t.column("is_tiny")[i].as_py():
                    continue
                n_docs += 1
                text = decode_text(t.column("text_utf8")[i].as_py())
                base = (FLAG_FACTCHECK if t.column("is_factcheck")[i].as_py() else 0) | \
                       (FLAG_PDF if t.column("is_pdf")[i].as_py() else 0)
                did = t.column("doc_id")[i].as_py()
                k = 0
                for s, e, n, split, hard in chunk_document(text, count):
                    cols["doc_id"].append(did)
                    cols["ord"].append(k)
                    cols["start"].append(s)
                    cols["end"].append(e)
                    cols["n_tokens"].append(n)
                    seg = text[s:e]
                    cols["text_hash"].append(_hash64(seg))
                    cols["flags"].append(base | (FLAG_SPLIT if split else 0) | (FLAG_HARD if hard else 0))
                    cols["text_utf8"].append(seg.encode("utf-8", "surrogatepass"))
                    n_chunks += 1
                    chars += e - s
                    max_tok = max(max_tok, n)
                    k += 1
                    if len(cols["doc_id"]) >= 20000:
                        write()
                del text
            del t
        write()
    os.replace(tmp, out)
    return {"shard": task["shard"], "skipped": False, "chunks": n_chunks, "docs": n_docs, "max_tokens": max_tok,
            "chars": chars, "seconds": round(time.time() - t0, 1)}


def tokenizer_file() -> str:
    d = glob.glob(os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "hub",
                               "models--BAAI--bge-small-en-v1.5", "snapshots", MODEL_REVISION))
    if not d:
        raise FileNotFoundError("bge-small-en-v1.5 revision %s not in the local HF cache" % MODEL_REVISION)
    return os.path.join(d[0], "tokenizer.json")


# ------------------------------------------------------------------------------------------------- driver
def chunk_bands(corpus: str, bands: list[int], workers: int = 4, verbose: bool = True) -> dict:
    log = print if verbose else (lambda *a, **k: None)
    tok = tokenizer_file()
    ctx = mp.get_context("spawn")
    report = {}
    for b in bands:
        t0 = time.time()
        shards = sorted(glob.glob(os.path.join(corpus, "documents", f"band={b}", "rank_*.parquet")))
        tasks = [{"shard": s, "tokenizer": tok,
                  "out": os.path.join(corpus, "chunks", f"band={b}", os.path.basename(s))} for s in shards]
        res = []
        with ctx.Pool(workers) as pl:
            for i, r in enumerate(pl.imap(chunk_shard, tasks)):
                res.append(r)
                if (i + 1) % 10 == 0:
                    log(f"  band {b}: {i + 1}/{len(tasks)} shards, {time.time() - t0:.0f}s")
        report[b] = {"shards": len(tasks), "seconds": round(time.time() - t0, 1)}
        log(f"band {b} chunked in {time.time() - t0:.0f}s")
    return report


def chunk_files(corpus: str, bands: list[int] | None = None) -> list[str]:
    """Chunk shard files in global order (band, rank). chunk_id = cumulative row offset in this order."""
    fs = sorted(glob.glob(os.path.join(corpus, "chunks", "band=*", "rank_*.parquet")),
                key=lambda p: (int(re.search(r"band=(\d+)", p).group(1)), p))
    if bands is not None:
        fs = [f for f in fs if int(re.search(r"band=(\d+)", f).group(1)) in bands]
    return fs


def write_chunk_manifest(corpus: str) -> dict:
    """Offsets: chunk_id of the first row of each file. Needs all bands up to the last chunked one."""
    files, off, entries = chunk_files(corpus), 0, []
    for f in files:
        n = pq.ParquetFile(f).metadata.num_rows
        entries.append({"file": os.path.relpath(f, corpus).replace("\\", "/"), "first_chunk_id": off, "rows": n,
                        "sha256": audit.sha256_file(f)})
        off += n
    man = {"n_chunks": off, "files": entries, "model_revision": MODEL_REVISION,
           "params": {"target": TARGET, "max_words": MAX_WORDS, "overlap": OVERLAP, "max_tokens": MAX_TOKENS,
                      "max_chars": MAX_CHARS}}
    tmp = os.path.join(corpus, "chunks_manifest.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(man, f, indent=1)
    os.replace(tmp, os.path.join(corpus, "chunks_manifest.json"))
    return man


def build_sqlite(corpus: str, path: str | None = None) -> int:
    """Derived chunk_id -> text store (rebuildable). Text as UTF-8 BLOB (NUL-safe)."""
    path = path or os.path.join(corpus, "chunk_text.sqlite")
    man = json.load(open(os.path.join(corpus, "chunks_manifest.json"), encoding="utf-8"))
    if os.path.exists(path):
        os.remove(path)
    db = sqlite3.connect(path)
    db.execute("PRAGMA journal_mode=OFF")
    db.execute("PRAGMA synchronous=OFF")
    db.execute("CREATE TABLE chunk_text (chunk_id INTEGER PRIMARY KEY, text BLOB NOT NULL)")
    n = 0
    for e in man["files"]:
        pf = pq.ParquetFile(os.path.join(corpus, e["file"]))
        cid = e["first_chunk_id"]
        for batch in pf.iter_batches(batch_size=20000, columns=["text_utf8"]):
            vals = batch.column(0).to_pylist()
            db.executemany("INSERT INTO chunk_text VALUES (?, ?)", ((cid + i, v) for i, v in enumerate(vals)))
            cid += len(vals)
            n += len(vals)
        db.commit()
    db.close()
    return n


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--bands", type=int, nargs="+", required=True)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--manifest", action="store_true", help="write chunks_manifest.json after chunking")
    ap.add_argument("--sqlite", action="store_true")
    a = ap.parse_args(argv)
    print(json.dumps(chunk_bands(a.corpus, a.bands, a.workers), indent=1))
    if a.manifest:
        print("chunks:", write_chunk_manifest(a.corpus)["n_chunks"])
    if a.sqlite:
        print("sqlite rows:", build_sqlite(a.corpus))


if __name__ == "__main__":
    sys.exit(main())
