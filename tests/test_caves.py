import random
import time
from collections import deque

import pytest

from swarmworld.world.caves import BORDER, carve_chamber, carve_deep, carve_passage

OPEN = "cu"


def _reach(open_tiles, start):
    seen, q = {start}, deque([start])
    while q:
        x, y = q.popleft()
        for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if n in open_tiles and n not in seen:
                seen.add(n)
                q.append(n)
    return seen


@pytest.mark.parametrize("size", [40, 64, 128])
def test_deep_is_one_connected_cave(size):
    for seed in range(5):
        rows = carve_deep(random.Random(seed), size, size).rows
        tiles = {(x, y) for y, r in enumerate(rows) for x, t in enumerate(r) if t in OPEN}
        assert tiles and _reach(tiles, next(iter(tiles))) == tiles


@pytest.mark.parametrize("size", [40, 64, 128])
def test_every_seed_gives_a_connected_bordered_deep_within_the_floor_bounds(size):
    for seed in range(60 if size < 128 else 25):
        rows = carve_deep(random.Random(seed), size, size).rows
        assert len(rows) == size and all(len(r) == size for r in rows)
        for y, r in enumerate(rows):
            for x, t in enumerate(r):
                if min(x, y, size - 1 - x, size - 1 - y) < BORDER:
                    assert t == "R", (seed, x, y)
        tiles = {(x, y) for y, r in enumerate(rows) for x, t in enumerate(r) if t in OPEN}
        assert 0.30 <= len(tiles) / size**2 <= 0.55, seed
        assert _reach(tiles, next(iter(tiles))) == tiles, seed
        assert sum(r.count("u") for r in rows) >= 20, seed


@pytest.mark.parametrize("size", [40, 64, 128])
def test_floor_fraction_and_water(size):
    for seed in range(5):
        d = carve_deep(random.Random(seed), size, size)
        flat = "".join(d.rows)
        assert 0.30 <= sum(t in OPEN for t in flat) / len(flat) <= 0.55
        assert flat.count("u") >= 20
        px, py = d.pool
        for x, y in ((px, py), (px + 1, py), (px - 1, py), (px, py + 1), (px, py - 1)):
            assert d.rows[y][x] == "u"
        assert d.caverns == sorted(d.caverns, key=lambda c: -c[2])


def test_same_rng_same_deep():
    assert carve_deep(random.Random(5), 64, 64).rows == carve_deep(random.Random(5), 64, 64).rows
    assert carve_deep(random.Random(5), 64, 64).rows != carve_deep(random.Random(6), 64, 64).rows


def test_carving_a_128_deep_is_quick():
    best = 9.0
    for _ in range(2):
        t = time.perf_counter()
        carve_deep(random.Random(3), 128, 128)
        best = min(best, time.perf_counter() - t)
    assert best < 1.0  # typically ~0.1 s; this catches a slide to seconds


def _rock_deep(two_levels, size=24):
    w = two_levels(size)
    y0 = w.region("deep").y0
    for y in range(y0, w.height):
        for x in range(size):
            w.tiles[y][x] = "R"
    return w, y0


def test_carve_chamber_respects_the_border(two_levels):
    w, y0 = _rock_deep(two_levels)
    opened = carve_chamber(w, 0, y0, 3)
    assert opened and all(x >= BORDER and y >= y0 + BORDER for x, y in opened)
    assert all(w.tile(x, y0 + 1) == "R" and w.tile(1, y0 + y) == "R" for x in range(24) for y in range(24))
    mid = carve_chamber(w, 12, y0 + 12, 2)
    assert (12, y0 + 12) in mid and len(mid) == 21 and all(w.tile(*p) == "c" for p in mid)


def test_carve_passage_joins_the_nearest_floor(two_levels):
    w, y0 = _rock_deep(two_levels)
    pocket = [(x, y0 + y) for x in range(15, 19) for y in range(5, 9)]
    for p in pocket:
        w.set_tile(*p, "c")
    start = (4, y0 + 15)
    changed = carve_passage(w, start)
    assert start in changed and changed
    open_ = {(x, y) for y in range(y0, w.height) for x in range(24) if w.tile(x, y) in OPEN}
    assert start in _reach(open_, pocket[0])  # joined orthogonally


def test_carve_passage_from_a_small_pocket_reaches_the_main_system(two_levels):
    w, y0 = _rock_deep(two_levels)
    big = [(x, y0 + y) for x in range(14, 20) for y in range(4, 10)]
    own = [(4, y0 + 16), (5, y0 + 16)]
    for p in big + own:
        w.set_tile(*p, "c")
    carve_passage(w, own[0])
    open_ = {(x, y) for y in range(y0, w.height) for x in range(24) if w.tile(x, y) in OPEN}
    assert own[0] in _reach(open_, big[0])
    assert carve_passage(w, own[0]) == []  # already part of it


def test_carve_passage_avoid_sends_it_to_the_other_group(two_levels):
    w, y0 = _rock_deep(two_levels)
    near = [(x, y0 + y) for x in range(6, 10) for y in range(10, 14)]  # nearest to the start, 16 tiles
    far = [(x, y0 + y) for x in range(14, 21) for y in range(14, 21)]  # 49 tiles
    for p in near + far:
        w.set_tile(*p, "c")
    start = (4, y0 + 20)
    carve_passage(w, start, avoid=set(near))
    open_ = {(x, y) for y in range(y0, w.height) for x in range(24) if w.tile(x, y) in OPEN}
    assert start in _reach(open_, far[0])
    assert all(w.tile(*p) == "c" for p in near)
    assert (start[0], start[1] - 1) not in near
