import json

from swarmworld.server.persistence import restore, save, snapshot
from swarmworld.server.state import ServerState
from swarmworld.world import model
from swarmworld.world.catalog import Catalog
from swarmworld.world.model import Region, World


def _flat(n=10):
    return World(n, n, [["g"] * n for _ in range(n)], Catalog.load())


def test_a_world_starts_as_one_surface_region():
    w = World(10, 10, [["g"] * 10 for _ in range(10)], Catalog.load())
    assert w.regions == [Region("surface", 0, 0, 10, True, True)] and w.center == (5, 5)
    assert w.region_at(3, 9).name == "surface" and w.below(3, 3) is None and w.under_sky(3, 3)
    assert w.region_at(3, 10) is None and w.region_at(-1, 3) is None


def test_add_region_grows_the_map_below_a_band_of_rock(two_levels):
    w = two_levels(24)
    deep = w.region("deep")
    assert (deep.y0, deep.y1, w.height) == (56, 80, 80) and w.center == (12, 12)
    assert all(w.tile(x, y) == "R" for y in range(24, 56) for x in range(24))
    assert w.region_at(5, 30) is None and not w.walkable(5, 30)
    assert w.below(5, 7) == (5, 63) and w.above(5, 63) == (5, 7) and w.above(5, 7) is None
    assert w.same_region((5, 60), (9, 70)) and not w.same_region((5, 7), (5, 63))
    assert not w.same_region((5, 30), (5, 31))
    assert w.region_bounds("deep") == (0, 56, 24, 80) and list(w.view_rows(57, 3)) == [56, 57, 58, 59, 60]
    assert w.region_bounds() == (0, 0, 24, 24) and list(w.view_rows(30, 3)) == []
    assert not w.under_sky(5, 63)
    w.skylight.add((5, 63))
    assert w.under_sky(5, 63)


def test_add_region_refuses_a_bad_row_or_a_second_name(two_levels):
    w = two_levels(10)
    for name, rows in (("other", [["c"] * 9]), ("deep", [["c"] * 10])):
        try:
            w.add_region(name, -2, rows, sky=False, weather=False)
        except ValueError:
            pass
        else:
            raise AssertionError(f"{name} with {len(rows[0])} wide rows was accepted")
    assert w.height == 10 + 32 + 10 and [r.name for r in w.regions] == ["surface", "deep"]


def test_add_region_bumps_the_tiles_version(two_levels):
    w = two_levels(10)
    v = w.tiles_version
    w.add_region("more", -2, [["c"] * 10], sky=False, weather=False)
    assert w.tiles_version > v


def test_day_part_names_the_time_of_day():
    w = _flat()
    seen = set()
    for t in range(0, model.DAY_TICKS, 10):
        w.tick = t
        seen.add(w.day_part())
        assert w.time_text() == f"Day 1, {w.day_part()}"
    assert seen == {"dawn", "morning", "midday", "afternoon", "dusk", "night"}


def test_rock_and_open_pits_block():
    w = _flat()
    for t, ok in (("R", False), ("O", False), ("c", True), ("u", True), ("g", True)):
        w.set_tile(2, 2, t)
        assert w.walkable(2, 2) is ok
    obj = w.add_object("boulder", 4, 4)
    for t in "wWu":
        w.set_tile(5, 5, t)
        assert not w.move_object(obj, 5, 5)
    w.set_tile(5, 5, "c")
    assert w.move_object(obj, 5, 5)
    assert model.TILE_NAMES["R"] == "rock wall" and model.TILE_NAMES["O"] == "the edge of an open pit"


def test_spawn_point_is_on_the_surface(two_levels):
    w = two_levels(24)
    for _ in range(200):
        x, y = w.spawn_point()
        assert w.region_at(x, y).name == "surface"


def test_set_tile_changes_reach_the_tick_message():
    st = ServerState(seed=7)
    w = st.world
    w.set_tile(3, 3, "d")
    w.set_tile(4, 3, "s")
    msg = json.loads(st.tick_message([]))
    assert sorted(msg["tiles"]) == [[3, 3, "d"], [4, 3, "s"]]
    assert json.loads(st.tick_message([]))["tiles"] is None


def test_init_lists_regions(two_levels):
    w = two_levels(24)
    init = w.to_init()
    assert init["regions"] == [r.to_dict() for r in w.regions] and init["height"] == 80
    assert init["regions"][1] == {"name": "deep", "level": -1, "y0": 56, "y1": 80, "sky": False, "weather": False}


def test_cre_dict_says_what_light_is_carried(monkeypatch):
    w = _flat()
    c = model.Creature("c1", "Ann", 1, 1)
    monkeypatch.setitem(model.LIGHT_ITEMS, "probe_lamp", 3)
    monkeypatch.setitem(model.LIGHT_ITEMS, "probe_glow", 2)
    assert "light" not in w.cre_dict(c)
    c.inventory["probe_glow"] = 1
    assert w.cre_dict(c)["light"] == 2
    c.inventory["probe_lamp"] = 1
    assert w.cre_dict(c)["light"] == 3


def test_regions_seed_and_skylight_survive_a_save(tmp_path):
    st = ServerState(seed=7)
    w = st.world
    w.seed = 7
    w.add_region("sky", 1, [["g"] * w.width for _ in range(4)], sky=True, weather=True)
    w.skylight.add((5, 6))
    path = tmp_path / "world.json"
    save(st, path)
    st2 = ServerState(seed=99)
    restore(st2, path)
    w2 = st2.world
    assert w2.regions == w.regions and w2.seed == 7 and w2.skylight == {(5, 6)} and w2.height == w.height


def test_a_save_from_before_regions_restores_one_surface(tmp_path):
    st = ServerState(seed=7)
    data = snapshot(st)
    for key in ("seed", "regions", "skylight"):
        del data["world"][key]
    path = tmp_path / "old.json"
    path.write_text(json.dumps(data))
    st2 = ServerState(seed=99)
    restore(st2, path)
    w = st2.world
    assert w.regions == [Region("surface", 0, 0, data["world"]["height"], True, True)] and w.seed is None
    assert w.skylight == set()
