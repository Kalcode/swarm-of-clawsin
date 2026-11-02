"""Pack food: fish species by water and time, cooking at campfire, oven and smoker, the drying rack and the well, clay
pots that carry water, wild deer, rabbits and boar that flee sooner, hunting with a spear or sling, leather from hide,
foraging mushrooms and herbs, and raw meat and fish that spoil unless cooked, smoked or dried."""

import random
from collections import Counter

from swarmworld.mind.techniques import relevant
from swarmworld.server.persistence import restore
from swarmworld.server.state import ServerState
from swarmworld.world import registry
from swarmworld.world.actions import Intention, apply_intention, step_activity
from swarmworld.world.catalog import Catalog
from swarmworld.world.model import DAY_TICKS, START_TICK, Creature, World
from swarmworld.world.packs import food
from swarmworld.world.perception import perceive
from swarmworld.world.simulation import Simulation
from swarmworld.world.terrain import generate_world

PHASE_AT = {"dawn": 0.05, "day": 0.3, "dusk": 0.6, "night": 0.8}  # a time of day in each phase (World.clock)


class Fixed(random.Random):
    """An rng whose random() is always the same number, to decide a hit or a miss; randint still varies."""

    def __init__(self, value: float):
        super().__init__(1)
        self.value = value

    def random(self):
        return self.value


def grass_world(size=40):
    w = World(size, size, [["g"] * size for _ in range(size)], Catalog.load())
    w.tick = START_TICK + 100  # morning
    w.rng = random.Random(5)
    return w


def set_phase(w, phase):
    w.tick = (w.tick // DAY_TICKS) * DAY_TICKS + int(DAY_TICKS * PHASE_AT[phase])
    assert w.clock()["phase"] == phase


def creature(w, name="Tam", x=10, y=10):
    c = Creature(f"c{len(w.creatures) + 1}", name, x, y, asleep=False, wake_reason=None, last_think_tick=w.tick)
    c.known_recipes = {r.output for r in w.catalog.recipes if r.known_at_start}
    w.creatures[c.id] = c
    return c


def act(w, c, **kw):
    res = apply_intention(w, c, Intention(**kw))
    while c.activity:
        step_activity(w, c)
    return res


def system(name):
    return next(s.fn for s in registry.SYSTEMS if s.name == name)


def campfire(w, x, y):
    return w.add_object("campfire", x, y, lit=True, lit_until=w.tick + 10_000)


def quiet_sim(w, memories=None):
    """A simulation whose weather stays as the test sets it; memories, if given, collects what creatures remember."""
    sink = (lambda c, text, imp: memories.append((c.name, text))) if memories is not None else None
    sim = Simulation(w, memory_sink=sink)
    sim._weather = lambda t: None
    return sim


# ------------------------------------------------------------------ fishing
def fish_many(w, c, casts=40):
    caught = Counter()
    c.inventory["fishing_rod"] = 1
    for _ in range(casts):
        before = Counter(c.inventory)
        res = act(w, c, action="gather", target="fish")
        assert res.ok
        caught += Counter(c.inventory) - before
    return caught


def test_fish_species_by_water_and_time():
    w = grass_world()
    for y in range(5, 15):
        for x in range(2, 6):
            w.tiles[y][x] = "w"   # a shallow pond in the west
        for x in range(30, 36):
            w.tiles[y][x] = "W"   # deep water in the east
    shallow = creature(w, "Tam", 6, 10)
    deep = creature(w, "Mara", 29, 10)

    set_phase(w, "day")
    by_day_shallow, by_day_deep = fish_many(w, shallow), fish_many(w, deep)
    assert by_day_shallow["perch"] and not by_day_shallow["trout"] and not by_day_shallow["eel"]
    assert by_day_deep["trout"] and not by_day_deep["perch"] and not by_day_deep["eel"]

    set_phase(w, "night")
    at_night = fish_many(w, shallow) + fish_many(w, deep)
    assert at_night["eel"] and not at_night["perch"] and not at_night["trout"]

    w.rng = Fixed(0.0)  # a bite on every cast: the result names what bit
    res = act(w, deep, action="gather", target="fish")
    assert res.ok and "catch" in res.message and any(f in res.message for f in ("eel", "fish"))
    assert all(f in food.FISHING_ITEMS for f in ("fish", "perch", "trout", "eel"))  # the species are data


def test_fishing_line_says_what_bites_here_once():
    w = grass_world()
    for x in range(30, 36):
        w.tiles[10][x] = "W"
    c = creature(w, "Mara", 29, 10)
    c.inventory["fishing_rod"] = 1
    set_phase(w, "day")
    first = perceive(w, c)
    assert "trout" in first and "deep water" in first
    assert "trout" not in perceive(w, c)  # said once, not every turn
    set_phase(w, "night")
    assert "eel" in perceive(w, c)


# ------------------------------------------------------------------ cooking
def test_cook_stew_at_fire():
    w = grass_world()
    c = creature(w)
    fire = campfire(w, 11, 10)
    c.inventory.update({"fish": 1, "herbs": 1})
    res = act(w, c, action="combine", items=["fish", "wild herbs"])
    assert not res.ok and "pot of water" in res.message  # a stew simmers in a pot of water you hold
    c.inventory["water_pot"] = 1
    res = act(w, c, action="combine", items=["fish", "wild herbs"])
    assert res.ok and c.inventory["fish_stew"] == 1 and c.inventory["water_pot"] == 1
    assert "fish_stew" in c.known_recipes
    cat = w.catalog
    assert cat.items["fish_stew"].food > cat.items["cooked_fish"].food > cat.items["fish"].food

    c.inventory.update({"meat": 1, "mushroom": 1})
    assert act(w, c, action="craft", target="meat stew").ok is False  # not known yet
    assert act(w, c, action="combine", items=["raw meat", "mushroom"]).ok and c.inventory["meat_stew"] == 1
    fire.data["lit"] = False
    c.inventory.update({"meat": 1, "mushroom": 1})
    res = act(w, c, action="craft", target="meat stew")
    assert not res.ok and "campfire" in res.message  # a cold fire cooks nothing

    c.satiety = 20
    assert act(w, c, action="eat", target="fish stew").ok and c.satiety > 80


def test_oven_and_smoker_are_placeable_stations():
    w = grass_world()
    c = creature(w)
    c.inventory.update({"brick": 3, "clay": 2, "planks": 3, "stone": 3})
    assert act(w, c, action="combine", items=["brick", "clay"]).ok and c.inventory["oven"] == 1
    assert act(w, c, action="combine", items=["planks", "stone"]).ok and c.inventory["smoker"] == 1
    assert act(w, c, action="place", target="oven").ok
    c.x += 8  # far from the oven
    assert act(w, c, action="place", target="smoker").ok
    kinds = {o.kind for o in w.objects.values()}
    assert {"oven", "smoker"} <= kinds and all(registry.LOOKS.get(k) for k in ("oven", "smoker"))

    c.inventory.update({"fish": 2, "meat": 1})
    assert act(w, c, action="combine", items=["fish"]).ok and c.inventory["smoked_fish"] == 1  # by the smoker
    assert act(w, c, action="combine", items=["raw meat"]).ok and c.inventory["smoked_meat"] == 1
    c.x -= 8  # back by the oven
    c.inventory.update({"flour": 1, "berries": 3})
    assert act(w, c, action="combine", items=["flour", "berries"]).ok and c.inventory["berry_pie"] == 1
    campfire(w, c.x, c.y - 1)
    c.inventory.update({"mushroom": 2})
    assert act(w, c, action="combine", items=["mushroom"]).ok and c.inventory["roasted_mushrooms"] == 1


def test_cook_tip_shows_when_food_and_a_station_are_at_hand():
    w = grass_world()
    c = creature(w)
    c.inventory["meat"] = 1
    assert not any("cook" in line for line in relevant(w, c, packs_only=True))
    campfire(w, 11, 10)
    assert any("cook" in line for line in relevant(w, c, packs_only=True))


# ------------------------------------------------------------------ drying, spoiling
def test_drying_rack_dries_meat():
    w = grass_world()
    sim = quiet_sim(w)
    c = creature(w)
    c.inventory.update({"stick": 4, "rope": 2, "log": 1})
    assert act(w, c, action="combine", items=["stick", "rope", "log"]).ok and c.inventory["drying_rack"] == 1
    assert act(w, c, action="place", target="drying rack").ok
    rack = next(o for o in w.objects.values() if o.kind == "drying_rack")
    assert registry.LOOKS["drying_rack"]
    c.inventory.update({"meat": 2, "trout": 1})
    assert any("drying rack" in line for line in relevant(w, c, packs_only=True))
    assert act(w, c, action="store", target="drying rack", items=["raw meat", "trout"]).ok
    assert rack.data["items"] == {"meat": 2, "trout": 1}
    assert "drying rack (holding 2 raw meat, 1 trout)" in perceive(w, c)

    w.weather, w.weather_until = "rain", w.tick + 10**6  # nothing dries in the rain
    for _ in range(food.DRY_TICKS + 40):
        sim.tick()
    assert rack.data["items"] == {"meat": 2, "trout": 1}
    assert "wet" in perceive(w, c)

    w.weather = "clear"
    set_phase(w, "day")
    for _ in range(food.DRY_TICKS // 2):
        sim.tick()
    assert "half dry" in perceive(w, c) or "nearly dry" in perceive(w, c)
    for _ in range(food.DRY_TICKS):
        sim.tick()
    assert rack.data["items"] == {"jerky": 2, "dried_fish": 1}
    assert act(w, c, action="take", target="drying rack", items=["jerky"], count=2).ok and c.inventory["jerky"] == 2


def test_raw_meat_spoils_but_dried_and_cooked_food_keeps():
    w = grass_world()
    memories = []
    sim = quiet_sim(w, memories)
    c = creature(w)
    c.inventory.update({"meat": 2, "jerky": 2, "cooked_fish": 1})
    basket = w.add_object("basket", 11, 10, items={"fish": 3, "dried_fish": 1})
    w.drop_items(12, 12, Counter({"perch": 1}))
    spoil = system("food spoilage")
    start = w.tick
    spoil(sim, w.tick)
    w.tick = start + food.WARN_AFTER
    spoil(sim, w.tick)
    assert any("raw meat" in text and "smell" in text for _, text in memories)
    w.tick = start + food.SPOILS_AFTER
    spoil(sim, w.tick)
    assert c.inventory == Counter({"jerky": 2, "cooked_fish": 1})
    assert basket.data["items"] == {"dried_fish": 1} and (12, 12) not in w.ground
    assert any("went bad" in text for _, text in memories)


def test_a_mind_away_keeps_its_food_fresh():
    w = grass_world()
    sim = quiet_sim(w)
    c = creature(w)
    c.inventory["meat"] = 1
    spoil = system("food spoilage")
    spoil(sim, w.tick)
    c.asleep = True  # its brain node is offline: the body is in stasis
    for _ in range(food.SPOILS_AFTER // food.SPOIL_EVERY + 2):
        w.tick += food.SPOIL_EVERY
        spoil(sim, w.tick)
    assert c.inventory["meat"] == 1


# ------------------------------------------------------------------ water
def test_well_fills_a_pot():
    w = grass_world()
    c = creature(w)
    c.inventory.update({"stone": 6, "rope": 2, "planks": 2, "clay": 2, "sand": 1})
    assert act(w, c, action="combine", items=["stone", "rope", "planks"]).ok and c.inventory["well"] == 1
    assert act(w, c, action="place", target="well").ok
    assert act(w, c, action="drink").ok  # a well is water within reach
    res = act(w, c, action="fill", target="well")
    assert not res.ok and "clay pot" in res.message
    campfire(w, 10, 11)
    assert act(w, c, action="combine", items=["clay", "sand"]).ok and c.inventory["clay_pot"] == 1
    c.inventory["clay_pot"] += 1
    assert any("fill" in line for line in relevant(w, c, packs_only=True))
    res = act(w, c, action="fill", target="well")
    assert res.ok and c.inventory["water_pot"] == 2 and c.inventory["clay_pot"] == 0
    assert any(e.kind == "sound" and e.data["sound"] == "splash" for e in w.events)

    c.x, c.y, c.energy = 30, 30, 50  # far from any water
    res = act(w, c, action="drink")
    assert res.ok and c.energy == 60 and c.inventory["water_pot"] == 1 and c.inventory["clay_pot"] == 1
    w.tiles[30][32] = "w"  # a stream two steps east: fill walks there first
    res = act(w, c, action="fill")
    assert res.ok and c.inventory["water_pot"] == 2 and c.inventory["clay_pot"] == 0 and (c.x, c.y) != (30, 30)
    res = act(w, c, action="fill")
    assert not res.ok and "full" in res.message


# ------------------------------------------------------------------ wild game and hunting
def test_wild_game_flees_sooner():
    w = grass_world()
    c = creature(w, "Tam", 20, 20)
    cow = w.add_object("cow", 24, 20)    # 4 steps east: not yet near enough to worry a cow
    deer = w.add_object("deer", 20, 24)  # 4 steps south: a deer is already off
    Simulation(w)._animals()
    assert cow.data["state"] != "wary"
    assert deer.data["state"] == "wary" and max(abs(deer.x - c.x), abs(deer.y - c.y)) >= 6

    sheep = w.add_object("sheep", 21, 20)  # right beside: both bolt, the rabbit farther
    rabbit = w.add_object("rabbit", 19, 20)
    Simulation(w)._animals()
    gap = lambda o: max(abs(o.x - c.x), abs(o.y - c.y))  # noqa: E731
    assert gap(rabbit) > gap(sheep) >= 3


def test_wild_game_will_not_be_tamed():
    w = grass_world()
    c = creature(w)
    c.inventory["berries"] = 5
    deer = w.add_object("deer", 11, 10)
    for _ in range(3):
        res = act(w, c, action="give", target="deer", items=["berries"])
        assert not res.ok and "wild" in res.message
    assert not deer.data.get("tamed_by") and c.inventory["berries"] == 5
    res = act(w, c, action="gather", target="deer")
    assert not res.ok and "hunt" in res.message


def test_hunt_needs_a_weapon_and_yields_meat_hide_bone():
    w = grass_world()
    c = creature(w)
    deer = w.add_object("deer", 12, 10)
    res = act(w, c, action="hunt", target="deer")
    assert not res.ok and "spear" in res.message and deer.id in w.objects
    assert not any("hunt" in line for line in relevant(w, c, packs_only=True))  # no weapon: no tip

    c.inventory.update({"stick": 2, "stone_knife": 1})  # a blade lashed to a shaft
    assert act(w, c, action="combine", items=["stick", "stone knife"]).ok and c.inventory["spear"] == 1
    assert any("hunt" in line for line in relevant(w, c, packs_only=True))
    w.rng = Fixed(0.0)  # it strikes true
    res = act(w, c, action="hunt", target="deer")
    assert res.ok and deer.id not in w.objects
    assert 2 <= c.inventory["meat"] <= 3 and c.inventory["hide"] == 1 and 1 <= c.inventory["bone"] <= 2
    assert c.inventory["spear"] == 1 and c.stats["hunted"] == 1
    assert any(e.kind == "sound" and e.data["sound"] == "hunt" for e in w.events)

    boar = w.add_object("boar", 12, 11)
    w.rng = Fixed(0.99)  # a miss: the boar bolts
    res = act(w, c, action="hunt", target="boar")
    assert res.ok and "miss" in res.message and boar.id in w.objects
    assert max(abs(boar.x - c.x), abs(boar.y - c.y)) > 2 and boar.data["state"] == "wary"

    res = act(w, c, action="hunt", target="cow")
    assert not res.ok and "game" in res.message  # nothing wild by that name; livestock isn't hunted

    c.inventory["stone_knife"] = 1  # hide scraped with a knife becomes leather; leather and rope make a sling
    assert act(w, c, action="combine", items=["hide"]).ok and c.inventory["leather"] == 1
    c.inventory["rope"] = 1
    assert act(w, c, action="combine", items=["leather", "rope"]).ok and c.inventory["sling"] == 1


def test_sling_reaches_farther_and_needs_stones():
    w = grass_world()
    c = creature(w)
    c.inventory["sling"] = 1
    rabbit = w.add_object("rabbit", 14, 10)  # 4 steps: beyond a spear, within a sling
    w.rng = Fixed(0.0)
    res = act(w, c, action="hunt", target="rabbit")
    assert not res.ok and "stone" in res.message
    c.inventory["stone"] = 2
    res = act(w, c, action="hunt", target="rabbit")
    assert res.ok and rabbit.id not in w.objects and c.inventory["stone"] == 1 and c.inventory["meat"] == 1
    assert (c.x, c.y) == (10, 10)  # it never had to move


def test_a_spear_stalks_game_out_of_reach():
    w = grass_world()
    c = creature(w)
    c.inventory["spear"] = 1
    deer = w.add_object("deer", 16, 10)  # 6 steps: too far to throw
    w.rng = Fixed(0.0)
    res = act(w, c, action="hunt", target="deer")
    assert res.ok and deer.id not in w.objects and c.inventory["meat"] >= 2 and c.x > 10


def test_weapon_inventions_count():
    w = grass_world()
    c = creature(w)
    c.inventory.update({"stick": 2, "flint": 2, "rope": 2})
    w.catalog.add_invention({"id": "inv_hunting_spear", "name": "hunting spear", "desc": "for hunting", "food": 0,
                             "placeable": False, "tool": True, "inputs": {"stick": 1, "flint": 1}})
    c.inventory["inv_hunting_spear"] = 1
    w.add_object("rabbit", 12, 10)
    w.rng = Fixed(0.0)
    assert act(w, c, action="hunt").ok and c.inventory["meat"] == 1


# ------------------------------------------------------------------ foraging and placing
def test_forage_mushrooms_and_herbs():
    w = grass_world()
    c = creature(w)
    patch = w.add_object("mushroom_patch", 11, 10)
    herbs = w.add_object("herb_patch", 10, 11)
    got = Counter()
    for _ in range(3):
        before = Counter(c.inventory)
        act(w, c, action="gather", target="mushrooms")
        got += Counter(c.inventory) - before
    assert got["mushroom"] >= 2 and patch.id not in w.objects  # picked clean: it's gone
    assert act(w, c, action="gather", target="herbs").ok and c.inventory["herbs"] >= 1
    for _ in range(3):
        act(w, c, action="gather", target="herbs")
    assert herbs.kind == "herb_patch_cut"  # it grows back in time
    assert registry.LOOKS["mushroom_patch"] and registry.LOOKS["herb_patch"] and registry.LOOKS["herb_patch_cut"]


def test_fresh_world_has_game_and_forage_in_their_places():
    w = generate_world(seed=3)
    kinds = Counter(o.kind for o in w.objects.values())
    for kind in ("deer", "rabbit", "boar", "mushroom_patch", "herb_patch"):
        assert kinds[kind] >= food.population(w, kind) > 0, kind
    for o in w.objects.values():
        if o.kind in ("deer", "boar", "rabbit", "mushroom_patch", "herb_patch"):
            assert w.tile(o.x, o.y) in registry.KINDS[o.kind]["habitat"]["tiles"], o
    assert w.ext["food"]["placed"]


def test_wild_game_comes_back_after_hunting():
    w = generate_world(seed=3)
    for o in [o for o in w.objects.values() if o.kind == "deer"]:
        w.remove_object(o.id)
    sim = quiet_sim(w)
    top_up = system("food wildlife")
    top_up(sim, w.tick)
    assert 0 < sum(1 for o in w.objects.values() if o.kind == "deer") < food.population(w, "deer")


def test_food_old_save_loads(prepack_save):
    st = ServerState(seed=1)
    restore(st, prepack_save)  # populate runs with fresh=False: game and forage are placed once
    w = st.world
    assert w.ext["food"]["placed"]
    kinds = Counter(o.kind for o in w.objects.values())
    assert all(kinds[k] for k in ("deer", "rabbit", "boar", "mushroom_patch", "herb_patch"))
    for c in w.creatures.values():
        c.asleep = False
    for _ in range(200):
        st.tick_message(st.sim.tick())
    assert all(perceive(w, c) for c in w.creatures.values())
    before = Counter(o.kind for o in w.objects.values())
    registry.run_populate(w, w.rng, fresh=False)  # idempotent
    assert Counter(o.kind for o in w.objects.values()) == before
