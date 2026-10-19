"""D3 rank bands: hand-checkable properties."""
from evret import pool

LAB = lambda i: "R" if i < 183 else "S" if i < 256 else "N" if i < 277 else "C"      # noqa: E731


def test_bands_and_determinism():
    ids = list(range(300))
    labels = {i: LAB(i) for i in ids}
    r1, r2 = pool.build_ranks(ids, labels, 42), pool.build_ranks(ids, labels, 42)
    assert r1 == r2 and sorted(r1.values()) == list(range(300))
    assert pool.build_ranks(ids, labels, 7) != r1
    assert pool.band_of(29) == 0 and pool.band_of(30) == 1 and pool.band_of(299) == 9


def test_every_band_mixes_labels_proportionally():
    ids = list(range(300))
    labels = {i: LAB(i) for i in ids}
    r = pool.build_ranks(ids, labels, 42)
    for b in range(10):
        cnt = {}
        for c, rk in r.items():
            if rk // 30 == b:
                cnt[labels[c]] = cnt.get(labels[c], 0) + 1
        # expected per band: R 18.3, S 7.3, N 2.1, C 2.3; stratification keeps R and S within +-2
        assert abs(cnt.get("R", 0) - 18.3) <= 2 and abs(cnt.get("S", 0) - 7.3) <= 2
        assert cnt.get("N", 0) + cnt.get("C", 0) >= 1


def test_old_split_takes_first_ranks():
    ids = list(range(10))
    labels = {i: "a" if i % 2 else "b" for i in ids}
    old_pool, old_held = [0, 1, 2, 3, 4, 5], [6, 7, 8, 9]
    r = pool.build_ranks(ids, labels, 42, old_pool, old_held)
    assert {c for c, k in r.items() if k < 6} == set(old_pool)
    assert {c for c, k in r.items() if k >= 6} == set(old_held)
