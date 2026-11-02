"""Pack building: a build verb that lays out a construction site from a design (tent, hut, storehouse, workshop, well,
bridge), takes materials and turns of work from anyone beside it, and turns into the building: walls, a door and
furniture on the map, a roof the viewer draws, shelter from rain and cold, a hut's bed, a storehouse's shelves and a
bridge you can walk over."""

import json
import random

from swarmworld.mind.techniques import relevant
from swarmworld.server.persistence import restore, save
from swarmworld.server.state import ServerState
from swarmworld.world import registry
from swarmworld.world.actions import Intention, apply_intention, bfs_path, start_walk, station_near, step_activity
from swarmworld.world.catalog import Catalog
from swarmworld.world.model import DAY_TICKS, START_TICK, Creature, World
from swarmworld.world.packs import building
from swarmworld.world.perception import perceive, roof_over
from swarmworld.world.simulation import Simulation

PHASE_AT = {"dawn": 0.05, "day": 0.3, "dusk": 0.6, "night": 0.8}
HUT = {"log": 6, "planks": 4, "thatch": 2, "plant_fiber": 4}


def grass_world(size=40, tiles=None):
    w = World(size, size, tiles or [["g"] * size for _ in range(size)], Catalog.load())
    w.tick = START_TICK + 100  # morning
    w.rng = random.Random(5)
    return w


def river_world(size=30, deep=(12, 13, 14)):
    """Grass with a deep river running north to south through the given columns."""
    return grass_world(size, [["W" if x in deep else "g" for x in range(size)] for _ in range(size)])


def set_phase(w, phase):
    w.tick = (w.tick // DAY_TICKS) * DAY_TICKS + int(DAY_TICKS * PHASE_AT[phase])
    assert w.clock()["phase"] == phase


def creature(w, name="Tam", x=10, y=10):
    c = Creature(f"c{len(w.creatures) + 1}", name, x, y, asleep=False, wake_reason=None, last_think_tick=w.tick)
    c.known_recipes = {r.output for r in w.catalog.recipes if r.known_at_start}
    w.creatures[c.id] = c
    return c


def act(w, c, **kw):
    """Carry out an intention and whatever it set going (a walk, then the work); the last result."""
    res = apply_intention(w, c, Intention(**kw))
    while c.activity:
        res = step_activity(w, c) or res
    return res


def system(name):
    return next(s.fn for s in registry.SYSTEMS if s.name == name)


def only_site(w):
    [(sid, site)] = building.sites(w).items()
    return sid, site


def finish(w, c, design, materials=None):
    """c lays out a design beside it with everything it needs in hand, then works until it stands. The building."""
    c.inventory.update(materials or building.DESIGNS[design]["needs"])
    res = act(w, c, action="build", target=design)
    assert res.ok, res.message
    for _ in range(20):
        if not building.sites(w):
            break
        res = act(w, c, action="build")
        assert res.ok, res.message
    assert not building.sites(w)
    return next(b for b in building.buildings(w).values() if b["design"] == design)


def inside_tiles(w, b):
    return [(x, y) for y in range(b["y0"] + 1, b["y1"]) for x in range(b["x0"] + 1, b["x1"])
            if w.walkable(x, y) and not w.object_at(x, y)]


def kinds_in(w, b):
    return sorted(w.object_at(x, y).kind for y in range(b["y0"], b["y1"] + 1) for x in range(b["x0"], b["x1"] + 1)
                  if w.object_at(x, y))


# ------------------------------------------------------------------ sites, help and the finished building
def test_start_a_site_and_finish_it_with_help():
    w = grass_world()
    mira, tam = creature(w, "Mira", 10, 10), creature(w, "Tam", 15, 10)
    mira.inventory.update({"log": 6, "planks": 2})
    res = act(w, mira, action="build", target="hut")
    assert res.ok and "hut" in res.message
    sid, site = only_site(w)
    assert site["have"] == {"log": 6, "planks": 2} and not mira.inventory.get("log")
    assert "2 planks" in res.message and "2 thatch" in res.message and "4 plant fiber" in res.message
    assert building.rect_dist(site, mira.x, mira.y) == 1  # laid out right beside her
    assert "hut site" in perceive(w, tam)  # anyone in sight sees it, and what it still needs
    assert "2 thatch" in w.objects[sid].name

    tam.inventory.update({"planks": 2, "thatch": 2, "plant_fiber": 5})
    res = act(w, tam, action="build", target="hut")  # he walks over and helps rather than starting another
    assert res.ok and len(building.sites(w)) == 1 and building.rect_dist(site, tam.x, tam.y) <= 1
    assert site["have"] == HUT and site["done"] == 1 and tam.inventory["plant_fiber"] == 1
    assert "3 more turns" in res.message

    assert act(w, mira, action="build").ok  # "build" beside a site works on it
    assert act(w, tam, action="build", target="site").ok
    res = act(w, mira, action="build", target="hut")
    assert res.ok and "finish" in res.message.lower()
    assert not building.sites(w) and sid not in w.objects
    [b] = building.buildings(w).values()
    assert b["design"] == "hut" and b["by"] == ["Mira", "Tam"] and b["roof"]
    assert (b["x1"] - b["x0"], b["y1"] - b["y0"]) == (3, 3)
    assert kinds_in(w, b) == ["bed", "door"] + ["log_wall"] * 11
    door = w.object_at(*b["door"])
    assert door.kind == "door" and door.name == "hut door" and b["door"][1] == b["y1"]
    assert mira.stats["built"] == 1 and tam.stats["built"] == 1
    [view] = w.to_init()["buildings"]
    assert view == {"id": view["id"], "design": "hut", "x0": b["x0"], "y0": b["y0"], "x1": b["x1"], "y1": b["y1"],
                    "door": b["door"], "roof": True}
    path = bfs_path(w, (mira.x, mira.y), set(inside_tiles(w, b)))
    assert path and tuple(b["door"]) in path  # in through the door, not through a wall


def test_site_still_needs_what_you_lack():
    w = grass_world()
    mira = creature(w, "Mira", 10, 10)
    mira.inventory["log"] = 2
    act(w, mira, action="build", target="house")  # an alias
    _, site = only_site(w)
    assert site["design"] == "hut"
    res = act(w, mira, action="build")
    assert not res.ok and "4 log" in res.message and "you carry none" in res.message.lower()
    mira.inventory["planks"] = 1
    res = act(w, mira, action="build")
    assert res.ok and site["have"]["planks"] == 1 and site["done"] == 0  # no work until it has everything


def test_one_open_site_at_a_time():
    w = grass_world()
    mira = creature(w, "Mira", 10, 10)
    act(w, mira, action="build", target="tent")
    mira.x, mira.y = 25, 25
    res = act(w, mira, action="build", target="hut")
    assert not res.ok and "tent site" in res.message and len(building.sites(w)) == 1


def test_no_room_no_site():
    w = grass_world()
    mira = creature(w, "Mira", 10, 10)
    for x in range(4, 17):
        for y in range(4, 17):
            if (x + y) % 3 == 0 and (x, y) != (10, 10):
                w.add_object("rock", x, y)
    res = act(w, mira, action="build", target="hut")
    assert not res.ok and "room" in res.message.lower() and not building.sites(w)


def test_build_without_a_design_is_still_craft():
    """The word build meant craft before this pack: what isn't a design still goes there, unchanged."""
    w = grass_world()
    mira = creature(w, "Mira", 10, 10)
    mira.inventory.update({"stick": 3, "stone": 2})
    res = act(w, mira, action="build", target="campfire")
    assert res.ok and mira.inventory["campfire"] == 1 and not building.sites(w)
    mira.inventory["planks"] = 2
    res = act(w, mira, action="build", target="wooden wall")
    assert not res.ok and "know how to make wooden wall" in res.message  # what craft says
    res = act(w, mira, action="build", target="campfire at home")  # "home" is a hut, but this is about a campfire
    assert not res.ok and res.message.startswith("You've never heard") and not building.sites(w)


def test_build_with_nothing_named_lists_the_designs():
    w = grass_world()
    mira = creature(w, "Mira", 10, 10)
    res = act(w, mira, action="build")
    assert not res.ok
    for design in ("tent", "hut", "storehouse", "workshop", "well", "bridge"):
        assert design in res.message
    assert "6 stick" in res.message


def test_insects_flit_off_a_site():
    w = grass_world()
    mira = creature(w, "Mira", 10, 10)
    for x in range(5, 16):
        for y in range(5, 16):
            if (x, y) != (10, 10):
                w.add_object("butterfly", x, y)
    assert act(w, mira, action="build", target="tent").ok
    sid, site = only_site(w)
    assert not any(o.kind == "butterfly" for o in w.objects.values() if building.rect_dist(site, o.x, o.y) == 0)
    x, y = next((x, y) for x in range(site["x0"], site["x1"] + 1) for y in range(site["y0"], site["y1"] + 1)
                if not w.object_at(x, y))
    w.add_object("honeybee", x, y)  # one wanders back in while it's being built: it flits off again
    finish(w, mira, "tent")
    assert not any(o.kind == "honeybee" for o in w.objects.values())
    b = next(iter(building.buildings(w).values()))
    w.add_object("firefly", b["x0"] + 1, b["y0"] + 1)  # and none settle inside
    system("building upkeep")(Simulation(w), w.tick)
    assert not any(o.kind == "firefly" for o in w.objects.values())


def test_a_creature_standing_in_the_way_steps_aside():
    w = grass_world()
    mira, tam = creature(w, "Mira", 10, 10), creature(w, "Tam", 30, 30)
    mira.inventory.update(building.DESIGNS["tent"]["needs"])
    act(w, mira, action="build", target="tent")
    _, site = only_site(w)
    tam.x, tam.y = site["x0"], site["y0"]  # where a wall will go
    sheep = w.add_object("sheep", site["x0"] + 1, site["y0"] + 1, state="graze")  # it would be shut in
    finish(w, mira, "tent")
    assert w.object_at(site["x0"], site["y0"]).kind == "tent_wall"
    assert (tam.x, tam.y) != (site["x0"], site["y0"]) and w.walkable(tam.x, tam.y)
    assert sheep.id in w.objects and building.rect_dist(site, sheep.x, sheep.y) > 0


# ------------------------------------------------------------------ inside
def test_inside_a_hut_is_sheltered_and_described():
    w = grass_world()
    mira, tam = creature(w, "Mira", 10, 10), creature(w, "Tam", 30, 30)
    b = finish(w, mira, "hut", HUT)
    mira.x, mira.y = inside_tiles(w, b)[0]
    assert roof_over(w, mira.x, mira.y) and not roof_over(w, *b["door"]) and not roof_over(w, tam.x, tam.y)
    set_phase(w, "night")
    w.weather = "rain"
    sim = Simulation(w)
    assert sim.exposure(mira) is None and sim.exposure(tam) == "rain"
    seen = perceive(w, mira)
    line = next(ln for ln in seen.splitlines() if ln.startswith("You're inside"))
    assert "hut" in line and "Mira" in line and "bed" in line and "dry" in line
    assert "soaked" not in seen and "soaked" in perceive(w, tam)
    assert "You're inside" in perceive(w, mira)  # it matters every turn while it rains

    w.weather = "clear"
    set_phase(w, "day")
    w.tick += DAY_TICKS
    assert "You're inside" in perceive(w, mira)  # a dry day: said once on coming in ...
    assert "You're inside" not in perceive(w, mira)  # ... not every turn
    mira.x, mira.y = b["door"]
    perceive(w, mira)
    mira.x, mira.y = inside_tiles(w, b)[0]
    assert "You're inside" in perceive(w, mira)  # and again on coming back in

    set_phase(w, "night")  # the hut's bed counts for sleep
    mira.energy, tam.energy = 40, 40
    before = (mira.energy, tam.energy)
    for _ in range(3):
        sim.tick()
    assert mira.sleeping and mira.activity["bed"] and mira.activity["label"] == "sleeping"
    assert tam.sleeping and tam.activity["label"] == "sleeping out in the cold"
    assert mira.energy - before[0] > tam.energy - before[1]


def test_a_tent_keeps_off_the_rain():
    w = grass_world()
    mira = creature(w, "Mira", 10, 10)
    b = finish(w, mira, "tent")
    mira.x, mira.y = b["x0"] + 1, b["y0"] + 1
    w.weather = "rain"
    sim = Simulation(w)
    assert sim.exposure(mira) is None and "soaked" not in perceive(w, mira)
    assert "tent" in next(ln for ln in perceive(w, mira).splitlines() if ln.startswith("You're inside"))
    mira.x, mira.y = b["door"]
    assert sim.exposure(mira) == "rain" and "soaked" in perceive(w, mira)


def test_a_tired_creature_goes_to_bed_inside_not_against_the_wall():
    w = grass_world()
    mira = creature(w, "Mira", 10, 10)
    b = finish(w, mira, "hut", HUT)
    mira.x, mira.y = 35, 35
    tam = creature(w, "Tam", b["x0"] - 1, b["y0"] + 1)  # outside, the bed just the other side of the wall
    set_phase(w, "night")
    tam.energy = 40
    assert not station_near(w, tam, "bed")  # a bed inside a building is for those inside it
    sim = Simulation(w)
    for _ in range(40):
        sim.tick()
        if tam.sleeping:
            break
    assert tam.sleeping and roof_over(w, tam.x, tam.y)


def test_storehouse_stores():
    w = grass_world()
    mira = creature(w, "Mira", 10, 10)
    b = finish(w, mira, "storehouse")
    [shelves] = [o for o in w.objects.values() if o.kind == "shelves"]
    assert building.rect_dist(b, shelves.x, shelves.y) == 0 and roof_over(w, shelves.x, shelves.y)
    mira.inventory.update({"stick": 5, "meat": 2})
    res = act(w, mira, action="store", target="storehouse", items=["stick", "meat"])  # walks in through the door
    assert res.ok and shelves.data["items"] == {"stick": 5, "meat": 2} and not mira.inventory.get("stick")
    assert roof_over(w, mira.x, mira.y)
    line = next(ln for ln in perceive(w, mira).splitlines() if ln.startswith("You're inside"))
    assert "storehouse" in line and "5 stick" in line
    tam = creature(w, "Tam", 30, 30)
    tam.x, tam.y = mira.x, mira.y
    mira.x, mira.y = 30, 30
    res = act(w, tam, action="take", target="storehouse", items=["stick"], count=5)
    assert res.ok and tam.inventory["stick"] == 5 and shelves.data["items"] == {"meat": 2}


def test_workshop_has_a_workbench_and_a_well_is_the_food_well():
    w = grass_world()
    mira = creature(w, "Mira", 10, 10)
    b = finish(w, mira, "workshop")
    assert "workbench" in kinds_in(w, b) and kinds_in(w, b).count("wall") == 13
    mira.x, mira.y = 30, 30
    well = finish(w, mira, "well")
    assert not well["roof"] and well["door"] is None
    assert w.object_at(well["x0"], well["y0"]).kind == "well"
    mira.inventory["clay_pot"] = 1
    assert act(w, mira, action="fill").ok and mira.inventory["water_pot"] == 1


def test_a_carried_well_is_placed():
    w = grass_world()
    mira = creature(w, "Mira", 10, 10)
    mira.inventory["well"] = 1
    res = act(w, mira, action="build", target="well")
    assert res.ok and any(o.kind == "well" for o in w.objects.values()) and not building.sites(w)


# ------------------------------------------------------------------ bridges
def test_bridge_makes_water_walkable():
    w = river_world()
    tam = creature(w, "Tam", 11, 10)
    assert not w.walkable(12, 10) and bfs_path(w, (11, 10), {(16, 10)}) is None
    tam.inventory.update({"planks": 6, "log": 3})
    res = act(w, tam, action="build", target="bridge")
    assert res.ok and "3 steps" in res.message
    _, site = only_site(w)
    assert (site["x0"], site["x1"], site["y0"], site["y1"]) == (12, 14, 10, 10) and site["work"] == 3
    for _ in range(5):
        if building.sites(w):
            assert act(w, tam, action="build").ok
    assert not building.sites(w)
    assert all(w.walkable(x, 10) and w.object_at(x, 10).kind == "bridge" for x in (12, 13, 14))
    [b] = building.buildings(w).values()
    assert b["design"] == "bridge" and not b["roof"] and b["door"] is None
    start_walk(w, tam, {(16, 10)}, "crossing", "You cross.")
    while (tam.x, tam.y) != (13, 10):
        step_activity(w, tam)
    assert "You stand on a wooden bridge over deep water" in perceive(w, tam)
    while tam.activity:
        step_activity(w, tam)
    assert (tam.x, tam.y) == (16, 10)


def test_no_bridge_where_you_can_wade_or_cannot_reach():
    w = grass_world(30, [["w" if x in (12, 13) else "g" for x in range(30)] for _ in range(30)])
    tam = creature(w, "Tam", 11, 10)
    res = act(w, tam, action="build", target="bridge")
    assert not res.ok and "wade" in res.message
    tam.x = 5
    res = act(w, tam, action="build", target="bridge")
    assert not res.ok and "water's edge" in res.message
    w = river_world(30, deep=tuple(range(12, 25)))
    tam = creature(w, "Tam", 11, 10)
    res = act(w, tam, action="build", target="bridge")
    assert not res.ok and "8 steps" in res.message


# ------------------------------------------------------------------ what a creature is told
def test_site_line_when_you_come_to_it_and_when_it_changes():
    w = grass_world()
    mira, tam = creature(w, "Mira", 10, 10), creature(w, "Tam", 30, 30)
    act(w, mira, action="build", target="tent")
    first = perceive(w, mira)
    assert "The tent site beside you still needs 6 stick, 4 plant fiber and 2 rope" in first
    assert "tent site beside you" not in perceive(w, mira)  # said, not repeated
    mira.inventory["stick"] = 6
    act(w, mira, action="build")
    assert "still needs 4 plant fiber and 2 rope" in perceive(w, mira)
    assert "tent site beside you" not in perceive(w, tam)


def test_build_is_disclosed_by_a_site_or_materials():
    w = grass_world()
    mira, tam = creature(w, "Mira", 10, 10), creature(w, "Tam", 12, 12)
    assert not any(line.startswith("build") for line in relevant(w, tam))
    tam.inventory["log"] = 2
    assert any(line.startswith("build") for line in relevant(w, tam))
    tam.inventory.clear()
    act(w, mira, action="build", target="tent")
    assert relevant(w, tam)[0].startswith("build")


def test_designs_name_real_things():
    cat = Catalog.load()
    for key, d in building.DESIGNS.items():
        assert set(d["needs"]) <= set(cat.items), key
        assert d["work"] >= 1 and all(n >= 1 for n in d["needs"].values()), key
        if d.get("over_water"):
            assert d["kind"] in registry.KINDS and registry.KINDS[d["kind"]].get("over_water"), key
            continue
        rows = d["layout"]
        assert len({len(r) for r in rows}) == 1, key
        for ch in "".join(rows):
            assert ch == "." or registry.KINDS.get(d["legend"][ch]["kind"]), (key, ch)
        if d["roof"]:
            assert rows[-1].count("D") == 1 and "".join(rows[:-1]).count("D") == 0, key
            assert set(rows[0]) == {"#"} and all(r[0] == r[-1] == "#" for r in rows[1:-1]), key


# ------------------------------------------------------------------ the viewer, upkeep and saves
def test_viewer_hears_when_a_building_stands_or_falls():
    st = ServerState(seed=1)
    w = grass_world()
    st.world = st.sim.world = w
    mira = creature(w, "Mira", 10, 10)
    assert json.loads(st.tick_message([]))["buildings"] is None
    b = finish(w, mira, "tent")
    sent = json.loads(st.tick_message([]))["buildings"]
    assert [x["design"] for x in sent] == ["tent"] and sent[0]["roof"] is True
    assert json.loads(st.tick_message([]))["buildings"] is None  # only when something changed
    for oid in b["pieces"][:5]:
        w.remove_object(oid)  # say the steward takes most of it down
    system("building upkeep")(st.sim, w.tick)
    assert not building.buildings(w) and json.loads(st.tick_message([]))["buildings"] == []
    assert not roof_over(w, b["x0"] + 1, b["y0"] + 1)


def test_a_forgotten_site_falls_apart():
    w = grass_world()
    mira = creature(w, "Mira", 10, 10)
    mira.inventory["stick"] = 4
    act(w, mira, action="build", target="tent")
    sid, site = only_site(w)
    w.tick += building.STALE_TICKS
    system("building upkeep")(Simulation(w), w.tick)
    assert not building.sites(w) and sid not in w.objects
    assert sum(p.get("stick", 0) for p in w.ground.values()) == 4  # what was brought lies where it stood


def test_building_old_save_loads(prepack_save, tmp_path):
    st = ServerState(seed=1)
    restore(st, prepack_save)
    w = st.world
    for c in w.creatures.values():
        c.asleep = False
    for _ in range(200):
        st.tick_message(st.sim.tick())
    assert "buildings" in w.to_init()
    c = next(iter(w.creatures.values()))
    x, y = next((x, y) for y in range(5, 59) for x in range(5, 59)
                if all(w.tile(x + dx, y + dy) not in "wW" for dx in range(-4, 5) for dy in range(-4, 5))
                and not any(abs(o.x - x) <= 4 and abs(o.y - y) <= 4 for o in w.creatures.values()))
    for oid in [o.id for o in w.objects.values() if abs(o.x - x) <= 4 and abs(o.y - y) <= 4]:
        w.remove_object(oid)
    c.x, c.y, c.activity = x, y, None
    b = finish(w, c, "tent")
    path = tmp_path / "save.json"
    save(st, path)
    st2 = ServerState(seed=1)
    restore(st2, path)
    assert [x["design"] for x in st2.world.to_init()["buildings"]] == ["tent"]
    assert roof_over(st2.world, b["x0"] + 1, b["y0"] + 1)
    for _ in range(50):
        st2.tick_message(st2.sim.tick())
