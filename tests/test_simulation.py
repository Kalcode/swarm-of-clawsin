import pytest

from swarmworld.world.actions import Intention, apply_intention
from swarmworld.world.catalog import Catalog
from swarmworld.world.model import START_TICK, Creature, World
from swarmworld.world.simulation import Simulation


@pytest.fixture
def world():
    w = World(40, 40, [["g"] * 40 for _ in range(40)], Catalog.load())
    w.tick = START_TICK
    return w


def creature(w, name, x, y):
    c = Creature(f"c{len(w.creatures) + 1}", name, x, y, asleep=False, wake_reason=None, last_think_tick=w.tick)
    w.creatures[c.id] = c
    return c


def test_hunger_and_collapse(world):
    notes = []
    sim = Simulation(world, memory_sink=lambda c, t, i: notes.append(t))
    c = creature(world, "Tam", 20, 20)
    c.satiety, c.health = 0, 2
    c.inventory["stone"] = 3
    for _ in range(12):
        sim.tick()
    assert c.collapsed and world.ground[(20, 20)]["stone"] == 3
    for _ in range(70):
        sim.tick()
    assert not c.collapsed and c.satiety > 0 and any("collapsed" in n for n in notes)


def test_regrowth(world):
    sim = Simulation(world)
    o = world.add_object("bush_empty", 5, 5, regrow_at=world.tick + 15)
    for _ in range(25):
        sim.tick()
    assert o.kind == "bush" and o.data["berries"] == 6


def test_speech_wakes_hearers(world):
    notes = {}
    sim = Simulation(world, memory_sink=lambda c, t, i: notes.setdefault(c.name, []).append(t))
    a = creature(world, "Tam", 10, 10)
    b = creature(world, "Mara", 14, 10)
    far = creature(world, "Odo", 19, 10)
    apply_intention(world, a, Intention("say", target="Mara", text="berries to the north"))
    sim.tick()
    assert b.wake_reason == "heard"
    assert 'Tam says to you: "berries to the north"' in notes["Mara"]
    assert sim.take_heard(b) == ['Tam says to you: "berries to the north"']
    assert far.wake_reason != "heard"


def test_idle_wake(world):
    sim = Simulation(world)
    c = creature(world, "Tam", 10, 10)
    for _ in range(31):
        sim.tick()
    assert c.wake_reason == "idle"


def test_witness_learns_recipe(world):
    notes = {}
    sim = Simulation(world, memory_sink=lambda c, t, i: notes.setdefault(c.name, []).append(t))
    a = creature(world, "Tam", 10, 10)
    b = creature(world, "Mara", 12, 10)
    a.inventory.update({"stick": 1, "stone": 1, "rope": 1})
    assert apply_intention(world, a, Intention("combine", items=["stick", "stone", "rope"])).ok
    sim.tick()
    assert any("watched Tam make stone axe" in n and "rope" in n for n in notes["Mara"])
    assert "stone_axe" in b.known_recipes


def test_inspiration_is_vague_and_relevant(world):
    notes = []
    sim = Simulation(world, memory_sink=lambda c, t, i: notes.append(t))
    c = creature(world, "Tam", 10, 10)
    c.persona = {"drive": "tinkerer"}
    c.inventory.update({"log": 1, "stone_axe": 1})
    for _ in range(40):
        sim._inspire(c)
    assert notes and all("->" not in n for n in notes)
    assert any("log" in n or "stone axe" in n for n in notes)


def test_sleeping_creatures_are_in_stasis(world):
    sim = Simulation(world)
    c = creature(world, "Tam", 10, 10)
    c.asleep = True
    c.satiety = 5
    for _ in range(500):
        sim.tick()
    assert c.satiety == 5 and not c.collapsed


def test_learning_a_recipe_by_listening(world):
    notes = {}
    sim = Simulation(world, memory_sink=lambda c, t, i: notes.setdefault(c.name, []).append(t))
    a = creature(world, "Tam", 10, 10)
    b = creature(world, "Mara", 12, 10)
    apply_intention(world, a, Intention("say", target="Mara", text="Combine flint with a stick to make a stone knife!"))
    sim.tick()
    assert "stone_knife" in b.known_recipes
    assert any("understand how to make stone knife" in n for n in notes["Mara"])
    before = set(b.known_recipes)
    apply_intention(world, a, Intention("say", text="I love sticks and stones."))
    sim.tick()
    assert b.known_recipes == before  # no recipe was spelled out


def test_overlapping_creatures_separate(world):
    sim = Simulation(world)
    a = creature(world, "Tam", 10, 10)
    b = creature(world, "Mara", 10, 10)
    for _ in range(12):
        sim.tick()
    assert (a.x, a.y) != (b.x, b.y)


def test_camps_become_named_places(world):
    from swarmworld.world.perception import perceive
    sim = Simulation(world)
    world.add_object("campfire", 10, 10, lit=True, builder="Bo")
    world.add_object("workbench", 12, 11, builder="Mara")
    c = creature(world, "Tam", 20, 10)
    sim._landmarks()
    camp = next(lm for lm in world.landmarks if lm["kind"] == "camp")
    assert camp["name"] == "Bo's camp" and camp["size"] == 2
    assert "Bo's camp 10 steps west" in perceive(world, c)
    res = apply_intention(world, c, Intention("walk_to", target="Bo's camp"))
    assert res.ok and "Bo's camp" in c.activity["label"]


def test_rain_and_cold_wear_you_down_unless_warm(world):
    from swarmworld.world.perception import perceive
    sim = Simulation(world)
    out = creature(world, "Tam", 5, 5)
    warm = creature(world, "Mara", 20, 20)
    world.add_object("campfire", 21, 20, lit=True, lit_until=10**9)
    world.weather, world.weather_until = "rain", world.tick + 10**6
    assert "soaked" in perceive(world, out) and "soaked" not in perceive(world, warm)
    assert world.clock()["weather"] == "rain"
    for _ in range(300):
        sim.tick()
    assert out.energy < warm.energy - 5


def test_tired_creatures_sleep_through_the_night(world):
    from swarmworld.world.model import DAY_TICKS
    sim = Simulation(world)
    c = creature(world, "Tam", 10, 10)
    c.energy = 30
    world.tick = DAY_TICKS * 2 + int(DAY_TICKS * 0.7)  # night
    sim.tick()
    assert (c.activity or {}).get("sleep")
    sim.wake(c, "met")
    assert c.wake_reason is None  # not roused by someone walking past
    world.tick = DAY_TICKS * 3 + 10  # dawn of the next day
    for _ in range(25):
        sim.tick()
    assert not (c.activity or {}).get("sleep") and c.energy > 30
