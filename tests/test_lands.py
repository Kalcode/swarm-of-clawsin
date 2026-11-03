import random
import time
from collections import Counter

import pytest

from swarmworld.world.lands import (BLEND_CHANCE, LAND, THEMES, Edge, choose_theme, column_edge, generate_land, need,
                                    row_edge)
from swarmworld.world.terrain import FLOW_STEP, TERMINAL_READY, generate_world
from swarmworld.world.perception import DIRS

MEADOW = Edge("g" * 32, "m" * 32, "." * 32)
NO_NEED = {"stone": 0.0, "wood": 0.0, "food": 0.0}


def _count(land, *kinds):
    return sum(1 for k, *_ in land.objects if k in kinds)


def _share(land, biome):
    return sum(row.count(biome) for row in land.biomes) / (LAND * LAND)


def test_the_same_inputs_make_the_same_land():
    a = generate_land(7, 1, 2, (32, 32), {"west": MEADOW}, NO_NEED)
    assert a == generate_land(7, 1, 2, (32, 32), {"west": MEADOW}, NO_NEED)
    assert generate_land(7, 2, 2, (32, 32), {"west": MEADOW}, NO_NEED).tiles != a.tiles
    assert generate_land(8, 1, 2, (32, 32), {"west": MEADOW}, NO_NEED).tiles != a.tiles


def test_the_blend_values_are_the_spec_s():
    assert LAND == 32 and BLEND_CHANCE == (0.8, 0.6, 0.4, 0.2)


@pytest.mark.parametrize("theme", list(THEMES))
def test_every_theme_keeps_its_promises(theme):
    for seed in range(5):
        land = generate_land(seed, 1, 0, (32, 32), {"west": MEADOW}, NO_NEED, theme=theme)
        assert land.theme == theme
        for rows in (land.tiles, land.biomes, land.flow):
            assert len(rows) == 32 and all(len(r) == 32 for r in rows)
        seen = set()
        for kind, x, y, data in land.objects:
            assert 0 <= x < 32 and 0 <= y < 32
            assert land.tiles[y][x] not in "wW", (kind, x, y)
            assert (x, y) not in seen
            seen.add((x, y))
        hx, hy = land.heart
        assert 0 <= hx < 32 and 0 <= hy < 32
        if theme == "stony_hills":
            h = [(x, y) for y in range(32) for x in range(32) if land.biomes[y][x] == "h"]
            assert len(h) >= 0.6 * 1024
            assert sum(land.tiles[y][x] == "r" for x, y in h) >= 0.8 * len(h)
            assert _count(land, "rock") >= 12 and _count(land, "flint_outcrop") >= 2
            assert _count(land, "iron_vein", "copper_vein") >= 2
            assert all(d == {"ore": 8} for k, _, _, d in land.objects if k in ("iron_vein", "copper_vein"))
            mx, my = land.mouth
            assert land.tiles[my][mx] == "r" and (mx, my) not in seen
            assert 4 <= mx <= 27 and 4 <= my <= 27
        else:
            assert land.mouth is None
        if theme == "berry_groves":
            assert sum(1 for k, _, _, d in land.objects if k == "bush" and d.get("berries") == 6) >= 25
            assert sum(1 for k, _, _, d in land.objects if k == "tree" and d.get("wood") == 6) >= 4
        if theme == "deep_pines":
            assert _share(land, "p") >= 0.6
            assert sum(1 for k, _, _, d in land.objects if k == "pine" and d.get("wood") == 6) >= 60
            assert _count(land, "mushroom_patch") >= 3
        if theme == "marsh":
            assert _share(land, "k") >= 0.5
            assert _count(land, "reed_bed") >= 8
            assert sum(1 for k, _, _, d in land.objects if k == "clay" and d.get("clay") == 6) >= 3
            assert sum(r.count("w") for r in land.tiles) >= 10
        if theme == "lake":
            assert sum(r.count("W") for r in land.tiles) >= 20
            assert _count(land, "reed_bed") >= 3 and _count(land, "clay") >= 2
            assert land.tiles[hy][hx] == "W"
        if theme == "plains":
            assert _share(land, "m") >= 0.7
            assert _count(land, "sheep", "cow") >= 3
        if theme == "ruins":
            tablets = [d for k, _, _, d in land.objects if k == "tablet"]
            assert len(tablets) == 1 and "TERMINAL" not in tablets[0]["text"]
            assert _count(land, "rock") >= 6
            assert ("tablet", hx, hy, tablets[0]) in land.objects


def test_ruins_rarely_hold_a_terminal():
    found = 0
    for seed in range(60):
        land = generate_land(seed, 3, 1, (32, 32), {"west": MEADOW}, NO_NEED, theme="ruins")
        terms = [d for k, _, _, d in land.objects if k == "terminal"]
        assert len(terms) <= 1
        for d in terms:
            assert d["ruin"] is True and d["screen"] == list(TERMINAL_READY) and d["code"] == "" and d["memory"] == {}
        found += len(terms)
    assert 1 <= found <= 25


def test_the_seam_blends_into_its_neighbour():
    w = generate_world(7, 48, 48)
    edge = column_edge(w, 47, 0, 32)
    assert len(edge.tiles) == len(edge.biomes) == len(edge.flow) == 32
    land = generate_land(7, 1, 0, (32, 32), {"west": edge}, NO_NEED, theme="deep_pines")
    rows = [y for y in range(32) if edge.tiles[y] not in "wW"]

    def same(col):
        return sum(land.biomes[y][col] == edge.biomes[y] for y in rows) / len(rows)

    assert same(0) >= 0.6
    assert same(3) < same(0)
    assert sum(land.biomes[y][8] == "p" for y in rows) / len(rows) >= 0.6


def test_a_land_below_fits_the_one_above():
    upper = generate_land(3, 0, 0, (32, 32), {}, NO_NEED, theme="stony_hills")
    north = row_edge(upper, 31)
    assert north.tiles == upper.tiles[31] and north.biomes == upper.biomes[31] and north.flow == upper.flow[31]
    low = generate_land(3, 0, 1, (32, 32), {"north": north}, NO_NEED, theme="plains")
    assert sum(low.biomes[0][x] == north.biomes[x] for x in range(32)) / 32 >= 0.6


def test_a_river_crossing_the_seam_flows_on():
    edge = Edge("g" * 10 + "w" + "g" * 21, "m" * 32, "." * 10 + "0" + "." * 21)
    for seed in range(5):
        land = generate_land(seed, 1, 0, (32, 32), {"west": edge}, NO_NEED, theme="plains")
        starts = [y for y in range(9, 12) if land.tiles[y][0] == "w" and land.flow[y][0] != "."
                  and FLOW_STEP[DIRS[int(land.flow[y][0])]][0] == 1]
        assert starts, seed
        _follow(land, starts[0])


def _follow(land, y, x=0):
    seen = set()
    while True:
        assert (x, y) not in seen
        seen.add((x, y))
        code = land.flow[y][x]
        assert land.tiles[y][x] in "wW"
        if code == ".":
            return "still", (x, y)
        dx, dy = FLOW_STEP[DIRS[int(code)]]
        x, y = x + dx, y + dy
        assert x >= 0
        if not (0 <= x < 32 and 0 <= y < 32):
            assert x >= 32 or y >= 32
            return "off", (x, y)


@pytest.mark.parametrize("theme", ["marsh", "lake"])
def test_a_river_ends_in_the_marsh_or_the_lake(theme):
    edge = Edge("g" * 14 + "ww" + "g" * 16, "m" * 32, "." * 14 + "00" + "." * 16)
    for seed in range(5):
        land = generate_land(seed, 1, 0, (32, 32), {"west": edge}, NO_NEED, theme=theme)
        starts = [y for y in range(13, 17) if land.tiles[y][0] == "w" and land.flow[y][0] != "."]
        assert starts, seed
        how, (x, y) = _follow(land, starts[0])
        assert how == "still" and 0 <= x < 32 and land.tiles[y][x] in "wW"


def test_need_weights_the_theme():
    def counts(nd):
        rng = random.Random(1)
        return Counter(choose_theme(rng, {"west": MEADOW}, nd) for _ in range(300))

    calm, hungry = counts(NO_NEED), counts({"stone": 1.0, "wood": 0.0, "food": 0.0})
    assert hungry.most_common(1)[0][0] == "stony_hills"
    assert hungry["stony_hills"] >= 1.5 * calm["stony_hills"]
    assert hungry["ruins"] < 0.08 * 300 and calm["ruins"] < 0.08 * 300


def test_water_and_rock_at_the_seam_favour_their_themes():
    def counts(edge):
        rng = random.Random(2)
        return Counter(choose_theme(rng, {"west": edge}, NO_NEED) for _ in range(300))

    wet = counts(Edge("w" * 32, "m" * 32, "." * 32))
    assert wet["marsh"] + wet["lake"] + wet["plains"] > 0.6 * 300
    rocky = counts(Edge("r" * 32, "h" * 32, "." * 32))
    assert rocky.most_common(1)[0][0] == "stony_hills"


def test_need_reads_the_census():
    w = generate_world(7)
    n = need(w)
    assert set(n) == {"stone", "wood", "food"} and all(0.0 <= v < 1.0 for v in n.values())
    for oid in [o.id for o in w.objects.values() if o.kind in ("rock", "flint_outcrop", "iron_vein", "copper_vein")]:
        w.remove_object(oid)
    assert need(w)["stone"] == 1.0


def test_a_land_is_quick():
    for theme in THEMES:
        t = time.perf_counter()
        generate_land(1, 1, 0, (32, 32), {"west": MEADOW, "north": MEADOW}, NO_NEED, theme=theme)
        assert time.perf_counter() - t < 0.1, theme


def test_a_short_land_fits_its_size():
    land = generate_land(1, 1, 1, (32, 16), {"west": MEADOW}, NO_NEED, theme="lake")
    assert len(land.tiles) == 16 and all(len(r) == 32 for r in land.tiles)
    assert 0 <= land.heart[1] < 16
