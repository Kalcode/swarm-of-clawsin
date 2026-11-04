import random

import pytest

from swarmworld.world.actions import Intention, apply_intention, step_activity
from swarmworld.world.catalog import Catalog
from swarmworld.world.model import DAY_TICKS, START_TICK, Creature, World
from swarmworld.world.perception import perceive
from swarmworld.world.simulation import Simulation


@pytest.fixture
def world():
    w = World(40, 40, [["g"] * 40 for _ in range(40)], Catalog.load())
    w.tick = START_TICK + 100  # morning
    w.rng = random.Random(3)
    return w


def creature(w, name="Mara", x=10, y=10):
    c = Creature(f"c{len(w.creatures) + 1}", name, x, y, asleep=False, wake_reason=None, last_think_tick=w.tick)
    w.creatures[c.id] = c
    return c


def tame(a, owner="Mara", home=None):
    a.data.update(tamed_by=owner, home=list(home or (a.x, a.y)), ready_at=0, hunger=10)


def run(sim, ticks):
    for _ in range(ticks):
        sim.tick()


def test_graze_lowers_hunger_on_grass(world):
    sheep = world.add_object("sheep", 20, 20, hunger=80)
    run(Simulation(world), 40)
    assert sheep.data["state"] == "graze" and sheep.data["hunger"] < 80


def test_wild_animal_keeps_away_from_creature(world):
    c = creature(world, "Tam", 20, 20)
    hen = world.add_object("chicken", 22, 20)
    run(Simulation(world), 4)
    assert max(abs(hen.x - c.x), abs(hen.y - c.y)) >= 3 and hen.data["state"] == "wary"


def test_wild_animal_bolts_when_adjacent(world):
    c = creature(world, "Tam", 20, 20)
    cow = world.add_object("cow", 21, 20)
    Simulation(world)._animals()
    assert max(abs(cow.x - c.x), abs(cow.y - c.y)) >= 3


def test_wild_animal_does_not_flee_who_fed_it(world):
    c = creature(world, "Tam", 20, 20)
    c.inventory["wheat_seeds"] = 2
    hen = world.add_object("chicken", 21, 20)
    assert apply_intention(world, c, Intention("give", target="chicken", items=["wheat_seeds"])).ok
    run(Simulation(world), 8)
    assert hen.data.get("state") != "wary"


def test_tamed_follows_owner_with_food(world):
    owner = creature(world, "Mara", 20, 20)
    owner.inventory["wheat_seeds"] = 3
    sheep = world.add_object("sheep", 20, 15)
    tame(sheep, home=(20, 15))
    sim = Simulation(world)
    for _ in range(12):
        owner.x += 1  # walk away slowly
        run(sim, 4)
    d = max(abs(sheep.x - owner.x), abs(sheep.y - owner.y))
    assert sheep.data["state"] == "follow" and d <= 2


def test_tamed_ignores_owner_without_food(world):
    owner = creature(world, "Mara", 20, 20)
    sheep = world.add_object("sheep", 20, 17)
    tame(sheep, home=(20, 17))
    run(Simulation(world), 60)
    assert sheep.data["state"] != "follow"
    assert max(abs(sheep.x - 20), abs(sheep.y - 17)) <= 3


def test_tamed_drifts_home(world):
    sheep = world.add_object("sheep", 20, 20)
    tame(sheep, home=(20, 15))
    run(Simulation(world), 120)
    assert max(abs(sheep.x - 20), abs(sheep.y - 15)) <= 3


def test_leading_far_relocates_home(world):
    owner = creature(world, "Mara", 10, 10)
    owner.inventory["wheat"] = 1
    sheep = world.add_object("sheep", 10, 12)
    tame(sheep, home=(10, 12))
    sim = Simulation(world)
    for _ in range(14):
        owner.x += 1
        run(sim, 4)
    assert sheep.data["state"] == "follow"
    owner.inventory.clear()
    owner.x = 38
    run(sim, 16)
    assert abs(sheep.data["home"][0] - 10) > 6
    assert max(abs(sheep.data["home"][0] - sheep.x), abs(sheep.data["home"][1] - sheep.y)) <= 3


def test_hungry_animals_do_not_produce(world):
    c = creature(world, "Mara", 10, 10)
    hen = world.add_object("chicken", 11, 10)
    tame(hen)
    hen.data["hunger"] = 90
    res = apply_intention(world, c, Intention("gather", target="chicken"))
    assert not res.ok and not c.inventory.get("egg")


def test_fed_animal_produces_and_feeding_lowers_hunger(world):
    c = creature(world, "Mara", 10, 10)
    c.inventory["wheat"] = 1
    hen = world.add_object("chicken", 11, 10)
    tame(hen)
    hen.data["hunger"] = 90
    apply_intention(world, c, Intention("give", target="chicken", items=["wheat"]))
    assert hen.data["hunger"] < 50
    res = apply_intention(world, c, Intention("gather", target="chicken"))
    while c.activity:
        step_activity(world, c)
    assert c.inventory["egg"] == 1, res.message


def _pair(world, kind="sheep"):
    a = world.add_object(kind, 20, 20)
    b = world.add_object(kind, 21, 20)
    for o in (a, b):
        tame(o, home=(20, 20))
    return a, b


def test_breeding_within_a_day_inherits_owner_and_home(world):
    _pair(world)
    run(Simulation(world), DAY_TICKS // 2)
    sheep = [o for o in world.objects.values() if o.kind == "sheep"]
    assert len(sheep) == 3
    assert all(o.data["tamed_by"] == "Mara" and o.data["home"] == [20, 20] for o in sheep)


def test_breeding_respects_cap(world):
    for i in range(12):
        o = world.add_object("sheep", 5 + i, 5)
        tame(o, home=(5 + i, 5))
    run(Simulation(world), DAY_TICKS)
    assert sum(1 for o in world.objects.values() if o.kind == "sheep") == 12


def test_hungry_animals_do_not_breed(world):
    a, b = _pair(world)
    sim = Simulation(world)
    for _ in range(40):
        for o in (a, b):
            o.data["hunger"] = 95
        sim.tick()
    assert sum(1 for o in world.objects.values() if o.kind == "sheep") == 2


def test_perception_mentions_state(world):
    c = creature(world, "Mara", 20, 20)
    sheep = world.add_object("sheep", 22, 20)
    sheep.data["state"] = "graze"
    assert "sheep grazing" in perceive(world, c)
    sheep.data.update(tamed_by="Mara", state="follow")
    assert "following Mara" in perceive(world, c)
    sheep.data.update(tamed_by=None, state="wary")
    assert "edging away from you" in perceive(world, c)


def test_old_save_animal_without_fields_works(world):
    sheep = world.add_object("sheep", 20, 20, tamed_by="Mara", home=[20, 20], ready_at=0, fed=2)
    wild = world.add_object("cow", 30, 30)
    run(Simulation(world), 20)
    assert "hunger" in sheep.data and "hunger" in wild.data and sheep.data["state"]


def test_animals_rest_at_night_bunched_together(world):
    world.tick = DAY_TICKS * 3 // 4
    a = world.add_object("sheep", 20, 20)
    b = world.add_object("sheep", 24, 20)
    run(Simulation(world), 80)
    assert a.data["state"] == "rest" and max(abs(a.x - b.x), abs(a.y - b.y)) <= 2


def test_ready_timer_pauses_while_hungry(world):
    hen = world.add_object("chicken", 20, 20)
    tame(hen)
    hen.data.update(hunger=90, ready_at=world.tick + 20)
    sim = Simulation(world)
    for _ in range(100):
        hen.data["hunger"] = 90  # kept hungry (no grazing)
        sim.tick()
    assert hen.data["ready_at"] > world.tick  # not ready though the original time passed
    hen.data["hunger"] = 0
    assert world.tick < hen.data["ready_at"]


def test_hunger_does_not_grow_while_resting_at_night(world):
    world.tick = DAY_TICKS * 3 // 4
    sheep = world.add_object("sheep", 20, 20, hunger=30)
    run(Simulation(world), 100)
    assert sheep.data["state"] == "rest" and sheep.data["hunger"] == 30


def dirt(world, x0, y0, x1, y1):
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            world.tiles[y][x] = "d"


def test_animal_on_dirt_heads_to_grass_and_eats(world):
    dirt(world, 16, 16, 24, 24)  # the nearest grass is 5 tiles away
    sheep = world.add_object("sheep", 20, 20, hunger=60)
    sim = Simulation(world)
    reached = False
    for _ in range(DAY_TICKS // 4):
        run(sim, 4)
        reached = reached or world.tile(sheep.x, sheep.y) in "gf"
    assert reached and sheep.data["hunger"] < 60


def test_grazing_feeds_only_on_grass_but_never_freezes(world):
    dirt(world, 0, 0, 39, 39)  # no grass anywhere
    sheep = world.add_object("sheep", 20, 20, hunger=30)
    sim = Simulation(world)
    spots = set()
    for _ in range(60):
        run(sim, 4)
        spots.add((sheep.x, sheep.y))
    assert len(spots) > 1 and sheep.data["hunger"] > 30


def test_plant_fiber_feeds_but_does_not_lure(world):
    owner = creature(world, "Mara", 20, 20)
    owner.inventory["plant_fiber"] = 3
    sheep = world.add_object("sheep", 20, 17)
    tame(sheep, home=(20, 17))
    sim = Simulation(world)
    for _ in range(12):
        owner.x += 1
        run(sim, 4)
    assert sheep.data["state"] != "follow"
    owner.x, owner.y = sheep.x + 1, sheep.y
    sheep.data["hunger"] = 80
    res = apply_intention(world, owner, Intention("give", target="sheep", items=["plant_fiber"]))
    assert res.ok and sheep.data["hunger"] == 20


def test_an_animal_turning_food_down_says_what_it_eats(world):
    # Opal offered rope to "Mika's cow" 14 times: "The Mika's cow sniffs the rope and turns away."
    opal = creature(world, "Opal")
    opal.inventory["rope"] = 1
    world.add_object("cow", 11, 10, label="Mika's cow")
    res = apply_intention(world, opal, Intention("give", target="cow", items=["rope"]))
    assert not res.ok and res.message.startswith("Mika's cow sniffs the rope and turns away.")
    assert "wheat, seeds, berries, carrots or plant fiber" in res.message
    opal.inventory["berries"] = 2
    res = apply_intention(world, opal, Intention("give", target="cow", items=["rope"]))
    assert "Your berries might tempt it." in res.message
    world.add_object("sheep", 9, 10)
    res = apply_intention(world, opal, Intention("give", target="sheep", items=["rope"]))
    assert res.message.startswith("The sheep sniffs the rope")
