"""The frontier's fixed origin, and World.shift_x with its hooks."""

import logging
from collections import Counter

import pytest

from swarmworld.server.persistence import restore
from swarmworld.server.state import ServerState
from swarmworld.world import registry
from swarmworld.world.catalog import Catalog
from swarmworld.world.model import CORE_SHIFT_STORES, Creature, World, shift_key
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


def test_a_failing_shift_hook_is_logged_and_the_rest_run(two_levels, caplog):
    w = two_levels(24)
    with registry.sandbox():
        calls = []

        def boom(w, n):
            raise RuntimeError("shift boom")
        registry.register_shift_hook("boom", boom)
        registry.register_shift_hook("after", lambda w, n: calls.append(n))
        with caplog.at_level(logging.ERROR, logger="swarmworld.packs"):
            w.shift_x(3)
        assert calls == [3] and "shift boom" in caplog.text
        assert w.origin_x == 3


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
