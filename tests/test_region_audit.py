"""The region audit: the land, nature, food, weather and building keep to the surface; cave water is water (Task 4).

A generated world has its own deep (the underground pack grows it); with_deep(w) leaves that as it is, and gives a
world made with deep=False a deep of 40 rows below it (rows 80-119, after the rock band), shorter than the surface so
that a mix-up of the two heights or areas can't pass. Tests that need ground a careless whole-map scan would use paint
some of the deep as grass, forest floor or dirt (dug or filled ground looks like that), so a scan that strays below
finds somewhere to put things."""

import random
from collections import Counter

from swarmworld.mind.memory import Memory
from swarmworld.mind.prompts import build_act_messages
from swarmworld.world.actions import Intention, apply_intention
from swarmworld.world.model import ANIMALS, DAY_TICKS, START_TICK, Creature
from swarmworld.world.packs import building, food, nature, weather
from swarmworld.world.perception import DIRS, _far_features, note_spots, perceive
from swarmworld.world.registry import run_populate
from swarmworld.world.simulation import Simulation
from swarmworld.world.terrain import (ANIMAL_POPULATION, _lake_tiles, biome_at, derive_biomes, derive_flow, flow_at,
                                      generate_world, spawn_animals, water_near)

SIZE = 48
DEEP_ROWS = 40  # not the surface's height
SURFACE_KINDS = set(nature.PLANTS) | set(nature.INSECTS) | set(food.habitat_kinds()) | set(ANIMALS)


def with_deep(w, h=DEEP_ROWS):
    """Add a deep of h rows (rock round the edge, cave floor inside) below w unless it has one (a generated world
    has); its bounds."""
    if w.region("deep") is None:
        rows = [["R" if x in (0, w.width - 1) or y in (0, h - 1) else "c" for x in range(w.width)] for y in range(h)]
        w.add_region("deep", -1, rows, False, False)
    return w.region_bounds("deep")


def paint_ground(w, y0, y1):
    """Grass, forest floor and dirt over most of the deep, as if it had been dug and filled."""
    for y in range(y0 + 2, y1 - 2):
        for x in range(2, w.width - 2):
            w.set_tile(x, y, "gfd"[(x + y) % 3])


def person(w, name, x, y, **kw):
    c = Creature(f"c{len(w.creatures) + 1}", name, x, y, asleep=False, **kw)
    w.creatures[c.id] = c
    return c


def test_surface_systems_never_touch_the_deep():
    w = generate_world(7, SIZE, SIZE)
    _, y0, _, y1 = with_deep(w)
    paint_ground(w, y0, y1)
    sim = Simulation(w)
    person(w, "Ana", *w.center)
    person(w, "Bo", w.center[0] + 2, w.center[1])
    sounds = []
    for kind in ("storm", "heat", "wind"):
        weather.set_weather(w, kind, w.tick + 200)
        for _ in range(200):
            sounds += [e for e in sim.tick() if e.kind == "sound"]
    below = [o for o in w.objects.values() if o.kind in SURFACE_KINDS and not w.under_sky(o.x, o.y)]
    assert below == []
    assert sounds and all(w.region_at(e.x, e.y) is w.region("surface") for e in sounds)


def test_packs_populate_only_the_surface():
    w = generate_world(7, SIZE, SIZE)
    _, y0, _, y1 = with_deep(w)
    paint_ground(w, y0, y1)
    w.ext["nature"]["planted"] = False  # as if the packs had never placed anything here
    w.ext["food"]["placed"] = False
    before = set(w.objects)
    run_populate(w, random.Random(3), fresh=True)
    new = [w.objects[i] for i in set(w.objects) - before]
    assert {o.kind for o in new} & set(nature.PLANTS) and {o.kind for o in new} & set(food.habitat_kinds())
    assert [o for o in new if not w.under_sky(o.x, o.y)] == []


def test_population_counts_ignore_the_deep():
    w = generate_world(7, SIZE, SIZE, deep=False)
    kinds = sorted(food.habitat_kinds())
    counts = {k: food.population(w, k) for k in kinds}
    caps = {k: nature.insect_cap(w, k) for k in nature.INSECTS}
    with_deep(w)
    assert {k: food.population(w, k) for k in kinds} == counts
    assert {k: nature.insect_cap(w, k) for k in nature.INSECTS} == caps
    assert caps == {k: round(n * SIZE * SIZE / 128 ** 2) for k, n in nature.INSECT_CAP.items()}


def test_game_and_animals_below_never_fill_the_surface_quota():
    w = generate_world(7, SIZE, SIZE)
    _, y0, _, _ = with_deep(w)
    sim = Simulation(w)
    for kind, n in ANIMAL_POPULATION.items():  # a whole herd of each kind down here...
        for i in range(n):
            w.add_object(kind, 5 + i, y0 + 5 + 2 * list(ANIMAL_POPULATION).index(kind))
    gone = [o for o in w.objects.values() if o.kind == "chicken" and w.under_sky(o.x, o.y)][:2]
    for o in gone:  # ...and two chickens gone from up top
        w.remove_object(o.id)
    assert spawn_animals(w, random.Random(5)) == 2
    deer = [o for o in w.objects.values() if o.kind == "deer"]
    assert deer and all(w.move_object(o, 5 + i, y0 + 20) for i, o in enumerate(deer))  # all the deer go below
    food._wildlife(sim, 300)
    assert any(o.kind == "deer" and w.under_sky(o.x, o.y) for o in w.objects.values())


def test_drift_carries_off_the_surface_edge():
    w = generate_world(7, SIZE, SIZE)
    _, y0, _, _ = with_deep(w)
    sim = Simulation(w)
    x, y = 20, SIZE - 1  # the surface's last row: below it is the rock band
    w.set_tile(x, y, "w")
    flow = w.ext["nature"]["flow"]
    flow[y] = flow[y][:x] + str(DIRS.index("south")) + flow[y][x + 1:]
    w.set_tile(10, y0 + 10, "u")  # cave water, with a pile in it
    w.drop_items(x, y, Counter({"stick": 1}))
    w.drop_items(10, y0 + 10, Counter({"stone": 1}))
    nature.drift_step(sim, 4)
    assert (x, y) not in w.ground  # the river carried it off the surface
    assert w.ground[(10, y0 + 10)] == {"stone": 1}  # nothing flows down here


def test_biome_and_river_lines_are_silent_below():
    w = generate_world(7, SIZE, SIZE)
    _, y0, _, _ = with_deep(w)
    low = person(w, "Low", 10, y0 + 10)
    w.set_tile(11, y0 + 10, "u")
    for x, y in ((10, y0 + 10), (11, y0 + 10), (10, SIZE + 3), (10, -1)):  # the deep, the rock band, off the map
        assert biome_at(w, x, y) is None and flow_at(w, x, y) is None and nature.biome_around(w, x, y) is None
    assert nature.biome_around(w, 10, SIZE - 1) is not None  # the surface's edge reads only the surface
    assert nature.biome_line(w, low) is None and nature.river_line(w, low) is None
    text = perceive(w, low)
    assert "You're in" not in text and "river beside you" not in text


def test_weather_lines_are_silent_below(two_levels):
    w = two_levels(24)
    top, low = person(w, "Top", 10, 10), person(w, "Low", 10, 60)
    for kind, line in weather.LINES.items():
        weather.set_weather(w, kind, 10_000)
        assert weather._weather_line(w, top) == line
        assert weather._weather_line(w, low) is None
        assert line not in perceive(w, low)


def test_thunder_strikes_the_surface_only(monkeypatch):
    w = generate_world(7, SIZE, SIZE)
    _, y0, _, _ = with_deep(w)
    deep_tree = w.add_object("tree", 10, y0 + 5, wood=6)  # planted down here: no lightning reaches it
    monkeypatch.setattr(weather, "THUNDER_CHANCE", 1.0)
    w.events.clear()
    for t in range(200):
        weather._storm(w, t)
    sounds = [e for e in w.events if e.kind == "sound"]
    assert len(sounds) == 200 and any(e.text == "a crack of thunder" for e in sounds)
    assert all(w.region_at(e.x, e.y) is w.region("surface") for e in sounds)
    assert not deep_tree.data.get("burning")


def test_wind_and_heat_spare_the_deep(two_levels):
    w = two_levels(24)
    sim = Simulation(w)
    top_fire = w.add_object("campfire", 5, 5, lit=True, lit_until=10_000)
    deep_fire = w.add_object("campfire", 5, 60, lit=True, lit_until=10_000)
    top, low = person(w, "Top", 10, 10), person(w, "Low", 10, 60)
    weather.set_weather(w, "wind", 10_000)
    weather._step(sim, 10)
    assert top_fire.data["lit_until"] == 10_000 - weather.FIRE_EXTRA
    assert deep_fire.data["lit_until"] == 10_000
    weather.set_weather(w, "heat", 10_000)
    weather._step(sim, 48)
    assert top.satiety == 79 and low.satiety == 80


def test_rain_and_wind_never_reach_a_rack_or_a_crop_below(two_levels):
    w = two_levels(24)
    sim = Simulation(w)
    t = w.tick = START_TICK + 100  # morning
    racks = [w.add_object("drying_rack", 5, y, items={"meat": 1}) for y in (5, 60)]
    crops = [w.add_object("crop", 8, y, stage=0, grow_at=t + 500) for y in (5, 60)]
    low = person(w, "Low", 5, 61)
    weather.set_weather(w, "rain", 10_000)
    sim._regrow(t)
    food._dry(sim, t)
    assert crops[0].data["grow_at"] == t + 490 and crops[1].data["grow_at"] == t + 500  # rain speeds only the top
    assert "drying" not in racks[0].data and racks[1].data["drying"] == {"meat": food.DRY_EVERY}
    assert food._rack_line(w, low) == "On the drying rack beside you, the raw meat is only just set out."
    weather.set_weather(w, "wind", 10_000)
    food._dry(sim, t)
    assert racks[0].data["drying"] == {"meat": 2 * food.DRY_EVERY}  # wind dries it twice as fast up top
    assert racks[1].data["drying"] == {"meat": 2 * food.DRY_EVERY}  # below, as on a still day
    weather.set_weather(w, "clear", 10_000)
    w.tick = DAY_TICKS * 2 + int(DAY_TICKS * 0.8)  # night: only up top does it dry more slowly
    food._dry(sim, w.tick)
    assert racks[0].data["drying"] == {"meat": 2 * food.DRY_EVERY + food.DRY_EVERY // 2}
    assert racks[1].data["drying"] == {"meat": 3 * food.DRY_EVERY}


def test_no_building_sites_or_wells_underground(two_levels):
    w = two_levels(24)
    top, low = person(w, "Top", 10, 10), person(w, "Low", 10, 66)
    res = apply_intention(w, low, Intention("build", target="hut"))
    assert not res.ok and res.message == "There's no room to raise a building down here; build up on the surface."
    res = apply_intention(w, low, Intention("build", target="well"))  # a well site
    assert not res.ok and res.message == "There's no room to raise a building down here; build up on the surface."
    assert not building.sites(w)
    low.inventory["well"] = 1  # a well already made
    for it in (Intention("place", target="well"), Intention("build", target="well")):
        res = apply_intention(w, low, it)
        assert not res.ok and res.message == "A well needs open ground up on the surface."
    assert low.inventory["well"] == 1 and not any(o.kind == "well" for o in w.objects.values())
    assert apply_intention(w, top, Intention("build", target="hut")).ok  # up on the surface, all as before
    top.inventory["well"] = 1
    assert apply_intention(w, top, Intention("place", target="well")).ok


def test_cave_water_is_drinkable_and_fishable(two_levels):
    w = two_levels(24)
    low = person(w, "Low", 10, 60)
    w.set_tile(11, 60, "u")
    res = apply_intention(w, low, Intention("drink"))
    assert res.ok and res.message == "You drink cool water and feel refreshed."
    low.inventory["fishing_rod"] = 1
    res = apply_intention(w, low, Intention("gather", target="fish"))
    assert res.ok and low.activity["label"] == "fishing"
    low.activity = None
    low.inventory["clay_pot"] = 1
    assert apply_intention(w, low, Intention("fill")).ok and low.inventory["water_pot"] == 1
    assert food._water_type(w, low.x, low.y) == "shallow"
    assert "water" in _far_features(w, low, 6)
    note_spots(w, low, w.tick)
    assert low.spots["water"][:2] == (11, 60)
    far = person(w, "Far", 16, 60)
    w.add_object("campfire", 17, 61, lit=True, lit_until=10_000)  # firelight to see the water by
    res = apply_intention(w, far, Intention("walk_to", target="water"))
    assert res.ok and far.activity["type"] == "walk"
    # place never sets a thing down in cave water: only the tile southeast of here is dry
    maker = person(w, "Maker", 10, 70)
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            if (dx or dy) and (dx, dy) != (1, 1):
                w.set_tile(10 + dx, 70 + dy, "u")
    maker.inventory["campfire"] = 1
    assert apply_intention(w, maker, Intention("place", target="campfire")).ok
    fire = next(o for o in w.objects.values() if o.data.get("builder") == "Maker")
    assert (fire.x, fire.y) == (11, 71)


def test_old_world_land_is_read_from_the_surface_only():
    a, b = generate_world(7, SIZE, SIZE), generate_world(7, SIZE, SIZE)
    _, y0, _, y1 = with_deep(b)
    paint_ground(b, y0, y1)
    for x in range(5, 15):  # a pool, a stream, rock and sand down here that a careless scan would read
        b.set_tile(x, y0 + 5, "W")
        b.set_tile(x, y0 + 6, "w")
        b.set_tile(x, y0 + 7, "r")
        b.set_tile(x, y0 + 8, "s")
    assert derive_biomes(b) == derive_biomes(a) and len(derive_biomes(b)) == SIZE
    assert derive_flow(b) == derive_flow(a) and len(derive_flow(b)) == SIZE
    assert _lake_tiles(b) == _lake_tiles(a)
    assert (water_near(b, 2) == water_near(a, 2)).all()
    del b.ext["nature"]["biomes"], b.ext["nature"]["flow"]  # an older world: its land is read from its tiles
    b.land = None
    nature.populate(b, random.Random(1), fresh=False)
    assert len(b.ext["nature"]["biomes"]) == len(b.ext["nature"]["flow"]) == SIZE


def test_surface_is_the_same_with_a_deep_below():
    worlds = generate_world(7, SIZE, SIZE, deep=False), generate_world(7, SIZE, SIZE)  # without the deep, and with it
    assert worlds[0].region("deep") is None and worlds[1].region("deep") is not None
    persona = {"traits": ["curious", "patient"], "drive": "curious", "initiative": "proactive"}
    tams = [person(w, "Tam", *w.center, persona=dict(persona)) for w in worlds]
    views = [perceive(w, c) for w, c in zip(worlds, tams)]
    assert views[0] == views[1]
    msgs = [build_act_messages(w, c, Memory(), v) for w, c, v in zip(worlds, tams, views)]
    assert msgs[0] == msgs[1]
    sims = [Simulation(w) for w in worlds]
    for w in worlds:
        weather.set_weather(w, "storm", w.tick + 150)  # thunder and a wild-game top-up both roll the world's dice
    for _ in range(300):
        for sim in sims:
            sim.tick()
    a, b = worlds
    assert perceive(a, tams[0]) == perceive(b, tams[1])
    assert a.weather == b.weather and a.rng.getstate() == b.rng.getstate()
