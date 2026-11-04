"""The frontier lays a strip of new land east or west across every region, within the pace and the cap."""

import json
import logging
import re
import sys
import time
from collections import Counter

import pytest

import swarmworld.server.__main__ as server_main
from swarmworld.server.__main__ import make_parser
from swarmworld.server.app import STATE, create_app
from swarmworld.server.persistence import restore, save, snapshot
from swarmworld.server.public import Publisher
from swarmworld.server.state import ServerState
from swarmworld.world import lands, registry
from swarmworld.world.actions import start_walk
from swarmworld.world.lands import THEMES
from swarmworld.world.model import Creature, FrontierSettings
from swarmworld.world.packs import food, frontier, nature, underground
from swarmworld.world.packs.frontier import frontier_seed, grow, land_at, land_rect, why_not_grow
from swarmworld.world.simulation import Simulation
from swarmworld.world.terrain import generate_world


def world48(**kw):
    w = generate_world(7, 48, 48)
    w.frontier_settings = FrontierSettings(**{"on": True, "pace": 0, **kw})
    return w


def _expected(w, side):
    """The lands a strip to this side would hold, made from the edges as they are now (before the strip is laid)."""
    s, seed, need = w.region("surface"), frontier_seed(w), lands.need(w)
    lx = (w.ext.get("frontier", {}).get("strips", {}).get(side, 0) + 1) * (1 if side == "east" else -1)
    seam = w.width - 1 if side == "east" else 0
    out, above = [], None
    for ly, y0 in enumerate(range(s.y0, s.y1, 32)):
        y1 = min(y0 + 32, s.y1)
        edges = {"west" if side == "east" else "east": lands.column_edge(w, seam, y0, y1)}
        if above:
            edges["north"] = lands.row_edge(above, len(above.tiles) - 1)
        above = lands.generate_land(seed, lx, ly, (32, y1 - y0), edges, need)
        out.append(above)
    return out


def _free_tile(w, near=None):
    cx, cy = near or w.center
    return next((x, y) for r in range(1, 20) for y in range(cy - r, cy + r + 1) for x in range(cx - r, cx + r + 1)
                if w.walkable(x, y) and w.tile(x, y) not in "wW" and (x, y) not in w.grid and not w.occupied(x, y))


def _plain(st) -> dict:
    return json.loads(json.dumps(snapshot(st)))


def test_growth_is_off_by_default():
    w = generate_world(7, 48, 48)
    assert why_not_grow(w, "east") == "off" and grow(w, "east") == [] and w.width == 48 and "frontier" not in w.ext
    assert FrontierSettings() == FrontierSettings(on=False, strip=32, pace=1200, cap=384) and w.growths == []


def test_an_east_strip_widens_every_region():
    w = world48()
    old, regions = [row[:] for row in w.tiles], list(w.regions)
    assert grow(w, "east") == ["1,0", "1,1"] and w.width == 80 and all(len(r) == 80 for r in w.tiles)
    assert all(w.tiles[y][:48] == old[y] for y in range(w.height))          # nothing old moved
    assert all(w.tiles[y][48:] == ["R"] * 32 for y in range(48, 80))        # the rock band
    assert any(t != "R" for y in range(48) for t in w.tiles[y][48:])        # new land on the surface
    n = w.ext["nature"]
    assert len(n["biomes"]) == 48 and all(len(r) == 80 for r in n["biomes"] + n["flow"])
    assert (w.origin_x, w.center, w.regions) == (0, (24, 24), regions)
    assert all(w.tiles[y][48:50] == w.tiles[y][78:] == ["R"] * 2 for y in range(w.region("deep").y0, w.height))


def test_a_west_strip_shifts_the_old_world_by_32():
    w = world48()
    x, y = _free_tile(w)
    w.creatures["c1"] = ada = Creature("c1", "Ada", x, y)
    old = [row[:] for row in w.tiles]
    old_nature = {k: list(w.ext["nature"][k]) for k in ("biomes", "flow")}
    objects = {o.id: (o.kind, o.x, o.y, w.tiles[o.y][o.x]) for o in w.objects.values()}
    ends = [(p["up"], p["down"]) for p in underground.portals(w)]
    assert ends
    under_ada = w.tile(x, y)
    assert grow(w, "west") == ["-1,0", "-1,1"]
    assert w.width == 80 and all(w.tiles[y][32:] == old[y] for y in range(w.height))
    assert all(w.ext["nature"][k][y][32:] == old_nature[k][y] for k in old_nature for y in range(48))
    for oid, (kind, ox, oy, code) in objects.items():
        o = w.objects[oid]
        assert (o.kind, o.x, o.y, w.tiles[o.y][o.x]) == (kind, ox + 32, oy, code)
    assert (ada.x, ada.y) == (x + 32, y) and w.tile(ada.x, ada.y) == under_ada
    assert [(p["up"], p["down"]) for p in underground.portals(w)] == [([u[0] + 32, u[1]], [d[0] + 32, d[1]])
                                                                      for u, d in ends]
    assert (w.origin_x, w.home_width, w.center) == (32, 48, (56, 24))
    assert all(w.tiles[y][:32] == ["R"] * 32 for y in range(48, 80))


def test_a_strip_waits_a_day_and_stops_at_the_cap():
    w = world48(pace=1200, cap=144)
    assert grow(w, "east") and why_not_grow(w, "west") == "pace" and grow(w, "west") == []
    w.tick += 1199
    assert why_not_grow(w, "east") == "pace"
    w.tick += 1
    assert grow(w, "west") and w.width == 112
    w.tick += 1200
    assert grow(w, "east") and w.width == 144 and why_not_grow(w, "east") == why_not_grow(w, "west") == "cap"
    assert grow(w, "east", ignore_pace=True) == [] and w.width == 144


def test_the_steward_may_lay_a_strip_before_the_day_is_out():
    w = world48(pace=1200)
    assert grow(w, "east") and grow(w, "east") == [] and grow(w, "east", ignore_pace=True) == ["2,0", "2,1"]
    assert w.ext["frontier"]["last_grow"] == w.tick


def test_the_strip_width_is_fixed_by_the_first_growth():
    w = world48(strip=16)
    assert grow(w, "east") == ["1,0", "1,1", "1,2"] and w.width == 64
    w.frontier_settings = FrontierSettings(on=True, pace=0)  # a restart with other settings
    assert grow(w, "east") == ["2,0", "2,1", "2,2"] and w.width == 80 and w.ext["frontier"]["strip"] == 16
    assert land_rect(w, "2,2") == (64, 32, 80, 48)


def test_new_lands_are_recorded_and_populated():
    w = world48()
    expected = _expected(w, "east")
    keys = grow(w, "east")
    rec = w.ext["frontier"]
    assert rec["seed"] == 7 and rec["strip"] == 32 and rec["strips"] == {"east": 1, "west": 0}
    assert list(rec["lands"]) == keys == ["1,0", "1,1"] and rec["last_grow"] == w.tick
    habitat = set(nature.PLANTS) | set(food.habitat_kinds())
    for key, land in zip(keys, expected):
        r = rec["lands"][key]
        assert r == {"theme": land.theme, "side": "east", "heart": list(land.heart), "name": None, "found_by": None,
                     "tick": None}
        assert r["theme"] in THEMES
        x0, y0, x1, y1 = land_rect(w, key)
        assert ["".join(w.tiles[y][x0:x1]) for y in range(y0, y1)] == land.tiles
        assert [w.ext["nature"]["biomes"][y][x0:x1] for y in range(y0, y1)] == land.biomes
        assert [w.ext["nature"]["flow"][y][x0:x1] for y in range(y0, y1)] == land.flow
        made = {(x0 + x, y0 + y): kind for kind, x, y, _ in land.objects}
        assert all(w.object_at(*p).kind == kind for p, kind in made.items())
        held = Counter(o.kind for o in w.objects.values() if x0 <= o.x < x1 and y0 <= o.y < y1)
        assert all(held[kind] for kind in THEMES[land.theme]["min"]), (land.theme, held)
        filled = {o.kind for o in w.objects.values() if x0 <= o.x < x1 and y0 <= o.y < y1 and (o.x, o.y) not in made}
        assert filled & habitat, (key, land.theme, filled)
        assert land_at(w, x0, y0) == land_at(w, x1 - 1, y1 - 1) == key
    assert land_rect(w, "1,1") == (48, 32, 80, 48)  # a 48-row surface: lands of 32 and 16 rows
    assert land_at(w, 47, 10) is None and land_at(w, 50, w.region("deep").y0 + 3) is None


def test_land_places_count_from_the_home_lands():
    w = world48()
    grow(w, "east")
    grow(w, "west")
    grow(w, "west")
    assert (w.width, w.origin_x) == (144, 64)
    assert land_rect(w, "1,0") == (112, 0, 144, 32)
    assert land_rect(w, "-1,0") == (32, 0, 64, 32) and land_rect(w, "-2,1") == (0, 32, 32, 48)
    assert land_at(w, 0, 47) == "-2,1" and land_at(w, 63, 0) == "-1,0" and land_at(w, 64, 0) is None
    assert list(w.ext["frontier"]["lands"]) == ["1,0", "1,1", "-1,0", "-1,1", "-2,0", "-2,1"]


def test_the_seed_is_the_worlds_or_read_from_its_land():
    w, other = world48(), world48()
    assert frontier_seed(w) == 7
    w.seed = other.seed = None
    seed = frontier_seed(w)
    assert isinstance(seed, int) and seed == frontier_seed(other)  # the same land, the same seed
    other.tiles[5][5] = "W" if other.tiles[5][5] != "W" else "g"
    assert frontier_seed(other) != seed
    grow(w, "east")
    assert w.ext["frontier"]["seed"] == seed
    w.tiles[5][5] = other.tiles[5][5]
    assert frontier_seed(w) == seed  # kept in the record from then on


def test_a_land_is_shaped_and_stocked_before_the_packs_fill_it(caplog):
    w = world48()
    expected = _expected(w, "east")
    seen = []

    def probe(world, rng, bounds):
        x0, y0, x1, y1 = bounds
        seen.append((bounds, {(o.x, o.y): o.kind for o in world.objects.values() if x0 <= o.x < x1 and y0 <= o.y < y1},
                     all(len(r) == world.width for r in world.ext["nature"]["biomes"] + world.ext["nature"]["flow"])))
    with registry.sandbox():
        registry.register_populate("probe", lambda world, rng, fresh: None, land=probe)
        registry.POPULATE.insert(0, registry.POPULATE.pop())  # ahead of food's and nature's land hooks
        with caplog.at_level(logging.ERROR, logger="swarmworld.packs"):
            keys = grow(w, "east")
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]  # the growth worked, it wasn't taken back
    assert [b for b, _, _ in seen] == [land_rect(w, k) for k in keys]
    for (bounds, placed, widened), land in zip(seen, expected):
        x0, y0 = bounds[:2]
        assert widened and placed == {(x0 + x, y0 + y): kind for kind, x, y, _ in land.objects}
        assert all(w.object_at(*p).kind == kind for p, kind in placed.items())  # the land hooks kept off them


def test_nature_sees_the_new_land_after_a_west_strip():
    w = world48()
    before = {k: set(v) for k, v in nature._ambient(w)["tiles"].items()}
    grow(w, "west")
    after = nature._ambient(w)["tiles"]
    for k in ("forest", "beach", "meadow"):
        assert {(x - 32, y) for x, y in after[k] if x >= 32} == before[k], k
    assert {(x + 32, y) for x, y in before["firefly"]} <= set(after["firefly"])
    assert any(x < 32 for k in ("forest", "beach", "meadow") for x, _ in after[k])


def test_renewal_draws_from_the_new_land():
    w = world48()
    nature._ambient(w)  # the habitats a running world has worked out already
    grow(w, "east", theme="deep_pines")
    assert any(x >= 48 for x, _ in nature._ambient(w)["tiles"]["forest"])
    sim = Simulation(w)
    have = sum(o.kind == "mushroom_patch" for o in w.objects.values())
    w.ext["nature"]["targets"]["mushroom_patch"] = have + 40
    before = set(w.objects)
    for _ in range(5):
        nature.renew_step(sim, 0)
    new = [w.objects[i] for i in set(w.objects) - before if w.objects[i].kind == "mushroom_patch"]
    assert any(o.x >= 48 for o in new)


def test_growth_rolls_none_of_the_worlds_dice():
    w = world48()
    state = w.rng.getstate()
    assert grow(w, "east") and grow(w, "west")
    assert w.rng.getstate() == state


def test_the_same_world_grows_the_same_land():
    a, b = world48(), world48()
    key = lambda w: (w.tiles, sorted((o.kind, o.x, o.y) for o in w.objects.values()), w.ext["frontier"])  # noqa: E731
    for w in (a, b):
        grow(w, "west")
        grow(w, "east")
    assert key(a) == key(b)


def test_growth_is_announced_once_for_the_viewers():
    w = world48()
    w.set_tile(3, 3, "d")  # a change from before the strip, still waiting for the viewers
    n = len(w.events)
    grow(w, "east")
    ev = [e for e in w.events[n:] if e.kind == "frontier"]
    assert [(e.actor, e.x, e.y, e.text) for e in ev] == [(None, 47, 24, "New country lies to the east.")]
    assert w.growths == [{"side": "east", "columns": 32, "width": 80, "origin_x": 0}]
    assert w.changed_tiles == {(3, 3): "d"}
    x, y = _free_tile(w)
    ada = w.creatures["c1"] = Creature("c1", "Ada", x, y)
    grow(w, "west", by=ada)
    ev = [e for e in w.events[n:] if e.kind == "frontier"]
    assert (ev[-1].actor, ev[-1].x, ev[-1].y, ev[-1].text) == ("c1", 32, 24,
                                                                "Ada's exploring lays down new country to the west.")
    assert w.growths[-1] == {"side": "west", "columns": 32, "width": 112, "origin_x": 32}
    assert w.changed_tiles == {(35, 3): "d"}

    st = ServerState(seed=7, frontier=FrontierSettings(on=True, pace=0))
    grow(st.world, "east")
    assert st.take_growth() == [{"side": "east", "columns": 32, "width": 160, "origin_x": 0}]
    assert st.world.growths == [] and st.take_growth() == []


def test_a_failing_shift_hook_leaves_the_world_as_it_was(caplog):
    st = ServerState(seed=7, frontier=FrontierSettings(on=True, pace=0))
    w = st.world
    x, y = _free_tile(w)
    ada = w.creatures["c1"] = Creature("c1", "Ada", x, y)
    start_walk(w, ada, {(x + 3, y)}, "east", "You arrive.")
    path = list(ada.activity["path"])
    w.set_tile(x, y + 3, "d")
    before, events, changed = _plain(st), len(w.events), dict(w.changed_tiles)
    with registry.sandbox():
        def boom(world, n):
            raise RuntimeError("shift boom")
        registry.register_shift_hook("boom", boom)  # the last hook: the others have moved their state by then
        with caplog.at_level(logging.ERROR, logger="swarmworld.packs"):
            assert grow(w, "west") == []
    assert w.ext.pop("frontier") == {"origin_x": 0, "home_width": w.width, "failed": w.tick}  # only the mark
    assert _plain(st) == before
    assert len(w.events) == events and not any(e.kind == "frontier" for e in w.events) and w.growths == []
    assert w.creatures["c1"] is ada and ada.activity["path"] == path and w.changed_tiles == changed
    assert w.origin_x == 0
    lines = [r for r in caplog.records if "shift boom" in r.getMessage()]
    assert len(lines) == 1 and "\n" not in lines[0].getMessage() and lines[0].exc_info is None
    assert re.search(r"at \w+\.py:\d+ in boom\)$", lines[0].getMessage())  # names the raising frame
    assert grow(w, "west") and (ada.x, w.origin_x) == (x + 32, 32)  # with the hook gone, the strip goes in
    # (pace=0: a failure holds nothing back)


def test_an_east_strip_that_fails_half_way_is_taken_back(monkeypatch):
    st = ServerState(seed=7, frontier=FrontierSettings(on=True, pace=0))
    before = _plain(st)

    def boom(*a):
        raise RuntimeError("populate boom")
    monkeypatch.setattr(frontier, "run_populate_land", boom)
    assert grow(st.world, "east") == []
    assert st.world.ext.pop("frontier")["failed"] == st.world.tick  # only the mark of the failure stays
    assert _plain(st) == before and st.world.width == 128 and st.world.growths == []


def test_a_grown_world_survives_save_and_load(tmp_path):
    on = FrontierSettings(on=True, pace=0)
    st = ServerState(seed=7, frontier=on)
    w = st.world
    x, y = _free_tile(w)
    w.creatures["c1"] = Creature("c1", "Ada", x, y)
    assert grow(w, "west") and grow(w, "east")
    save(st, tmp_path / "w.json")
    st2 = ServerState(seed=3, frontier=on)
    restore(st2, tmp_path / "w.json")
    w2 = st2.world
    assert (w2.width, w2.origin_x, w2.center) == (192, 32, (96, 64))
    assert w2.ext["frontier"] == json.loads(json.dumps(w.ext["frontier"]))
    assert all(w2.ext["nature"][k] == w.ext["nature"][k] for k in ("biomes", "flow"))
    assert w2.tiles == w.tiles
    assert {o.id: (o.kind, o.x, o.y) for o in w2.objects.values()} == {o.id: (o.kind, o.x, o.y) for o in w.objects.values()}
    assert {c.id: (c.x, c.y) for c in w2.creatures.values()} == {"c1": (x + 32, y)}
    assert w2.frontier_settings is st2.frontier
    assert grow(w2, "east") == ["2,0", "2,1", "2,2", "2,3"] and w2.width == 224


def test_a_grown_world_loads_with_the_frontier_off(tmp_path):
    st = ServerState(seed=7, frontier=FrontierSettings(on=True, pace=0))
    assert grow(st.world, "west") and grow(st.world, "east")
    st.sim._landmarks()
    save(st, tmp_path / "a.json")
    st2 = ServerState(seed=3)
    restore(st2, tmp_path / "a.json")
    w2 = st2.world
    st2.sim._landmarks()
    meadow = [lm for lm in st.world.landmarks if lm["name"] == "the meadow"]
    assert meadow and [lm for lm in w2.landmarks if lm["name"] == "the meadow"] == meadow
    assert w2.ext["frontier"]["lands"] == json.loads(json.dumps(st.world.ext["frontier"]["lands"]))
    assert (w2.origin_x, w2.home_width, w2.center) == (32, 128, (96, 64))
    assert why_not_grow(w2, "east") == why_not_grow(w2, "west") == "off" and grow(w2, "east") == []
    save(st2, tmp_path / "b.json")
    assert json.loads((tmp_path / "b.json").read_text())["world"] == json.loads((tmp_path / "a.json").read_text())["world"]


def test_a_world_that_never_grew_saves_as_before(prepack_save, tmp_path):
    worlds = []
    for i, settings in enumerate((None, FrontierSettings(on=True))):
        st = ServerState(seed=1, frontier=settings)
        restore(st, prepack_save)
        assert why_not_grow(st.world, "east") == (None if settings else "off")
        save(st, tmp_path / f"{i}.json")
        worlds.append(json.loads((tmp_path / f"{i}.json").read_text())["world"])
    assert "frontier" not in worlds[0]["ext"] and worlds[0] == worlds[1]


def test_the_steward_can_lay_a_strip():
    st = ServerState(seed=7, frontier=FrontierSettings(on=True, cap=192))  # the day's pace: the steward isn't held
    out = st.admin("grow", {"side": "east"})
    assert out["ok"] and out["lands"] == ["1,0", "1,1", "1,2", "1,3"] and st.world.width == 160
    assert st.admin("grow", {"side": "east"})["width"] == 192
    ev = [e for e in st.world.events if e.kind == "steward"]
    assert ev[-1].text == "Steward laid a strip of new land to the east." and (ev[-1].x, ev[-1].y) == (64, 64)
    with pytest.raises(ValueError, match=re.escape("the map is as wide as it may grow (192)")):
        st.admin("grow", {"side": "west"})
    with pytest.raises(ValueError, match="east.*west"):
        st.admin("grow", {"side": "north"})
    with pytest.raises(ValueError, match=re.escape("the frontier is off (start the world with --frontier on)")):
        ServerState(seed=7).admin("grow", {"side": "east"})


async def test_the_steward_grows_over_http(aiohttp_client):
    client = await aiohttp_client(create_app(seed=7, tick_seconds=0.02, start_loop=False, public_every=0,
                                             frontier=FrontierSettings(on=True)))
    r = await client.post("/api/admin/grow", json={"side": "west"})
    assert r.status == 200 and (await r.json())["origin_x"] == 32 and client.app[STATE].world.width == 160
    assert (await client.post("/api/admin/grow", json={"side": "up"})).status == 400
    r = await client.post("/api/admin/frobnicate", json={})
    assert r.status == 404 and "grow" in await r.text()


def test_the_frontier_flag(tmp_path, monkeypatch):
    assert make_parser().parse_args([]).frontier == "off" and make_parser().parse_args(["--frontier", "on"]).frontier == "on"
    assert create_app(frontier=FrontierSettings(on=True), start_loop=False)[STATE].world.frontier_settings.on
    assert not create_app(start_loop=False)[STATE].world.frontier_settings.on
    seen = []

    class Stop(Exception):
        pass

    def fake_create_app(**kw):
        seen.append(kw["frontier"])
        raise Stop
    monkeypatch.setattr(server_main, "create_app", fake_create_app)
    base = ["swarmworld.server", "--runs", str(tmp_path / "runs"), "--world", str(tmp_path / "w.json"), "--embed", "none"]
    for extra in ([], ["--frontier", "on"], ["--frontier", "off"]):
        monkeypatch.setattr(sys, "argv", base + extra)
        with pytest.raises(Stop):
            server_main.main()
    assert seen == [FrontierSettings(on=False), FrontierSettings(on=True), FrontierSettings(on=False)]


def test_a_growth_makes_the_publisher_rebuild_its_static():
    st = ServerState(seed=7, frontier=FrontierSettings(on=True, pace=0))
    now = [0.0]
    pub = Publisher(st, clock=lambda: now[0])
    pub.publish()
    grow(st.world, "east")
    now[0] += 3
    pub.publish()
    assert pub.builds["static"] == 2 and json.loads(pub.static_doc().body)["width"] == 160


def test_a_strip_is_laid_quickly():
    w = generate_world(7)
    w.frontier_settings = FrontierSettings(on=True)
    t = time.perf_counter()
    assert grow(w, "east") and w.width == 160
    assert time.perf_counter() - t < 1.0


def test_a_failing_copy_is_logged_and_nothing_grows(monkeypatch, caplog):
    w = world48()
    monkeypatch.setattr(frontier, "_keep", lambda world: (_ for _ in ()).throw(RuntimeError("copy boom")))
    with caplog.at_level(logging.ERROR, logger="swarmworld.packs"):
        assert grow(w, "east") == []
    assert w.width == 48 and len([r for r in caplog.records if "copy boom" in r.getMessage()]) == 1
