"""The frontier's fixed origin, and World.shift_x with its hooks."""

import re
from collections import Counter

import pytest

from swarmworld.server.persistence import restore
from swarmworld.server.public import Publisher
from swarmworld.server.state import ServerState
from swarmworld.world import registry
from swarmworld.world.actions import start_walk
from swarmworld.world.catalog import Catalog
from swarmworld.world.packs.underground import add_portal
from swarmworld.world.model import CORE_SHIFT_STORES, Creature, FrontierSettings, World, shift_key
from swarmworld.world.packs.frontier import grow
from swarmworld.world.simulation import Simulation
from swarmworld.world.terrain import generate_world


def test_a_world_that_never_grew_has_its_origin_at_zero():
    w = generate_world(7, 48, 48)
    assert (w.origin_x, w.home_width, w.center, w.home_bounds()) == (0, 48, (24, 24), (0, 0, 48, 48))
    assert "frontier" not in w.ext


def test_an_old_save_keeps_its_middle(prepack_save):
    st = ServerState(seed=1)
    restore(st, prepack_save)
    w = st.world
    assert (w.center, w.origin_x, w.home_width) == ((32, 32), 0, 64)
    assert "frontier" not in w.ext


def test_center_follows_the_home_lands():
    w = World(64, 64, [["g"] * 64 for _ in range(64)], Catalog.load())
    w.frontier_record()["origin_x"] = 32
    for row in w.tiles:
        row[:0] = ["g"] * 32
    w.width = 96
    assert w.center == (64, 32) and w.home_bounds() == (32, 0, 96, 64) and w.home_width == 64


def test_shift_key_and_the_core_store():
    assert shift_key("12,5", 32) == "44,5"
    assert CORE_SHIFT_STORES == ("object.data.home",)


def _populated(two_levels, path=((4, 5), (5, 5), (6, 5))):
    w = two_levels(24)
    ada = Creature("c1", "Ada", 3, 5)
    ada.activity = {"path": list(path)}
    ada.seen_pos = {"ula": (7, 8, 10)}
    ada.spots = {"rock": (9, 9, 11)}
    w.creatures[ada.id] = ada
    cow = w.add_object("cow", 10, 3, home=[10, 3])
    w.drop_items(2, 2, Counter({"stick": 1}))
    w.set_tile(1, 1, "d")
    w.skylight = {(5, 60)}
    w.landmarks = [{"name": "x", "x": 4, "y": 4, "kind": "camp"}]
    w.emit("say", None, 6, 6, "hi")
    return w, ada, cow


def test_shift_moves_every_core_store(two_levels):
    w, ada, cow = _populated(two_levels)
    w.shift_x(32)
    assert (ada.x, ada.y) == (35, 5) and ada.activity["path"] == [(36, 5), (37, 5), (38, 5)]
    assert ada.seen_pos == {"ula": (39, 8, 10)} and ada.spots == {"rock": (41, 9, 11)}
    assert (cow.x, cow.data["home"]) == (42, [42, 3]) and w.grid[(42, 3)] == cow.id and (10, 3) not in w.grid
    assert set(w.ground) == {(34, 2)} and "pile:34:2" in w.changed_objects and "pile:2:2" not in w.changed_objects
    assert w.changed_tiles == {(33, 1): "d"} and w.skylight == {(37, 60)}
    assert w.landmarks[0]["x"] == 36 and w.events[-1].x == 38
    assert (w.origin_x, w.home_width, w.width) == (32, 24, 24)  # the tiles are not touched


def test_removed_piles_move_too(two_levels):
    w = two_levels(24)
    w.removed_objects.add("pile:3:4")
    w.shift_x(8)
    assert w.removed_objects == {"pile:11:4"}


def test_a_path_of_lists_stays_lists(two_levels):
    w, ada, _ = _populated(two_levels, path=([4, 5], [5, 5]))
    w.shift_x(32)
    assert ada.activity["path"] == [[36, 5], [37, 5]]


def test_shift_hooks_run_in_order_and_leave_with_the_sandbox(two_levels):
    w = two_levels(24)
    with registry.sandbox():
        calls = []
        registry.register_shift_hook("probe a", lambda w, n: calls.append(("a", n)), stores=("ext.probe.a",))
        registry.register_shift_hook("probe b", lambda w, n: calls.append(("b", n)))
        with pytest.raises(ValueError, match="probe a"):
            registry.register_shift_hook("probe a", lambda w, n: None)
        w.shift_x(5)
        assert calls == [("a", 5), ("b", 5)] and "ext.probe.a" in registry.shift_stores()
    assert not {h.name for h in registry.SHIFT_HOOKS} & {"probe a", "probe b"}


def test_a_failing_shift_hook_stops_the_shift(two_levels):
    w = two_levels(24)
    with registry.sandbox():
        calls = []

        def boom(w, n):
            raise RuntimeError("shift boom")
        registry.register_shift_hook("boom", boom)
        registry.register_shift_hook("after", lambda w, n: calls.append(n))
        with pytest.raises(RuntimeError, match="shift boom"):  # the frontier takes the growth back (its tests)
            w.shift_x(3)
        assert calls == []


def test_shifting_rolls_nothing(two_levels):
    w, _, _ = _populated(two_levels)
    state = w.rng.getstate()
    w.shift_x(32)
    assert w.rng.getstate() == state
    with pytest.raises(ValueError):
        w.shift_x(0)


def test_the_lake_the_meadow_and_the_terminals_stay_with_the_home_lands():
    w = generate_world(7, 48, 48)
    sim = Simulation(w)

    def named():
        sim._landmarks()
        return {lm["name"]: (lm["x"], lm["y"]) for lm in w.landmarks
                if lm["name"] in ("the lake", "the meadow") or lm["name"].endswith(" terminal")}
    before = named()
    assert "the meadow" in before
    w.frontier_record()
    for row in w.tiles:
        row.extend(["W"] * 16)
    w.width = 64
    w.tiles_version += 1
    assert named() == before


def test_the_lake_and_the_meadow_follow_the_origin_when_land_goes_in_west():
    w = generate_world(7, 48, 48)
    sim = Simulation(w)

    def named():
        sim._landmarks()
        return {lm["name"]: (lm["x"], lm["y"]) for lm in w.landmarks if lm["name"] in ("the lake", "the meadow")}
    before = named()
    assert set(before) == {"the lake", "the meadow"}
    assert sim._lake() == before["the lake"]
    w.frontier_record()  # taken while the home lands are the whole map
    for row in w.tiles:
        row[:0] = ["W"] * 16  # new land of deep water: it is no lake of the home lands
    w.width = 64
    w.tiles_version += 1
    w.shift_x(16)
    assert w.origin_x == 16 and w.home_bounds() == (16, 0, 64, 48)
    assert named() == {k: (x + 16, y) for k, (x, y) in before.items()}
    assert sim._lake() == (before["the lake"][0] + 16, before["the lake"][1])


# ---------------------------------------------------------------------------------------------------------------
# The canary: every coordinate the world stores moves, and every store of them has a hook.

IGNORED: dict[str, str] = {  # a path that never moves -> why
    "ext.frontier.lands": "land grid coordinates count from origin_x; a shift never moves them",
}
KEY = re.compile(r"-?\d+,-?\d+")
WORD = re.compile(r"[a-z_]+")


def _ints(*vs) -> bool:
    return all(isinstance(v, int) and not isinstance(v, bool) for v in vs)


def _walk(path: str, v):
    """Yields (path, (x, y)) for each position in v, per the store-path rule: a key that isn't [a-z_]+ is `*`, a
    list's items are `[]`."""
    if isinstance(v, dict):
        if _ints(v.get("x"), v.get("y")):
            yield path, (v["x"], v["y"])
        if _ints(v.get("x0")):  # a rectangle, even one missing a corner (flagged all the same)
            yield path, (v["x0"], v.get("y0"))
        if _ints(v.get("x1")):
            yield path, (v["x1"], v.get("y1"))
        for k, item in v.items():
            if isinstance(k, str) and KEY.fullmatch(k):
                x, y = k.split(",")
                yield path, (int(x), int(y))
            yield from _walk(f"{path}.{k if isinstance(k, str) and WORD.fullmatch(k) else '*'}", item)
    elif isinstance(v, (list, tuple)):
        if len(v) in (2, 3) and _ints(*v):  # [x, y], or [x, y, tick]
            yield path, (v[0], v[1])
        else:
            for item in v:
                yield from _walk(f"{path}[]", item)
    elif isinstance(v, str) and KEY.fullmatch(v):  # an "x,y" string, as a value or a list's item
        x, y = v.split(",")
        yield path, (int(x), int(y))


def coordinate_leaves(world) -> list[tuple[str, tuple[int, int]]]:
    out = list(_walk("ext", world.ext))
    for c in world.creatures.values():
        out += _walk("creature.ext", c.ext)
    for o in world.objects.values():
        out += _walk("object.data", o.data)
    return out


def _covers(store: str, path: str) -> bool:
    return path == store or path.startswith((store + ".", store + "["))


def uncovered(world) -> set[str]:
    stores = registry.shift_stores() | set(CORE_SHIFT_STORES) | set(IGNORED)
    return {path for path, _ in coordinate_leaves(world) if not any(_covers(s, path) for s in stores)}


@pytest.fixture
def everything():
    """A world holding one of everything that has a position (a strip of new land east included), and a Publisher
    that has seen two ticks. A pack that keeps positions puts one of them here."""
    st = ServerState(seed=7, frontier=FrontierSettings(on=True, pace=0))
    w = st.world
    assert grow(w, "east")  # a strip of new land, with its records
    sim = st.sim
    s = w.region("surface")
    deep = w.region("deep")

    def free(x, y):
        return all(w.walkable(x + i, y) and (x + i, y) not in w.grid for i in range(8))
    x0, y0 = next((x, y) for y in range(40, s.y1) for x in range(40, 90) if free(x, y))
    ada = Creature("c1", "Ada", x0, y0)
    w.creatures[ada.id] = ada
    start_walk(w, ada, {(x0 + 6, y0)}, "east", "You arrive.")
    assert ada.activity["path"]
    ada.seen_pos = {"ula": (x0 + 1, y0 + 1, 5)}
    ada.spots = {"rock": (x0 + 2, y0 + 1, 6)}
    ada.ext["nature"] = {"river": [x0 + 3, y0 + 2]}
    w.drop_items(x0 + 4, y0 + 1, Counter({"raw_meat": 1}))
    w.ext["food"]["piles"] = {f"{x0 + 4},{y0 + 1}": {"raw_meat": w.tick}}
    b = w.ext.setdefault("building", {})
    b["sites"] = {"s1": {"x0": x0, "y0": y0 + 2, "x1": x0 + 2, "y1": y0 + 4, "door": None, "start": [x0, y0 + 2]}}
    b["built"] = {"b1": {"design": "hut", "x0": x0 + 4, "y0": y0 + 2, "x1": x0 + 6, "y1": y0 + 4, "door": [x0 + 5, y0 + 4],
                         "start": None}}
    d = w.ext.setdefault("digging", {})
    for what, v in (("work", {"n": 1, "by": []}), ("shafts", {"n": 1, "by": []}), ("dug", "g"), ("filling", 7),
                    ("made_water", 9)):
        d[what] = {f"{x0 + 5},{y0 + 5}": v}
    up, down = (x0 + 1, y0 + 6), (x0 + 1, deep.y0 + 5)
    portal = add_portal(w, "shaft", "a shaft", up, down)
    portal["chamber"] = [[down[0], down[1] + 1], [down[0], down[1] + 2]]
    w.add_object("cow", x0 + 2, y0 + 6, home=[x0 + 2, y0 + 6])
    w.skylight.add((x0 + 3, deep.y0 + 3))
    w.set_tile(x0, y0 + 7, "d")
    sim._landmarks()
    w.emit("say", ada.id, x0, y0, "hi")
    pub = Publisher(st)
    pub.observe(st.tick_dict([]), [])
    w.tick += 1
    pub.observe(st.tick_dict([]), [])
    w.drop_items(x0 + 5, y0 + 1, Counter({"stick": 1}))
    w.set_tile(x0 + 1, y0 + 7, "d")  # still waiting for the next tick message
    return st, pub


def positions(st) -> dict[str, list[tuple[int, int]]]:
    w = st.world
    out = {
        "creature": [(c.x, c.y) for c in w.creatures.values()],
        "path": [tuple(p[:2]) for c in w.creatures.values() for p in (c.activity or {}).get("path", ())],
        "seen_pos": [tuple(p[:2]) for c in w.creatures.values() for p in c.seen_pos.values()],
        "spots": [tuple(p[:2]) for c in w.creatures.values() for p in c.spots.values()],
        "object": [(o.x, o.y) for o in w.objects.values()],
        "grid": list(w.grid),
        "ground": list(w.ground),
        "changed_objects": [(int(x), int(y)) for oid in sorted(w.changed_objects) if oid.startswith("pile:")
                            for _, x, y in [oid.split(":")]],
        "changed_tiles": list(w.changed_tiles),
        "skylight": sorted(w.skylight),
        "landmarks": [(lm["x"], lm["y"]) for lm in w.landmarks],
        "events": [(e.x, e.y) for e in w.events],
    }
    for path, pt in coordinate_leaves(w):
        if not any(_covers(s, path) for s in IGNORED):
            out.setdefault(path, []).append(pt)
    return out


def publisher_positions(pub) -> dict[str, list[tuple[int, int]]]:
    out = {f"publisher.trail.{cid}": [(x, y) for _, x, y in trail] for cid, trail in pub._trails.items()}
    return out | {"publisher.tiles": list(pub._tiles),
                  "publisher.tile_entries": [(e[0], e[1]) for e in pub._tiles.values()]}


def test_every_position_moves_together(everything):
    st, pub = everything
    before = positions(st) | publisher_positions(pub)
    assert all(before.values()), [k for k, v in before.items() if not v]  # the fixture holds something in every store
    st.world.shift_x(32)
    after = positions(st)  # read before a tick message takes the changed tiles
    pub.observe(st.tick_dict([]), [])  # the publisher notices the new origin on its next tick
    after |= publisher_positions(pub)
    assert any(k.startswith("publisher.trail.") for k in before)
    for k, pts in before.items():
        moved = [(x + 32, y) for x, y in pts]
        if k == "changed_objects":  # sorted by id, and the ids changed
            assert sorted(after[k]) == sorted(moved), k
        elif k.startswith("publisher.trail."):  # a trail gains this tick's position, and may lose its oldest
            assert after[k][:-1] == moved[len(moved) - len(after[k]) + 1:], k
        else:
            assert after[k][:len(pts)] == moved, k


def test_no_store_of_positions_goes_unshifted(everything):
    assert uncovered(everything[0].world) == set()


def test_the_canary_sings(everything):
    w = everything[0].world
    w.ext["probe"] = {"camp": [3, 4], "seen": {"5,6": 1}, "trail": [[1, 2, 99]], "at": "7,8", "marks": ["9,10"],
                      "box": {"x0": 1, "y0": 2}, "flag": [True, False], "name": "a,b"}
    cow = next(o for o in w.objects.values() if o.kind == "cow")
    cow.data["roost"] = {"x": 1, "y": 2}
    assert uncovered(w) == {"ext.probe.camp", "ext.probe.seen", "ext.probe.trail[]", "ext.probe.at",
                            "ext.probe.marks[]", "ext.probe.box", "object.data.roost"}


def test_every_declared_store_holds_something_in_the_fixture(everything):
    paths = {p for p, _ in coordinate_leaves(everything[0].world)}
    empty = {s for s in registry.shift_stores() if not any(_covers(s, p) for p in paths)}
    assert not empty, empty
