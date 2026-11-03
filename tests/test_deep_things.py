"""The underground pack V (Task 12): coal for fires and furnaces, the crystal lamp, and the ancient terminal."""

from collections import Counter, deque

import pytest

from swarmworld.scripting.terminal import run_terminal
from swarmworld.world.actions import FUEL, Intention, apply_intention
from swarmworld.world.catalog import Catalog
from swarmworld.world.model import LIGHT_ITEMS, START_TICK, Creature, World
from swarmworld.world.packs import underground
from swarmworld.world.perception import DARK_SIGHT, light_range, perceive
from swarmworld.world.simulation import Simulation
from swarmworld.world.terrain import generate_world


def make(n=1):
    w = World(40, 40, [["g"] * 40 for _ in range(40)], Catalog.load())
    w.tick = START_TICK + 100
    for i in range(n):
        c = Creature(f"c{i + 1}", ["Ada", "Bo"][i], 10 + i, 10, asleep=False)
        w.creatures[c.id] = c
    return w


def do(w, c, action, **kw):
    return apply_intention(w, c, Intention(action, **kw))


def fed_for(item):
    w = make()
    c = w.creatures["c1"]
    fire = w.add_object("campfire", 10, 11, lit=True, lit_until=w.tick)
    c.inventory[item] = 1
    res = do(w, c, "give", target="campfire", items=[item])
    assert res.ok, res.message
    return fire.data["lit_until"] - w.tick


def test_coal_burns_longest_in_a_campfire():
    assert [fed_for(i) for i in ("coal", "charcoal", "log")] == [1800, 1200, 900]
    assert FUEL["coal"] == 1800 and FUEL["stick"] == 300


def test_coal_smelts_ore_at_a_furnace():
    w = make()
    c = w.creatures["c1"]
    w.add_object("furnace", 10, 11)
    c.inventory.update(copper_ore=1, coal=1)
    res = do(w, c, "combine", items=["copper ore", "coal"])
    assert res.ok and c.inventory == Counter(copper_ingot=1)
    c.known_recipes.add("iron_ingot")
    c.inventory.update(iron_ore=1, coal=1)
    res = do(w, c, "craft", target="iron ingot")
    assert res.ok and c.inventory == Counter(copper_ingot=1, iron_ingot=1)
    c.inventory.update(iron_ore=1, charcoal=1)  # the charcoal way still works
    assert do(w, c, "craft", target="iron ingot").ok and c.inventory["iron_ingot"] == 2
    c.inventory.clear()
    c.inventory.update(iron_ore=1)  # neither fuel: the main recipe's complaint
    assert "charcoal" in do(w, c, "craft", target="iron ingot").message


def test_alt_recipes_load_and_the_main_recipe_stays():
    cat = Catalog.load()
    for out, fuel in (("copper_ingot", "copper_ore"), ("iron_ingot", "iron_ore")):
        main, alt = cat.recipes_for(out)
        assert not main.alt and alt.alt and cat.recipe_for(out) is main
        assert main.inputs == {fuel: 1, "charcoal": 1} and alt.inputs == {fuel: 1, "coal": 1} and alt.station == "furnace"
    assert [r.alt for r in cat.recipes_for("crystal_lamp")] == [False, True]
    assert cat.recipes_for("nothing") == []


def test_an_alt_without_a_main_recipe_is_an_error(data_dir):
    root = data_dir({"odd": {"recipes": [{"output": "gizmo", "inputs": {"stick": 1}, "alt": True}]}})
    with pytest.raises(ValueError, match=r"gizmo.*packs/odd/recipes.json"):
        Catalog.load(root)


def test_crystal_lamp_from_crystal_and_basket_or_pot():
    w = make()
    c = w.creatures["c1"]
    c.inventory.update(crystal=1, basket=1)
    res = do(w, c, "combine", items=["crystal", "basket"])
    assert res.ok and c.inventory == Counter(crystal_lamp=1)
    assert "glows without burning out" in res.message
    c.inventory.clear()
    c.inventory.update(crystal=1, clay_pot=1)
    assert do(w, c, "combine", items=["crystal", "clay pot"]).ok and c.inventory == Counter(crystal_lamp=1)
    c.inventory.clear()
    c.inventory.update(crystal=1, clay_pot=1)
    assert do(w, c, "craft", target="crystal lamp").ok and c.inventory == Counter(crystal_lamp=1)
    assert w.catalog.items["crystal_lamp"].placeable and w.catalog.resolve("crystal light") == "crystal_lamp"


def deep_spot(w, run=4):
    """Open cave floor with nothing glowing near: the dark, one step of sight."""
    deep = w.region("deep")
    for y in range(deep.y0, deep.y1):
        for x in range(w.width):
            if all(w.tile(x + dx, y) == "c" and (x + dx, y) not in w.grid for dx in range(run)):
                c = Creature("probe", "Probe", x, y)
                if light_range(w, c) == DARK_SIGHT:
                    return x, y
    raise AssertionError("no dark floor")


def test_a_placed_crystal_lamp_glows_and_never_goes_out():
    from swarmworld.world.registry import KINDS
    assert KINDS["crystal_lamp"]["glow"] == 3 and not KINDS["crystal_lamp"].get("blocking")
    w = generate_world(7, 48, 48)
    x, y = deep_spot(w)
    c = Creature("c1", "Ada", x, y, asleep=False)
    w.creatures["c1"] = c
    c.inventory["crystal_lamp"] = 1
    assert do(w, c, "place", target="crystal lamp").ok and not c.inventory
    lamp = next(o for o in w.objects.values() if o.kind == "crystal_lamp")
    w.tick += 5000
    assert light_range(w, c) == 3 > DARK_SIGHT
    c.x, c.y = lamp.x + 2, lamp.y  # still within its reach
    assert max(abs(lamp.x - c.x), abs(lamp.y - c.y)) == 2 and light_range(w, c) == 3


def test_a_carried_crystal_lamp_lights_the_way():
    w = generate_world(7, 48, 48)
    x, y = deep_spot(w)
    c = Creature("c1", "Ada", x, y, asleep=False)
    w.creatures["c1"] = c
    w.add_object("rock", x + 3, y)
    assert "boulder" not in perceive(w, c)
    c.inventory["crystal_lamp"] = 1
    w.tick += 5000
    assert LIGHT_ITEMS["crystal_lamp"] == 3 and light_range(w, c) == 3 and "a boulder 3 steps east" in perceive(w, c)


def test_coal_names_the_item_not_the_seam():
    w = generate_world(7, 48, 48)
    x, y = deep_spot(w)
    c = Creature("c1", "Ada", x, y, asleep=False)
    w.creatures["c1"] = c
    assert w.catalog.resolve("coal") == "coal"
    c.inventory["coal"] = 3
    assert do(w, c, "drop", items=["coal"], count=1).ok and w.ground[(x, y)]["coal"] == 1
    assert do(w, c, "take", items=["coal"]).ok and c.inventory["coal"] == 3
    assert "coal" in do(w, c, "eat", target="coal").message.lower() and c.inventory["coal"] == 3
    w.add_object("coal_seam", x + 1, y)
    c.inventory["stone_pickaxe"] = 1
    res = do(w, c, "gather", target="coal")
    assert res.ok, res.message
    for _ in range(30):
        if c.inventory["coal"] > 3 or c.activity is None:
            break
        from swarmworld.world.actions import step_activity
        step_activity(w, c)
    assert c.inventory["coal"] > 3


def deep_with_terminal():
    w = generate_world(7)
    return w, w.ext["underground"]["terminal"]


def test_the_ancient_terminal_lies_far_from_every_way_in():
    w, t = deep_with_terminal()
    deep = w.region("deep")
    term = w.object_at(t["x"], t["y"])
    assert term.kind == "terminal" and w.region_at(term.x, term.y) is deep
    assert term.data["label"] == "ancient terminal" and term.data["code"] == "" and term.data["memory"] == {}
    assert term.data["screen"][0] == "THE ANCIENT TERMINAL HUMS IN THE DARK. ITS SCREEN GLOWS GREEN."
    assert sum(o.kind == "terminal" for o in w.objects.values() if w.region_at(o.x, o.y) is deep) == 1
    exits = [tuple(p["down"]) for p in underground.portals(w)]
    walkable = underground._walker(w)
    far = {e: 0 for e in exits}
    q = deque(exits)
    while q:
        x, y = q.popleft()
        for dx, dy in underground.STEPS:
            n = (x + dx, y + dy)
            if n not in far and walkable(*n):
                far[n] = far[(x, y)] + 1
                q.append(n)
    free = [d for (x, y), d in far.items() if (x, y) not in w.grid
            and any(walkable(x + dx, y + dy) and (x + dx, y + dy) not in w.grid for dx, dy in underground.STEPS)]
    at = 1 + min(far[n] for n in ((term.x + dx, term.y + dy) for dx, dy in underground.STEPS) if n in far)
    assert at == max(free) > 20
    again = generate_world(7)  # rolled from nothing random
    assert again.ext["underground"]["terminal"] == t


def test_the_ancient_terminal_runs_lua_like_the_others():
    w, t = deep_with_terminal()
    term = w.object_at(t["x"], t["y"])
    notes = {}
    sim = Simulation(w, memory_sink=lambda c, text, i: notes.setdefault(c.name, []).append(text), terminal_runner=run_terminal)
    spot = next((term.x + dx, term.y + dy) for dx, dy in underground.STEPS if w.walkable(term.x + dx, term.y + dy))
    below = Creature("c1", "Low", *spot, asleep=False, wake_reason=None, last_think_tick=w.tick)
    top = Creature("c2", "Top", *w.center, asleep=False, wake_reason=None, last_think_tick=w.tick)
    w.creatures.update({below.id: below, top.id: top})
    assert do(w, below, "program", target="terminal", text='say("hi")').ok
    for _ in range(3):
        sim.tick()
    assert any('The terminal says: "hi"' in n for n in notes.get("Low", []))
    assert not any("hi" in n for n in notes.get("Top", []))


def test_its_tablet_hints_at_the_surface_terminals():
    from swarmworld.world.terrain import TABLET_TEXT
    w, t = deep_with_terminal()
    tablets = [o for o in w.objects.values() if o.kind == "tablet" and w.region_at(o.x, o.y) is w.region("deep")]
    assert len(tablets) == 1 and abs(tablets[0].x - t["x"]) + abs(tablets[0].y - t["y"]) == 1
    text = tablets[0].data["text"]
    assert text.startswith("Worn letters, older than any above:") and "CAME UP FROM THE DEEP" in text
    assert "LEFT OUR MACHINES IN THE LIGHT" in text and "OBEYS LUA" in text and TABLET_TEXT != text


def test_the_ancient_terminal_is_a_landmark():
    w, t = deep_with_terminal()
    Simulation(w).tick()
    mark = next(lm for lm in w.landmarks if lm["name"] == "the ancient terminal")
    assert (mark["x"], mark["y"], mark["kind"]) == (t["x"], t["y"], "terminal")
    near = Creature("c1", "Ada", t["x"], t["y"] + 1 if w.walkable(t["x"], t["y"] + 1) else t["y"] - 1, asleep=False)
    w.creatures["c1"] = near
    assert "the ancient terminal" in perceive(w, near)
