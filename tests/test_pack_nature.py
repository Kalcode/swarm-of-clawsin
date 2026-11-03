"""Pack `nature`: biomes on a bigger map, flowing rivers, flowers, reeds, mushrooms and insects."""

import json
import time
from collections import Counter

import pytest

from swarmworld.server.persistence import restore, save
from swarmworld.server.state import ServerState
from swarmworld.world import registry
from swarmworld.world.actions import Intention, apply_intention
from swarmworld.world.catalog import DATA, Catalog
from swarmworld.world.model import DAY_TICKS, Creature, World
from swarmworld.world.packs import nature
from swarmworld.world.perception import DAY_SIGHT, FIRE_SIGHT, NIGHT_SIGHT, perceive, sight_range
from swarmworld.world.simulation import Simulation
from swarmworld.world.terrain import BIOMES, FLOW_STEP, biome_at, flow_at, generate_world, surface_rows

NIGHT = DAY_TICKS * 2 + int(DAY_TICKS * 0.8)
DAY = DAY_TICKS * 2 + int(DAY_TICKS * 0.3)


def fresh(seed=7):
    return generate_world(seed)


def creature(w, x, y, name="Tam", cid=None):
    c = Creature(cid or f"c{len(w.creatures) + 1}", name, x, y)
    c.asleep = False
    w.creatures[c.id] = c
    return c


def land_beside(w, o):
    return next((o.x + dx, o.y + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                if (dx or dy) and w.walkable(o.x + dx, o.y + dy) and w.tile(o.x + dx, o.y + dy) not in "wW")


def only_nature_lines():
    """A sandbox where the only perception lines are this pack's, so other packs' lines can't crowd them out."""
    box = registry.sandbox()
    box.__enter__()
    registry.PERCEPTIONS[:] = [p for p in registry.PERCEPTIONS if p.fn.__module__ == nature.__name__]
    return box


def chain(w, x, y, limit=2000):
    """Follow the flow from (x, y): the tiles passed, and where it ends (the first tile that doesn't flow)."""
    passed = []
    while flow_at(w, x, y) and len(passed) < limit:
        passed.append((x, y))
        dx, dy = FLOW_STEP[flow_at(w, x, y)]
        x, y = x + dx, y + dy
    return passed, (x, y)


# ----------------------------------------------------------------------------------------------- the land
@pytest.mark.parametrize("seed", [1, 7, 42])
def test_fresh_world_has_all_biomes(seed):
    t = time.perf_counter()
    w = fresh(seed)
    took = time.perf_counter() - t
    assert w.region_bounds("surface") == (0, 0, 128, 128)  # the deep lies below, past a band of rock
    assert took < 10.0, took  # about a second here; loose, so a busy machine doesn't fail it
    land = Counter(biome_at(w, x, y) for y in surface_rows(w) for x in range(w.width) if w.tile(x, y) not in "wW")
    assert set(BIOMES.values()) == {"meadow", "oak forest", "pine forest", "marsh", "rocky hills", "beach"}
    for name in BIOMES.values():
        assert land[name] >= 60, (name, land)
    assert biome_at(w, *w.center) == "meadow"

    def kinds_in(biome):
        return Counter(o.kind for o in w.objects.values() if biome_at(w, o.x, o.y) == biome)

    oak, pine = kinds_in("oak forest"), kinds_in("pine forest")
    assert oak["tree"] > 5 * oak["pine"] and pine["pine"] > 5 * pine["tree"]  # each forest is its own kind of tree
    hills = kinds_in("rocky hills")
    assert hills["rock"] >= 20 and hills["copper_vein"] + hills["iron_vein"] >= 3 and hills["flint_outcrop"] >= 2
    assert kinds_in("marsh")["reed_bed"] >= 5 and kinds_in("meadow")["flower_patch"] >= 20
    assert kinds_in("beach")["shell_bed"] >= 2
    beach = [(x, y) for y in surface_rows(w) for x in range(w.width)
             if biome_at(w, x, y) == "beach" and w.tile(x, y) not in "wW"]
    assert sum(w.tile(x, y) == "s" for x, y in beach) >= 0.8 * len(beach)
    hilly = [(x, y) for y in surface_rows(w) for x in range(w.width)
             if biome_at(w, x, y) == "rocky hills" and w.tile(x, y) not in "wW"]
    assert sum(w.tile(x, y) == "r" for x, y in hilly) >= 0.8 * len(hilly)
    k = Counter(o.kind for o in w.objects.values())
    assert k["terminal"] == 2 and k["wishing_stone"] == 1
    cx, cy = w.center
    assert all(max(abs(o.x - cx), abs(o.y - cy)) <= 45 for o in w.objects.values() if o.kind == "terminal")


def test_generation_is_deterministic_and_saves_the_land(tmp_path):
    a, b = fresh(3), fresh(3)
    assert a.tiles == b.tiles and a.ext["nature"] == b.ext["nature"]
    def things(w):
        return sorted((o.kind, o.x, o.y) for o in w.objects.values())

    assert things(a) == things(b)
    assert fresh(4).ext["nature"]["biomes"] != a.ext["nature"]["biomes"]
    st = ServerState(seed=3)
    save(st, tmp_path / "w.json")
    st2 = ServerState(seed=9)
    restore(st2, tmp_path / "w.json")
    assert st2.world.ext["nature"]["flow"] == st.world.ext["nature"]["flow"]
    assert st2.world.ext["nature"]["biomes"] == st.world.ext["nature"]["biomes"]


# ----------------------------------------------------------------------------------------------- rivers
def test_rivers_flow_and_drift():
    w = fresh()
    river = [(x, y) for y in surface_rows(w) for x in range(w.width) if flow_at(w, x, y)]
    assert len(river) >= 80
    assert all(w.tile(x, y) == "w" for x, y in river)  # rivers are shallow: you can wade across
    assert flow_at(w, *w.center) is None
    for x, y in river[::5]:  # downstream always ends in the lake or off the map, never in a loop
        passed, (ex, ey) = chain(w, x, y)
        assert len(passed) == len(set(passed)) and len(passed) < 2000
        assert not w.in_bounds(ex, ey) or w.tile(ex, ey) in "wW", (x, y, ex, ey)

    # a stick dropped in the river drifts downstream
    start = next(p for p in river if len(chain(w, *p)[0]) >= 12)
    downstream, _ = chain(w, *start)
    c = creature(w, *start)
    c.inventory["stick"] = 1
    assert apply_intention(w, c, Intention("drop", target="stick")).ok
    assert w.ground[start]["stick"] == 1
    c.x, c.y = w.center  # walk away: the river takes it
    sim = Simulation(w)
    for _ in range(40):
        sim.tick()
    assert start not in w.ground
    where = [p for p, pile in w.ground.items() if pile.get("stick")]
    assert len(where) == 1 and where[0] in downstream[3:]

    # beside the river, a creature is told which way it flows
    bank = next((x + dx, y + dy) for x, y in river for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                if w.in_bounds(x + dx, y + dy) and w.tile(x + dx, y + dy) not in "wW" and w.walkable(x + dx, y + dy))
    c2 = creature(w, *bank, name="Ivo")
    box = only_nature_lines()
    try:
        c2.ext["nature"] = {"biome": nature.biome_around(w, *bank)}  # it already knows where it is
        text = perceive(w, c2)
        line = next(ln for ln in text.splitlines() if "river" in ln and "flows" in ln)
        assert any(f"flows {flow_at(w, bank[0] + dx, bank[1] + dy)}" in line
                   for dx in (-1, 0, 1) for dy in (-1, 0, 1))
        c2.wake_reason = None
        assert "flows" not in perceive(w, c2)  # said once, not every turn
    finally:
        box.__exit__(None, None, None)


# ----------------------------------------------------------------------------------------------- plants
def test_flowers_and_reeds_gather_from_data():
    data = json.loads((DATA / "packs" / "nature" / "objects.json").read_text())
    for kind in ("flower_patch", "reed_bed", "mushroom_patch", "shell_bed", "driftwood", "flint_outcrop"):
        assert data[kind]["yields"] and kind in registry.YIELDS and data[kind]["look"]
        assert registry.owner("object kind", kind) == "packs/nature/objects.json"
    w = fresh()
    have = Counter(o.kind for o in w.objects.values())
    assert have["flower_patch"] >= 60 and have["reed_bed"] >= 20 and have["mushroom_patch"] >= 20
    for kind, said, item in (("flower_patch", "flowers", "flower"), ("reed_bed", "reeds", "reed"),
                             ("mushroom_patch", "mushrooms", "mushroom"), ("shell_bed", "shells", "shell"),
                             ("driftwood", "driftwood", "stick"), ("flint_outcrop", "flint", "flint")):
        o = next(o for o in w.objects.values() if o.kind == kind and land_beside(w, o))
        c = creature(w, *land_beside(w, o))
        res = apply_intention(w, c, Intention("gather", target=said))
        assert res.ok and c.inventory[item] >= 1, (kind, res.message)
        del w.creatures[c.id]
    # picked bare, a flower patch shows it and grows back
    o = next(o for o in w.objects.values() if o.kind == "flower_patch" and land_beside(w, o))
    c = creature(w, *land_beside(w, o))
    for _ in range(registry.YIELDS["flower_patch"]["uses"]):
        apply_intention(w, c, Intention("gather", target="flower patch"))
    assert o.kind == "picked_flowers"
    w.tick = o.data["regrow_at"]
    Simulation(w)._regrow(w.tick)
    assert o.kind == "flower_patch"
    cat = Catalog.load()
    for item in ("flower", "reed", "mushroom", "shell"):
        assert item in cat.items and cat.items[item].desc


def test_mushrooms_and_shells_come_back():
    w = fresh()
    sim = Simulation(w)
    targets = w.ext["nature"]["targets"]
    for kind in ("mushroom_patch", "shell_bed", "driftwood"):
        gone = [o for o in w.objects.values() if o.kind == kind]
        assert len(gone) == targets[kind] > 0
        for o in gone[: len(gone) // 2]:
            w.remove_object(o.id)
    for i in range(30):
        nature.renew_step(sim, i * 300)
    have = Counter(o.kind for o in w.objects.values())
    for kind in ("mushroom_patch", "shell_bed", "driftwood"):
        assert targets[kind] * 0.9 <= have[kind] <= targets[kind], kind
    assert all(biome_at(w, o.x, o.y) in ("oak forest", "pine forest") for o in w.objects.values()
               if o.kind == "mushroom_patch")


# ----------------------------------------------------------------------------------------------- insects
def test_fireflies_light_at_night():
    w = World(30, 30, [["g"] * 30 for _ in range(30)], Catalog.load())
    w.tick = NIGHT
    c = creature(w, 10, 10)
    w.add_object("tree", 13, 10, wood=6)
    assert sight_range(w, c) == NIGHT_SIGHT and "oak tree" not in perceive(w, c)
    w.add_object("firefly", 11, 12)
    assert NIGHT_SIGHT < sight_range(w, c) < FIRE_SIGHT  # a little light, much less than a fire
    text = perceive(w, c)
    assert "oak tree 3 steps east" in text and "firefly" in text
    assert "couple of steps" not in text and "glow" in text and "firelight" not in text
    assert "cold" in text  # fireflies don't warm you
    w.tick = DAY
    assert sight_range(w, c) == DAY_SIGHT  # by day they make no difference
    far = World(30, 30, [["g"] * 30 for _ in range(30)], Catalog.load())
    far.tick = NIGHT
    c2 = creature(far, 5, 5)
    far.add_object("firefly", 11, 5)
    assert sight_range(far, c2) == NIGHT_SIGHT and "firefly 6 steps east" in perceive(far, c2)  # seen from afar


def test_insects_come_and_go_with_the_day():
    w = fresh()
    w.weather = "clear"
    sim = Simulation(w)

    def count():
        return Counter(o.kind for o in w.objects.values() if o.kind in nature.INSECTS)

    w.tick = DAY
    for _ in range(20):
        w.tick += 10
        nature.insects_step(sim, w.tick)
    day = count()
    assert day["honeybee"] >= 5 and day["butterfly"] >= 5 and day["firefly"] == 0
    flowers = [(o.x, o.y) for o in w.objects.values() if o.kind in ("flower_patch", "picked_flowers")]
    for o in w.objects.values():
        if o.kind == "honeybee":  # bees keep to the flowers
            assert any(max(abs(o.x - x), abs(o.y - y)) <= 2 for x, y in flowers)
    assert sum(day.values()) <= 80
    w.tick = NIGHT
    for _ in range(15):
        w.tick += 10
        nature.insects_step(sim, w.tick)
    night = count()
    assert night["firefly"] >= 8 and night["honeybee"] == 0 and night["butterfly"] == 0
    for o in w.objects.values():
        if o.kind == "firefly":
            assert biome_at(w, o.x, o.y) in ("marsh", "oak forest") or any(
                w.tile(o.x + dx, o.y + dy) in "wW" for dx in range(-2, 3) for dy in range(-2, 3))
    w.weather = "rain"
    for _ in range(40):
        nature.insects_step(sim, w.tick)
    assert sum(count().values()) == 0  # they shelter from the rain


# ----------------------------------------------------------------------------------------------- perception
def test_biome_line_only_on_change():
    w = fresh()
    box = only_nature_lines()
    try:
        c = creature(w, *w.center)
        meadow = nature.BIOME_LINES["m"]
        assert meadow in perceive(w, c)
        c.wake_reason = None
        assert meadow not in perceive(w, c)  # not every turn
        x, y = next((x, y) for y in surface_rows(w) for x in range(w.width) if w.walkable(x, y)
                    and all(biome_at(w, x + dx, y + dy) == "oak forest" for dx in range(-2, 3) for dy in range(-2, 3)))
        c.x, c.y = x, y
        oak = nature.BIOME_LINES["o"]
        assert oak in perceive(w, c)
        c.wake_reason = "idle"
        assert oak not in perceive(w, c) and meadow not in perceive(w, c)
        edge = next((x, y) for y in surface_rows(w) for x in range(w.width) if w.walkable(x, y)
                    and biome_at(w, x, y) == "meadow" and Counter(biome_at(w, x + dx, y + dy) for dx in range(-2, 3)
                                                                  for dy in range(-2, 3))["oak forest"] >= 12)
        c.x, c.y = edge  # a step out of the trees onto a ragged edge: still the forest, mostly
        assert meadow not in perceive(w, c)
        c.wake_reason = "woke"  # waking up: where am I?
        assert oak in perceive(w, c)
        assert all(len(line) <= 90 for line in nature.BIOME_LINES.values())
    finally:
        box.__exit__(None, None, None)
    hand_built = World(20, 20, [["g"] * 20 for _ in range(20)], Catalog.load())
    assert nature.biome_line(hand_built, creature(hand_built, 5, 5)) is None  # a world without biomes says nothing


# ----------------------------------------------------------------------------------------------- old saves
def test_nature_old_save_loads(prepack_save):
    st = ServerState(seed=1)
    restore(st, prepack_save)
    w = st.world
    assert w.region_bounds("surface") == (0, 0, 64, 64)
    mine = w.ext["nature"]
    assert len(mine["biomes"]) == 64 and all(len(r) == 64 for r in mine["biomes"])
    assert biome_at(w, 32, 32) == "meadow" and biome_at(w, 0, 0) in ("oak forest", "pine forest")
    river = [(x, y) for y in range(64) for x in range(64) if flow_at(w, x, y)]
    assert len(river) >= 40  # the old river flows now
    for x, y in river:  # into the lake, or out at the edge of the map (where the old rivers stopped a step short)
        _, (ex, ey) = chain(w, x, y)
        assert not w.in_bounds(ex, ey) or w.tile(ex, ey) in "wW" or ex in (0, 63) or ey in (0, 63), (x, y, ex, ey)
    assert flow_at(w, 49, 48) is None  # the lake itself is still
    placed = sorted((o.kind, o.x, o.y) for o in w.objects.values() if o.kind in nature.PLANTS)
    assert Counter(k for k, _, _ in placed)["flower_patch"] >= 5
    from swarmworld.world.registry import run_populate
    run_populate(w, w.rng, fresh=False)  # idempotent
    assert sorted((o.kind, o.x, o.y) for o in w.objects.values() if o.kind in nature.PLANTS) == placed
    for c in w.creatures.values():
        c.asleep = False
    for _ in range(200):
        st.tick_message(st.sim.tick())
    assert w.tick == 1044 + 200 and all(perceive(w, c) for c in w.creatures.values())
