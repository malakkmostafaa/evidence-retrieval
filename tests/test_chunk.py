"""Chunker tests: hand-computed spans on tiny texts, an independent naive reference, and a fuzz test."""
import random
import re

import pytest

from evret import chunk as ck


def spans(text, **kw):
    return [(s, e) for s, e, _ in ck.pack(text, **kw)]


# ---------------------------------------------------------------------------------- hand-computed cases
def test_hard_cap_without_boundaries():
    # 600 words "a" separated by one space: word k occupies [2k, 2k+1). No punctuation -> chunks end at word 250.
    # chunk 1: words 0..249 -> [0, 499); next starts at word 230 -> char 460; chunk 2: words 230..479 -> [460, 959);
    # chunk 3 starts at word 460 -> 920; 140 words remain (460..599) -> ends at word 599 -> 1199.
    t = "a " * 600
    assert spans(t) == [(0, 499), (460, 959), (920, 1199)]
    assert [h for _, _, h in ck.pack(t)] == [True, True, False]


def test_ends_at_first_sentence_boundary_after_200():
    # words: 209 x "x", then "x." (word index 209), then 400 x "x". A '.' at word 150 must be ignored (before 200).
    t = ("x " * 150).replace("x ", "x. ", 1) + "x " * 59 + "x. " + "x " * 400
    # word 0 is "x." (boundary but < 200 words), word 209 = "x." -> first boundary with >= 200 words
    # chunk 1 = words 0..209 -> start 0, end = start of word 209 (= 2*209 + 1 for the extra '.' in word 0) + 2
    s209 = 2 * 209 + 1
    assert spans(t)[0] == (0, s209 + 2)
    # next chunk starts 20 words before the end of chunk 1 = word 190 -> char 2*190 + 1
    assert spans(t)[1][0] == 2 * 190 + 1


def test_newline_is_a_boundary():
    # word 205 is followed by "\n": the chunk ends there (words 0..205)
    t = "x " * 205 + "x\n" + "x " * 400
    s, e = spans(t)[0]
    assert (s, e) == (0, 2 * 205 + 1)
    # a space-only gap is not a boundary: no '.' and no '\n' -> hard cap at word 250
    assert spans("x " * 400)[0] == (0, 2 * 249 + 1)


def test_closing_quote_after_period_is_a_boundary():
    t = "x " * 209 + 'x." ' + "x " * 400
    assert spans(t)[0][1] == 2 * 209 + 3


def test_short_and_degenerate_texts():
    assert spans("") == [] and spans("   \n\t ") == []
    assert spans("  hello world  ") == [(2, 13)]                         # one chunk, trimmed to the words
    t = "w " * 199
    assert spans(t) == [(0, 2 * 198 + 1)]
    # exactly 200 words and no boundary: the chunk ends at word 200?  No: only a boundary or 250 words ends a chunk,
    # so all 200 words form the last chunk.
    assert spans("w " * 200) == [(0, 399)]


def test_no_chunk_contains_only_overlap():
    # 250 + 20 -> after chunk 1 (words 0..249), words 250..269 are new, so a 2nd chunk starts at word 230
    t = "a " * 270
    assert spans(t) == [(0, 499), (460, 539)]
    # exactly 250 words: one chunk only (nothing new after it)
    assert spans("a " * 250) == [(0, 499)]


def test_u2028_and_nul_are_ordinary_characters():
    t = ("a b\x00c " * 100)
    ch = spans(t)
    assert ch[0][0] == 0 and all(0 <= s < e <= len(t) for s, e in ch)


# ---------------------------------------------------------------------------------- independent reference
def reference(text, target=200, max_words=250, overlap=20):
    words = [(m.start(), m.end()) for m in re.finditer(r"\S+", text)]
    out, i = [], 0
    while i < len(words):
        j = min(i + max_words, len(words))                        # exclusive end index
        cut = None
        for k in range(i + target, j + 1):                        # chunk of k - i words, k - i >= target
            if k > len(words):
                break
            e = words[k - 1][1]
            gap_end = words[k][0] if k < len(words) else len(text)
            if text[e - 1] in ".!?" or (text[e - 1] in ck._CLOSERS and e >= 2 and text[e - 2] in ".!?") \
                    or "\n" in text[e:gap_end]:
                cut = k
                break
        if cut is None:
            cut = j
        out.append((words[i][0], words[cut - 1][1]))
        if cut >= len(words):
            break
        i = cut - overlap
    return out


def rand_text(rng):
    alpha = ["a", "bb", "ccc", "d.", "e!", "f?", 'g."', "h\n", "i", "j ", "\x00", "k)", "l,"]
    n = rng.choice([0, 1, 5, 199, 200, 201, 249, 250, 251, 270, 500, 900, 1500])
    seps = [" ", " ", " ", "  ", "\n", "\t", " \n "]
    parts = []
    for _ in range(n):
        parts.append(rng.choice(alpha) + rng.choice(seps))
    return rng.choice(["", " ", "\n"]) + "".join(parts)


def test_fuzz_against_reference_and_invariants():
    rng = random.Random(1234)
    for _ in range(300):
        t = rand_text(rng)
        got = spans(t)
        assert got == reference(t), t[:60]
        covered = bytearray(len(t))
        prev_start = -1
        for s, e in got:
            assert 0 <= s < e <= len(t) and s > prev_start        # inside the text, strictly increasing starts
            prev_start = s
            assert len(re.findall(r"\S+", t[s:e])) <= 250
            for i in range(s, e):
                covered[i] = 1
        for i, c in enumerate(t):
            if not c.isspace():
                assert covered[i], (i, t[:40])                    # every non-whitespace char lies in some chunk


# ---------------------------------------------------------------------------------- caps
def toy_count(texts):
    return [len(t.split()) + 2 for t in texts]                    # words + [CLS] + [SEP]


def test_split_to_caps_is_contiguous_and_loses_nothing():
    t = " ".join(f"w{i}" for i in range(1000))
    pieces = ck.split_to_caps(t, 0, len(t), toy_count, max_tokens=102, max_chars=10**9)
    assert pieces[0][0] == 0 and pieces[-1][1] == len(t)
    for (a, b, n), (c, d, m) in zip(pieces, pieces[1:]):
        assert b == c                                              # contiguous, no gap, no overlap
    assert all(n <= 102 for _, _, n in pieces)
    assert "".join(t[a:b] for a, b, _ in pieces) == t
    assert [w for a, b, _ in pieces for w in t[a:b].split()] == t.split()      # no word is cut in half
    assert len(pieces) >= 10                                       # 1000 words / 100 per piece at least


def test_split_by_characters_when_no_whitespace():
    t = "x" * 12000
    pieces = ck.split_to_caps(t, 0, len(t), toy_count, max_tokens=500, max_chars=5000)
    assert all(b - a <= 5000 for a, b, _ in pieces) and "".join(t[a:b] for a, b, _ in pieces) == t
    assert len(pieces) == 4                                        # 12000 -> 6000+6000 -> 4 x 3000


def test_chunk_document_applies_cap_and_marks_split():
    t = ("longword" * 40 + " ") * 30                              # 30 words of 320 chars: 9600 chars > 5000
    out = list(ck.chunk_document(t, toy_count))
    assert len(out) >= 2 and all(split for _, _, _, split, _ in out)
    assert all(e - s <= 5000 for s, e, *_ in out)
    assert out[0][0] == 0 and out[-1][1] == len(t.rstrip())


def test_real_tokenizer_counts_and_caps():
    count = ck.make_counter(ck.tokenizer_file())
    assert count(["Hello world"]) == [4]                           # [CLS] hello world [SEP]
    assert count([""]) == [2]
    t = ("alpha beta gamma delta. " * 300)
    for s, e, n, split, hard in ck.chunk_document(t, count):
        assert n == count([t[s:e]])[0] and n <= ck.MAX_TOKENS
    garbage = " ".join("xq%dzv%dkj" % (i, i * 7) for i in range(400))          # many word pieces per word
    for s, e, n, split, hard in ck.chunk_document(garbage, count):
        assert n == count([garbage[s:e]])[0] and n <= ck.MAX_TOKENS and e - s <= ck.MAX_CHARS
