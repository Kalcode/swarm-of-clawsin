import pytest

from swarmworld.world.catalog import Catalog
from swarmworld.world.model import DAY_TICKS, START_TICK, Creature, World
from swarmworld.world.perception import direction, perceive, sight_range


@pytest.fixture
def world():
    tiles = [["g"] * 30 for _ in range(30)]
    w = World(30, 30, tiles, Catalog.load())
    w.tick = START_TICK + 200  # daytime
    return w


def add_creature(w, name="Tam", x=10, y=10, cid=None):
    c = Creature(cid or f"c{len(w.creatures) + 1}", name, x, y)
    w.creatures[c.id] = c
    return c


def test_sees_within_range(world):
    c = add_creature(world)
    world.add_object("tree", 15, 10, wood=6)
    world.add_object("rock", 18, 10)
    text = perceive(world, c)
    assert "oak tree 5 steps east" in text
    assert "boulder" not in text


def test_night_shrinks_sight(world):
    c = add_creature(world)
    world.add_object("tree", 14, 10, wood=6)
    world.tick = DAY_TICKS * 2 + int(DAY_TICKS * 0.8)  # night
    assert sight_range(world, c) == 2
    assert "oak tree" not in perceive(world, c)
    world.add_object("campfire", 11, 11, lit=True)
    assert sight_range(world, c) == 5
    assert "oak tree 4 steps east" in perceive(world, c)


def test_lists_inventory_and_hearing(world):
    c = add_creature(world)
    c.inventory.update({"stick": 3, "stone_axe": 1})
    other = add_creature(world, "Mara", 12, 10)
    other.inventory["stone_pickaxe"] = 1
    text = perceive(world, c, heard=['Mara says to you: "Got any stone?"'])
    assert "3 stick" in text and "1 stone axe" in text
    assert 'Mara says to you: "Got any stone?"' in text
    assert "Mara 2 steps east" in text and "stone pickaxe" in text


def test_relative_directions():
    assert direction(0, -3) == "north"
    assert direction(2, 2) == "southeast"
    assert direction(-1, 0) == "west"
    assert direction(0, 0) == "here"
