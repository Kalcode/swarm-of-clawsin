import pytest

from swarmworld.world.catalog import Catalog
from swarmworld.world.model import DAY_TICKS, START_TICK, Creature, World
from swarmworld.world.perception import direction, perceive, sight_range, visible_objects


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


def test_hunger_offers_seeds_only_when_nothing_better(world):
    c = add_creature(world)
    c.satiety = 30
    c.inventory.update({"wheat_seeds": 3, "berries": 2})
    text = perceive(world, c)
    assert "2 berries" in text and "wheat seeds" not in text.split("You carry food")[1].split("\n")[0]
    c.inventory.pop("berries")
    assert "3 wheat seeds" in perceive(world, c).split("You carry food")[1]


def test_remembers_resources_out_of_sight_and_forgets_gone_ones(world):
    from swarmworld.world.perception import note_spots
    c = add_creature(world)
    world.add_object("rock", 14, 10)
    bush = world.add_object("bush", 10, 14, berries=3)
    note_spots(world, c, world.tick)
    assert set(c.spots) >= {"rock", "bush"}
    c.x, c.y = 26, 26  # far away: neither is in sight
    text = perceive(world, c)
    assert "You remember:" in text and "boulder" in text.split("You remember:")[1]
    world.change_kind(bush, "bush_empty")  # picked clean while they were away
    c.x, c.y = 10, 11
    note_spots(world, c, world.tick)
    assert "bush" not in c.spots and "rock" in c.spots


NIGHT = DAY_TICKS * 2 + int(DAY_TICKS * 0.8)


def fog(w):
    from swarmworld.world.packs import weather as wx
    wx.set_weather(w, "fog", w.tick + 500)


def test_fog_by_day_is_in_the_time_line_not_a_pack_line(world):
    from swarmworld.world import registry
    from swarmworld.world.packs import weather as wx
    c = add_creature(world)
    fog(world)
    first = perceive(world, c).splitlines()[0]
    assert first.endswith("Fog hangs thick around you; you can only see a few steps.")
    assert wx._weather_line(world, c) is None and not any("Fog" in ln for ln in registry.extra_perception(world, c))


def test_fog_at_night_beside_a_fire_is_firelight_not_a_soft_glow(world):
    c = add_creature(world)
    world.tick = NIGHT
    world.add_object("campfire", 11, 10, lit=True, lit_until=world.tick + 5000)
    fog(world)
    assert sight_range(world, c) == 3  # the fog still caps how far you see
    first = perceive(world, c).splitlines()[0]
    assert "firelight" in first and "soft glow" not in first
    assert "Fog hangs thick around you; you can only see a few steps." in first


def test_fog_in_the_dark_does_not_promise_more_sight(world):
    c = add_creature(world)
    world.tick = NIGHT
    fog(world)
    first = perceive(world, c).splitlines()[0]
    assert "It is dark; you can only see a couple of steps." in first
    assert "Fog hangs thick around you." in first and "a few steps" not in first


def test_far_fireflies_are_only_the_nearest_few(world):
    c = add_creature(world, x=15, y=15)
    world.tick = NIGHT
    far = [(x, y) for y in range(7, 24) for x in range(7, 24) if max(abs(x - 15), abs(y - 15)) >= 4][:30]
    for x, y in far:
        world.add_object("firefly", x, y)
    flies = [d for o, d, _ in visible_objects(world, c) if o.kind == "firefly"]
    assert len(flies) == 3 and flies == sorted(flies)
    assert "3 fireflies" in perceive(world, c)
    world.add_object("campfire", 8, 20, lit=True, lit_until=world.tick + 5000)  # fires afar are not capped
    world.add_object("campfire", 22, 20, lit=True, lit_until=world.tick + 5000)
    assert "2 campfires (burning)" in perceive(world, c)
