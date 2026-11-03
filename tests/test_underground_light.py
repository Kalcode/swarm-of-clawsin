"""The underground pack III (Task 9): torches, lit at a fire, seen by below and at night, burning down to a stick."""

from collections import Counter

from swarmworld.world import registry
from swarmworld.world.actions import Intention, apply_intention, step_activity
from swarmworld.world.catalog import Catalog
from swarmworld.world.model import LIGHT_ITEMS, START_TICK, Creature, World
from swarmworld.world.packs import underground
from swarmworld.world.packs.underground import LIGHT_LINE, TORCH_TICKS
from swarmworld.world.perception import perceive
from swarmworld.world.simulation import Simulation
from swarmworld.world.terrain import generate_world

BURNED = "Your torch burned out, leaving a charred stick."


def make(n=1, fire=False):
    w = World(40, 40, [["g"] * 40 for _ in range(40)], Catalog.load())
    w.tick = START_TICK + 100
    for i in range(n):
        c = Creature(f"c{i + 1}", ["Ada", "Bo"][i], 10 + i, 10, asleep=False)
        w.creatures[c.id] = c
    if fire:
        w.add_object("campfire", 10, 11, lit=True, lit_until=w.tick + 5000)
    notes = []
    sim = Simulation(w, lambda c, text, imp: notes.append((c.id, text)))
    return w, sim, notes


def do(w, c, action, **kw):
    return apply_intention(w, c, Intention(action, **kw))


def run(w, sim, ticks):
    for _ in range(ticks // 10):
        w.tick += 10
        underground._torches(sim, w.tick)


def deep_world():
    w = generate_world(7, 48, 48)
    deep = w.region("deep")
    ys, xs = [(y, x) for y in range(deep.y0, deep.y1) for x in range(w.width)
              if all(w.tile(x + dx, y) == "c" for dx in range(0, 4))
              and not any((x + dx, y + dy) in w.grid for dx in range(-4, 8) for dy in range(-4, 5))][0]  # nothing near: dark
    return w, xs, ys


def test_torch_recipe_is_stick_fiber_and_charcoal():
    w, sim, _ = make()
    c = w.creatures["c1"]
    r = w.catalog.recipe_for("torch")
    assert r.inputs == {"stick": 1, "plant_fiber": 1, "charcoal": 1} and not r.station
    c.inventory.update(stick=1, plant_fiber=1, charcoal=1)
    res = do(w, c, "combine", items=["stick", "plant fiber", "charcoal"])
    assert res.ok and c.inventory == Counter(torch=1)
    c.inventory.update(stick=1, plant_fiber=1, stone_knife=1)
    res = do(w, c, "combine", items=["stick", "plant fiber"])
    assert res.ok and c.inventory["flute"] == 1


def test_light_a_torch_at_a_burning_campfire():
    w, sim, _ = make(fire=True)
    c = w.creatures["c1"]
    c.inventory["torch"] = 1
    res = do(w, c, "light", target="torch")
    assert res.ok and c.inventory == Counter(lit_torch=1) and c.activity["ticks"] == 2
    assert c.ext["underground"]["torch_until"] == w.tick + TORCH_TICKS
    assert do(w, c, "light").message == "Your torch is already burning."
    c.activity = None
    assert {registry.VERB_ALIASES[a] for a in ("light_torch", "kindle", "ignite")} == {"light"}


def test_light_from_a_friends_torch():
    w, sim, _ = make(n=2)
    a, b = w.creatures["c1"], w.creatures["c2"]
    a.inventory["torch"] = 1
    assert "no fire beside you" in do(w, a, "light").message
    b.inventory["lit_torch"] = 1
    res = do(w, a, "light")
    assert res.ok and a.inventory["lit_torch"] == 1 and b.inventory["lit_torch"] == 1


def test_no_fire_no_light():
    w, sim, _ = make()
    c = w.creatures["c1"]
    assert do(w, c, "light").message == "You have no torch to light. (A torch is a stick, plant fiber and charcoal.)"
    c.inventory["torch"] = 1
    assert do(w, c, "light").message == "There's no fire beside you to light it from: a burning campfire, or someone's lit torch."
    assert c.inventory == Counter(torch=1)


def test_a_torch_lights_the_deep():
    w, x, y = deep_world()
    c = Creature("c1", "Ada", x, y, asleep=False)
    w.creatures["c1"] = c
    w.add_object("rock", x + 3, y)
    assert "boulder" not in perceive(w, c)
    c.inventory["lit_torch"] = 1
    text = perceive(w, c)
    assert "lights the stone around you" in text and "a boulder 3 steps east" in text
    assert LIGHT_ITEMS["lit_torch"] == 4


def test_a_torch_lights_the_surface_at_night():
    from swarmworld.world.perception import light_range
    w, sim, _ = make()
    c = w.creatures["c1"]
    while w.clock()["phase"] != "night":
        w.tick += 1
    dark = light_range(w, c)
    c.inventory["lit_torch"] = 1
    assert light_range(w, c) == 4 > dark
    assert "your lit torch lights the way" in perceive(w, c)


def test_torch_burns_out_into_a_stick():
    w, sim, notes = make()
    c = w.creatures["c1"]
    c.inventory["torch"] = 1
    w.add_object("campfire", 10, 11, lit=True, lit_until=w.tick + 5000)
    do(w, c, "light")
    run(w, sim, TORCH_TICKS - 10)
    assert c.inventory["lit_torch"] == 1 and not notes
    run(w, sim, 10)
    assert c.inventory == Counter(stick=1) and "torch_until" not in c.ext["underground"]
    assert notes == [("c1", BURNED)]


def test_burning_out_in_the_deep_says_it_is_dark():
    w, x, y = deep_world()
    notes = []
    sim = Simulation(w, lambda c, text, imp: notes.append(text))
    c = Creature("c1", "Ada", x, y, asleep=False)
    w.creatures["c1"] = c
    c.inventory["lit_torch"] = 1
    run(w, sim, 10)
    run(w, sim, TORCH_TICKS)
    assert notes == [BURNED + " It is pitch dark."]


def test_torch_low_lines_once_each():
    w, sim, _ = make()
    c = w.creatures["c1"]
    c.inventory["lit_torch"] = 1
    run(w, sim, 10)
    lines = []
    for _ in range(TORCH_TICKS // 10):
        w.tick += 10
        underground._torches(sim, w.tick)
        for _ in range(2):
            line = underground._torch_line(w, c)
            if line:
                lines.append(line)
    assert lines == ["Your torch is burning low.", "Your torch is guttering; it will go out any moment."]


def test_torch_waits_while_its_mind_is_away():  # Review Focus 1
    w, sim, notes = make(n=2)
    a, b = w.creatures["c1"], w.creatures["c2"]
    for c in (a, b):
        c.inventory["lit_torch"] = 1
    run(w, sim, 10)
    left = a.ext["underground"]["torch_until"] - w.tick
    a.asleep = True
    b.collapsed_until = w.tick + 99999
    run(w, sim, 2000)
    assert a.inventory["lit_torch"] == 1 and b.inventory["lit_torch"] == 1 and not notes
    assert a.ext["underground"]["torch_until"] - w.tick == left
    a.asleep = False
    run(w, sim, left)
    assert a.inventory["stick"] == 1 and notes == [("c1", BURNED)]


def test_a_dropped_lit_torch_gutters_out_and_a_given_one_keeps_burning():  # Review Focus 5
    w, sim, _ = make(n=2)
    a, b = w.creatures["c1"], w.creatures["c2"]
    a.inventory["lit_torch"] = 1
    run(w, sim, 10)
    run(w, sim, 300)
    until = a.ext["underground"]["torch_until"]
    do(w, a, "give", target="Bo", items=["lit torch"])
    assert b.inventory["lit_torch"] == 1 and not a.inventory["lit_torch"]
    run(w, sim, 10)
    assert "torch_until" not in a.ext["underground"]
    assert b.ext["underground"]["torch_until"] == until  # the burn it had left goes with it
    run(w, sim, until - w.tick - 20)
    assert b.inventory["lit_torch"] == 1
    do(w, b, "drop", target="lit torch")
    assert w.ground[(b.x, b.y)]["lit_torch"] == 1
    run(w, sim, 10)
    assert w.ground[(b.x, b.y)] == Counter(stick=1) and not b.inventory["lit_torch"]
    shelf = w.add_object("shelves", 20, 20, items={"lit_torch": 2, "log": 1})
    run(w, sim, 10)
    assert shelf.data["items"] == {"stick": 2, "log": 1}


def test_a_lit_torch_given_or_picked_up_keeps_its_burn():
    """Given away nearly burnt, a torch is nearly burnt for its new holder: told it burns low, out on time; dropped and
    picked up before it gutters out, the same."""
    w, sim, notes = make(n=2)
    a, b = w.creatures["c1"], w.creatures["c2"]
    a.inventory["lit_torch"] = 1
    run(w, sim, 10)
    run(w, sim, 700)
    until = a.ext["underground"]["torch_until"]
    assert until - w.tick <= 100
    do(w, a, "give", target="Bo", items=["lit torch"])
    run(w, sim, 10)
    assert b.ext["underground"]["torch_until"] == until and "torch_until" not in a.ext["underground"]
    assert underground._torch_line(w, b) == "Your torch is burning low."
    do(w, b, "drop", target="lit torch")
    assert do(w, a, "pick_up", target="lit torch").ok and a.inventory["lit_torch"] == 1
    run(w, sim, 10)
    assert a.ext["underground"]["torch_until"] == until and "torch_until" not in b.ext["underground"]
    run(w, sim, until - w.tick)
    assert not a.inventory["lit_torch"] and a.inventory["stick"] == 1 and (a.id, BURNED) in notes


def test_a_second_lit_torch_burns_on_when_the_first_goes_out():
    """Two lit torches share one burn; when the first goes out the second starts its own at once, and never takes the
    burn a torch dropped nearby let go of."""
    w, sim, notes = make(n=2)
    a, b = w.creatures["c1"], w.creatures["c2"]
    a.inventory["lit_torch"], b.inventory["lit_torch"] = 2, 1
    run(w, sim, 10)
    run(w, sim, a.ext["underground"]["torch_until"] - w.tick)
    assert a.inventory["lit_torch"] == 1 and a.inventory["stick"] == 1
    assert a.ext["underground"]["torch_until"] == w.tick + TORCH_TICKS
    do(w, b, "drop", target="lit torch")
    run(w, sim, 10)
    assert a.ext["underground"]["torch_until"] == w.tick - 10 + TORCH_TICKS


def test_light_the_campfire_feeds_it():
    w, sim, _ = make(fire=True)
    c = w.creatures["c1"]
    fire = w.objects[w.grid[(10, 11)]]
    c.inventory["stick"] = 1
    before = fire.data["lit_until"]
    res = do(w, c, "light", target="campfire", items=["stick"])
    assert res.ok and fire.data["lit_until"] == before + 300 and not c.inventory["stick"]
    c.inventory["torch"] = 1  # with a torch in hand, it is the torch that gets lit
    assert do(w, c, "light", target="campfire").message.startswith("You light your torch")


def test_light_tip_only_with_a_torch_by_a_fire():
    w, sim, _ = make(n=2, fire=True)
    a, b = w.creatures["c1"], w.creatures["c2"]
    tip = next(t for t in registry.TECHNIQUES if t.name == "light")
    assert tip.line == LIGHT_LINE
    assert tip.trigger(w, a) is None
    a.inventory["torch"] = 1
    assert tip.trigger(w, a) == 5.6
    a.x, a.y = 30, 30
    assert tip.trigger(w, a) is None
    b.x, b.y, b.inventory["lit_torch"] = 28, 30, 1
    assert tip.trigger(w, a) == 5.6
    a.inventory["lit_torch"] = 1
    assert tip.trigger(w, a) is None


# ------------------------------------------------------------------ final fix wave: a companion's light
def lit_pair(w, y, gap=3):
    bo = Creature("c1", "Bo", 5, y, asleep=False)
    bo.inventory["lit_torch"] = 1
    ada = Creature("c2", "Ada", 5 + gap, y, asleep=False)
    for c in (bo, ada):
        w.creatures[c.id] = c
    return bo, ada


def test_below_a_companions_torch_lights_you_and_shows_its_bearer_from_afar(two_levels):
    """Below the sky, within a companion's carried light you see as far as it reaches and are told whose light it is;
    in the dark, a creature carrying a light is seen up to GLOW_SIGHT, like a fire, and named as carrying it."""
    from swarmworld.world.perception import DARK_SIGHT, GLOW_SIGHT, light_range, visible_creatures
    w = two_levels(24)
    w.tick = START_TICK + 100
    y = w.region("deep").y0 + 10
    bo, ada = lit_pair(w, y)
    assert light_range(w, ada) == 4
    text = perceive(w, ada)
    assert "Down here it is always dark, but Bo's lit torch lights the stone around you." in text
    assert "Others: Bo 3 steps west, carrying a lit torch." in text
    ada.inventory["stone_pickaxe"] = 1
    assert "Others: Ada 3 steps east, carrying a stone pickaxe." in perceive(w, bo)  # no light: as before
    bo.inventory["stone_pickaxe"] = 1
    assert "Others: Bo 3 steps west, carrying a lit torch and a stone pickaxe." in perceive(w, ada)
    ada.x = 5 + GLOW_SIGHT - 1  # beyond the torch's reach, in the dark: Bo is still seen by its light
    assert light_range(w, ada) == DARK_SIGHT
    assert [o.name for o, _, _ in visible_creatures(w, ada)] == ["Bo"]
    assert f"Others: Bo {GLOW_SIGHT - 1} steps west, carrying a lit torch and a stone pickaxe." in perceive(w, ada)
    assert visible_creatures(w, bo) == []  # Ada carries no light: out of Bo's sight
    ada.x = 5 + GLOW_SIGHT + 1
    assert visible_creatures(w, ada) == []


def test_on_the_surface_a_companions_torch_changes_nothing(two_levels):
    from swarmworld.world.perception import NIGHT_SIGHT, light_range, visible_creatures
    w = two_levels(24)
    while w.clock()["phase"] != "night":
        w.tick += 1
    bo, ada = lit_pair(w, 10, gap=2)
    assert light_range(w, ada) == NIGHT_SIGHT
    text = perceive(w, ada)
    assert "It is dark; you can only see a couple of steps." in text and "Others: Bo 2 steps west." in text
    ada.x = 12
    assert visible_creatures(w, ada) == []


def test_by_a_companions_torch_the_way_up_and_the_bearer_are_found(two_levels):
    """The review's case: Ada, unlit, 3 steps from a cave exit where Bo stands with a lit torch, climbs up and walks to
    Bo."""
    w = two_levels(24)
    up = (12, 12)
    p = underground.add_portal(w, "cave", "the north cave", up, w.below(*up))
    bo = Creature("c1", "Bo", *p["down"], asleep=False)
    bo.inventory["lit_torch"] = 1
    ada = Creature("c2", "Ada", p["down"][0] + 3, p["down"][1], asleep=False)
    for c in (bo, ada):
        w.creatures[c.id] = c
    res = do(w, ada, "climb", target="up")
    assert res.ok and ada.activity["label"] == "heading to the way up to the north cave", res.message
    ada.activity = None
    assert do(w, ada, "walk_to", target="Bo").ok
