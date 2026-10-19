"""D3 - sealed rank bands.

Every claim gets a rank 0..n-1. Bands are consecutive blocks of `band_size` ranks. Pool = bands < pool_bands.
The remaining bands are sealed. Ranks come from a seeded permutation that is interleaved by veracity label, so
that every band (and every prefix of the ranking) contains the labels in roughly their overall proportions.

Interleaving rule (deterministic): inside each label group the claim ids are sorted and shuffled with
random.Random(seed); the i-th claim of a group of size n gets the sort key (i + u) / n with u ~ U[0, 1) drawn from
the same generator; claims are ordered by (key, claim_id). A group's members are therefore spread evenly over the
whole ranking and, in any window of w ranks, a group of share p contributes about w * p claims.
"""
from __future__ import annotations

import json
import random
from collections import defaultdict

BAND_SIZE = 30
POOL_BANDS = 6
SEED = 42


def stratified_order(ids: list[int], labels: dict[int, str], rng: random.Random) -> list[int]:
    groups: dict[str, list[int]] = defaultdict(list)
    for i in sorted(ids):
        groups[str(labels.get(i))].append(i)
    keyed = []
    for lab in sorted(groups):                       # sorted label order => deterministic draw order
        g = groups[lab]
        rng.shuffle(g)
        n = len(g)
        for i, cid in enumerate(g):
            keyed.append(((i + rng.random()) / n, cid))
    keyed.sort()
    return [cid for _, cid in keyed]


def load_old_split(path: str) -> tuple[list[int], list[int]]:
    """Old split file -> (pooled ids, held-out ids). ASSUMED layout: a JSON object with two id lists whose keys
    contain 'pool'/'train'/'dev' and 'held'/'test' respectively (the real file was not available when written)."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    pooled = held = None
    for k, v in data.items():
        if not isinstance(v, list):
            continue
        kl = k.lower()
        if "held" in kl or "test" in kl:
            held = [int(x) for x in v]
        elif "pool" in kl or "train" in kl or "dev" in kl:
            pooled = [int(x) for x in v]
    if pooled is None or held is None:
        raise ValueError(f"cannot find pooled/held-out id lists in {path}; keys: {list(data)}")
    return pooled, held


def build_ranks(ids: list[int], labels: dict[int, str], seed: int = SEED,
                old_pooled: list[int] | None = None, old_held: list[int] | None = None) -> dict[int, int]:
    """claim_id -> rank. With an old split: old pooled claims take the first ranks, old held-out the rest."""
    rng = random.Random(seed)
    idset = set(ids)
    if old_pooled is None:
        order = stratified_order(list(idset), labels, rng)
    else:
        a = [i for i in old_pooled if i in idset]
        b = [i for i in (old_held or []) if i in idset]
        rest = sorted(idset - set(a) - set(b))
        if rest:
            raise ValueError(f"{len(rest)} claims are in neither part of the old split: {rest[:10]}")
        order = stratified_order(a, labels, rng) + stratified_order(b, labels, rng)
    return {cid: r for r, cid in enumerate(order)}


def band_of(rank: int, band_size: int = BAND_SIZE) -> int:
    return rank // band_size
