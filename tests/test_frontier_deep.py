"""The deep under a frontier strip: solid rock with stocked pockets; stony hills open a cave into one."""

import random
from collections import deque

import numpy as np
import pytest

from swarmworld.world.actions import bfs_path
from swarmworld.world.caves import BORDER, MIN_POCKET, _components, carve_passage, carve_pockets
from swarmworld.world.model import FrontierSettings
from swarmworld.world.packs import digging, underground
from swarmworld.world.packs.frontier import grow
from swarmworld.world.terrain import generate_world


def world48(**kw):
    w = generate_world(7, 48, 48)
    w.frontier_settings = FrontierSettings(**{"on": True, "pace": 0, **kw})
    return w


@pytest.mark.parametrize("height", [48, 128])
def test_pockets_are_few_and_walled_in_rock(height):
    for seed in range(10):
        dm = carve_pockets(random.Random(seed), 32, height, 3)
        rows = dm.rows
        assert len(rows) == height and all(len(r) == 32 for r in rows)
        assert set("".join(rows)) <= {"R", "c"}
        assert all(r[:BORDER] == "R" * BORDER and r[-BORDER:] == "R" * BORDER for r in rows)
        assert all(set(r) == {"R"} for r in (*rows[:BORDER], *rows[-BORDER:]))
        floor = np.array([[ch == "c" for ch in r] for r in rows])
        groups = _components(floor)
        assert 1 <= len(groups) <= 3 and all(len(g) >= MIN_POCKET for g in groups)
        assert len(dm.caverns) == len(groups) and dm.caverns[0][2] >= dm.caverns[-1][2]
        assert floor.mean() <= 0.25
        assert carve_pockets(random.Random(seed), 32, height, 3).rows == rows


def test_carve_passage_can_aim_at_given_tiles(two_levels):
    w = two_levels(24)
    y0 = w.region("deep").y0
    for y in range(y0, w.height):
        for x in range(24):
            w.tiles[y][x] = "R"
    big = [(x, y0 + y) for x in range(14, 20) for y in range(4, 10)]  # the main system
    far = [(x, y0 + y) for x in range(4, 7) for y in range(16, 22)]  # a smaller one, near the start
    for p in big + far:
        w.set_tile(*p, "c")
    start = (10, y0 + 19)
    changed = carve_passage(w, start, goals=set(big))
    assert changed and start in changed
    assert not any(p in far for p in changed) and (14, y0 + 9) in set(changed) | set(big)
    seen, todo = {start}, [start]
    while todo:
        x, y = todo.pop()
        for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if n not in seen and w.tile(*n) == "c":
                seen.add(n)
                todo.append(n)
    assert big[0] in seen and far[0] not in seen


def _strip_deep(w, x0=48, x1=80):
    d = w.region("deep")
    return d, [(x, y) for y in range(d.y0, d.y1) for x in range(x0, x1)]


def test_a_strips_deep_is_rock_with_stocked_pockets():
    w = world48()
    deep = w.region("deep")
    old = [w.tiles[y][:48] for y in range(deep.y0, deep.y1)]
    grow(w, "east")
    assert [w.tiles[y][:48] for y in range(deep.y0, deep.y1)] == old
    deep, tiles = _strip_deep(w)
    assert all(w.tile(x, y) == "R" for x in (48, 49, 78, 79) for y in range(deep.y0, deep.y1))
    assert any(w.tile(*p) == "c" for p in tiles)
    objs = [o for o in w.objects.values() if 48 <= o.x < 80 and deep.y0 <= o.y < deep.y1]
    kinds = {o.kind for o in objs}
    assert {"rock", "coal_seam", "cave_mushrooms"} <= kinds and kinds & {"iron_vein", "copper_vein"}
    assert all(w.tile(o.x, o.y) == "c" for o in objs)
    assert not kinds & {"tree", "bush", "berry_bush", "fish", "campfire"}
    assert all(o.data.get("ore") == 8 for o in objs if o.kind in ("iron_vein", "copper_vein"))


def test_stony_hills_open_a_cave_into_a_pocket():
    w = world48()
    grow(w, "east", theme="stony_hills")
    new = [p for p in underground.portals(w) if p["up"][0] >= 48]
    assert new and all(w.below(*p["up"]) == tuple(p["down"]) for p in new)
    assert len({p["name"] for p in underground.portals(w)}) == len(underground.portals(w))
    for p in new:
        assert w.object_at(*p["up"]).kind == "cave_mouth" and w.object_at(*p["down"]).kind == "cave_exit"
        start = tuple(p["down"])
        seen, q = {start}, deque([start])
        while q:
            x, y = q.popleft()
            for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if n not in seen and w.tile(*n) == "c" and (n == start or n not in w.grid or w.walkable(*n)):
                    seen.add(n)
                    q.append(n)
        assert len(seen) >= 16


def test_cave_names_run_out_of_ordinals_gracefully():
    w = world48()
    up = (40, 5)
    names = []
    for i in range(12):
        name = underground.cave_name(w, up)
        names.append(name)
        underground.portals(w).append({"id": f"p{i}", "kind": "cave", "name": name, "up": [0, 0], "down": [0, 0]})
    assert len(set(names)) == 12 and names[1].startswith("the second ") and names[9].startswith("the tenth ")
    assert names[10].endswith(" cave 11") and names[11].endswith(" cave 12")


def test_the_old_deep_can_be_dug_toward_the_new():
    w = world48()
    deep = w.region("deep")
    assert not digging._inside_deep(w, 47, deep.y0 + 10)
    grow(w, "east")
    assert digging._inside_deep(w, 47, deep.y0 + 10)


def test_the_deep_rolls_none_of_the_worlds_dice():
    w = world48()
    state = w.rng.getstate()
    grow(w, "east", theme="stony_hills")
    grow(w, "west", theme="stony_hills")
    assert w.rng.getstate() == state


def _reaches(w, start, kinds):
    """True when a walk (the real bfs_path, corner rule and all) from start ends beside an object of each kind."""
    for kind in kinds:
        spots = {(o.x, o.y) for o in w.objects.values() if o.kind in kind}
        beside = {(x + dx, y + dy) for x, y in spots for dx in (-1, 0, 1) for dy in (-1, 0, 1)}
        beside = {p for p in beside if w.walkable(*p)} | ({start} if start in beside else set())
        if not beside or bfs_path(w, start, beside) is None:
            return False
    return True


@pytest.mark.parametrize("side,seed", [("west", 5), ("east", 36), ("east", 0), ("west", 1), ("east", 2), ("east", 3)])
def test_every_new_cave_reaches_stone_and_metal(side, seed):
    w = generate_world(seed, 48, 48)
    w.frontier_settings = FrontierSettings(on=True, pace=0)
    for sd in (side, side, "east"):
        before = {p["id"] for p in underground.portals(w)}
        grow(w, sd, theme="stony_hills")
        for p in underground.portals(w):
            if p["id"] not in before:
                down = tuple(p["down"])
                assert _reaches(w, down, [("rock",), ("iron_vein", "copper_vein")]), (sd, p["name"])


def test_a_raising_grow_under_leaves_the_world_as_it_was(monkeypatch, caplog):
    import logging
    w = world48()
    before = ([r[:] for r in w.tiles], sorted((o.id, o.kind, o.x, o.y) for o in w.objects.values()), w.width,
              dict(w.ext.get("underground", {})), w.tiles_version, len(w.events))
    real = underground.carve_passage

    def boom(*a, **k):
        real(*a, **k)
        raise RuntimeError("passage boom")
    monkeypatch.setattr(underground, "carve_passage", boom)
    with caplog.at_level(logging.ERROR, logger="swarmworld.packs"):
        assert grow(w, "east", theme="stony_hills") == []
    after = ([r[:] for r in w.tiles], sorted((o.id, o.kind, o.x, o.y) for o in w.objects.values()), w.width,
             dict(w.ext.get("underground", {})), w.tiles_version, len(w.events))
    assert after == before and "frontier" not in w.ext
    assert len([r for r in caplog.records if "passage boom" in r.getMessage()]) == 1
