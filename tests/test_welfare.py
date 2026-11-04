"""Welfare: starving sleepers are woken and fed, bedtime meals, seeds are not a staple."""
import pytest

from swarmworld.world.actions import step_activity
from swarmworld.world.catalog import Catalog
from swarmworld.world.model import START_TICK, Creature, World
from swarmworld.world.simulation import Simulation


@pytest.fixture
def world():
    tiles = [["g"] * 40 for _ in range(40)]
    w = World(40, 40, tiles, Catalog.load())
    w.tick = START_TICK + 100
    return w


def creature(w, x=10, y=10):
    c = Creature(f"c{len(w.creatures) + 1}", "Tam", x, y, asleep=False)
    w.creatures[c.id] = c
    return c


def sleeping(c):
    c.activity = {"type": "busy", "ticks": 10_000, "label": "sleeping", "rest": True, "sleep": True}


def test_seeds_are_worth_one():
    items = Catalog.load().items
    assert items["wheat_seeds"].food == 1 and items["carrot_seeds"].food == 1


def test_hunger_alarm_keeps_waking_a_sleeper_at_zero_every_60_ticks(world):
    sim = Simulation(world)
    c = creature(world)
    c.satiety = 0
    sleeping(c)
    sim.hunger_alert[c.id] = 0  # every alarm, level 0 included, has already fired
    for t, woken in ((119, False), (120, True), (121, False), (180, True)):
        c.wake_reason = None
        sim._needs(c, t)
        assert (c.wake_reason == "hungry") == woken, t


def test_alarm_fires_once_on_reaching_zero(world):
    sim = Simulation(world)
    c = creature(world)
    c.satiety = 0
    sleeping(c)
    sim.hunger_alert[c.id] = 5
    sim._needs(c, 7)
    assert c.wake_reason == "hungry"


def test_reflex_staggers_up_to_three_steps_and_wakes(world):
    sim = Simulation(world)
    c = creature(world)
    c.satiety = 3
    sleeping(c)
    bush = world.add_object("bush", 13, 10, berries=6)
    sim._reflex_eat(c)
    assert c.satiety > 3 and bush.data["berries"] < 6
    assert (c.x, c.y) != (10, 10) and max(abs(c.x - 13), abs(c.y - 10)) <= 1
    assert c.activity is None and c.wake_reason == "hungry"


def test_reflex_does_not_stagger_beyond_three_steps(world):
    sim = Simulation(world)
    c = creature(world)
    c.satiety = 3
    sleeping(c)
    world.add_object("bush", 15, 10, berries=6)  # 4 steps to a spot beside it
    sim._reflex_eat(c)
    assert c.satiety == 3 and (c.x, c.y) == (10, 10) and c.activity["sleep"]


def test_reflex_measures_walking_not_straight_lines(world):
    sim = Simulation(world)
    c = creature(world)
    c.satiety = 3
    for y in range(5, 16):  # a wall of water between them
        world.tiles[y][12] = "W"
    world.add_object("bush", 14, 10, berries=6)
    sim._reflex_eat(c)
    assert c.satiety == 3 and (c.x, c.y) == (10, 10)


def test_reflex_eats_a_ripe_crop_it_staggers_to(world):
    sim = Simulation(world)
    c = creature(world)
    c.satiety = 3
    world.add_object("crop", 12, 12, crop="carrot", stage=2)
    sim._reflex_eat(c)
    assert c.satiety > 3


def test_bedtime_meal_eats_to_sixty_then_sleeps(world):
    notes = []
    sim = Simulation(world, memory_sink=lambda c, t, i: notes.append(t))
    c = creature(world)
    c.satiety = 20
    world.add_object("bush", 12, 10, berries=20)
    sim._start_sleep(c, True)
    assert 60 <= c.satiety < 70 and c.activity["sleep"]
    assert notes == ["You ate before lying down."]


def test_no_bedtime_meal_when_not_hungry_or_no_food(world):
    notes = []
    sim = Simulation(world, memory_sink=lambda c, t, i: notes.append(t))
    c = creature(world)
    c.satiety = 50
    world.add_object("bush", 12, 10, berries=20)
    sim._start_sleep(c, True)
    assert c.satiety == 50 and notes == []
    d = creature(world, 30, 30)
    d.satiety = 20
    sim._start_sleep(d, True)
    assert d.satiety == 20 and notes == []


def test_bedtime_meal_food_must_be_within_four_steps(world):
    sim = Simulation(world)
    c = creature(world)
    c.satiety = 20
    world.add_object("bush", 16, 10, berries=20)  # 5 steps to reach beside it
    sim._start_sleep(c, True)
    assert c.satiety == 20


def test_starving_with_seeds_staggers_to_a_bush_and_keeps_the_seeds(world):
    sim = Simulation(world)
    c = creature(world)
    c.satiety = 2
    c.inventory.update(wheat_seeds=2)
    bush = world.add_object("bush", 13, 10, berries=6)
    sim._reflex_eat(c)
    assert c.inventory["wheat_seeds"] == 2 and bush.data["berries"] < 6 and c.satiety > 10


def test_starving_with_seeds_and_no_food_near_eats_the_seeds(world):
    sim = Simulation(world)
    c = creature(world)
    c.satiety = 2
    c.inventory.update(wheat_seeds=2)
    sim._reflex_eat(c)
    assert c.satiety == 4 and not c.inventory.get("wheat_seeds")


def test_bedtime_meal_eats_carried_food_first_without_moving(world):
    notes = []
    sim = Simulation(world, memory_sink=lambda c, t, i: notes.append(t))
    c = creature(world)
    c.satiety = 20
    c.inventory.update(berries=20)
    bush = world.add_object("bush", 13, 10, berries=6)
    sim._start_sleep(c, True)
    assert (c.x, c.y) == (10, 10) and bush.data["berries"] == 6
    assert c.satiety >= 60 and notes == ["You ate before lying down."]


def test_bedtime_meal_with_only_seeds_goes_to_the_bush(world):
    sim = Simulation(world)
    c = creature(world)
    c.satiety = 20
    c.inventory.update(wheat_seeds=5)
    bush = world.add_object("bush", 13, 10, berries=20)
    sim._start_sleep(c, True)
    assert c.inventory["wheat_seeds"] == 5 and bush.data["berries"] < 20 and c.satiety >= 60


def test_bedtime_meal_does_not_leave_a_bed(world):
    sim = Simulation(world)
    c = creature(world)
    c.satiety = 20
    world.add_object("bed", 10, 11)
    bush = world.add_object("bush", 13, 10, berries=20)
    sim._start_sleep(c, True)
    assert (c.x, c.y) == (10, 10) and bush.data["berries"] == 20 and c.activity["sleep"]


def test_ripe_wheat_is_not_food_for_the_reflex(world):
    sim = Simulation(world)
    c = creature(world)
    c.satiety = 3
    world.add_object("crop", 12, 10, crop="wheat", stage=2)
    sim._reflex_eat(c)
    assert c.satiety == 3 and (c.x, c.y) == (10, 10)


def test_ripe_crop_seeds_reach_the_pack(world):
    sim = Simulation(world)
    c = creature(world)
    c.satiety = 3
    world.add_object("crop", 11, 10, crop="carrot", stage=2)
    sim._reflex_eat(c)
    assert c.inventory.get("carrot_seeds", 0) >= 1


def test_stagger_never_lands_on_a_wall_or_a_creature(world):
    sim = Simulation(world)
    c = creature(world)
    c.satiety = 3
    other = creature(world, 12, 10)
    world.add_object("bush", 13, 10, berries=6)
    world.tiles[10][12] = "W"
    sim._reflex_eat(c)
    assert c.satiety > 3 and world.walkable(c.x, c.y) and (c.x, c.y) != (other.x, other.y)
    assert max(abs(c.x - 13), abs(c.y - 10)) <= 1
