import pytest

from swarmworld.world import model, registry
from swarmworld.world.model import DAY_TICKS, Creature
from swarmworld.world.perception import (DAY_SIGHT, DARK_SIGHT, FIRE_SIGHT, NIGHT_SIGHT, SOFT_SIGHT, carried_light,
                                         glow_light, light_range, perceive, sight_range)
from swarmworld.world.simulation import Simulation

NIGHT = DAY_TICKS * 2 + int(DAY_TICKS * 0.8)
DAY = DAY_TICKS * 2 + int(DAY_TICKS * 0.3)
LAMP = "probe_lamp"
DARK_LINE = "Down here it is pitch dark; you feel cold stone around you."


def put(w, x, y, name="Tam"):
    c = Creature(f"c{len(w.creatures) + 1}", name, x, y)
    c.asleep = False
    w.creatures[c.id] = c
    return c


@pytest.fixture
def lamp(monkeypatch):
    monkeypatch.setitem(model.LIGHT_ITEMS, LAMP, 4)
    return LAMP


def give_lamp(w, c):
    w.catalog.items.setdefault(LAMP, w.catalog.items[next(iter(w.catalog.items))])
    c.inventory[LAMP] = 1


@pytest.fixture
def lit(two_levels, lamp):
    w = two_levels(24)
    deep = put(w, 10, 60)
    top = put(w, 10, 10, "Top")
    return w, deep, top


def test_underground_is_pitch_dark_by_day_and_night(two_levels):
    w = two_levels(24)
    deep = put(w, 10, 60)
    for tick in (DAY, NIGHT):
        w.tick = tick
        assert light_range(w, deep) == DARK_SIGHT == 1
        assert DARK_LINE in perceive(w, deep)


def test_underground_time_line(two_levels):
    w = two_levels(24)
    w.tick = int(DAY_TICKS * 0.2)  # day 1, morning
    deep = put(w, 10, 60)
    assert f"Day 1; above, it's morning. {DARK_LINE}" in perceive(w, deep)


def test_carried_light_and_glow_light_the_dark(lit):
    w, deep, _ = lit
    give_lamp(w, deep)
    assert carried_light(deep) == (4, LAMP) and light_range(w, deep) == 4
    assert f"Down here it is always dark, but your {w.catalog.name(LAMP)} lights the stone around you." in perceive(w, deep)
    del deep.inventory[LAMP]
    assert carried_light(deep) == (0, None)
    with registry.sandbox():
        registry.register_kinds({"glim2": {"name": "glim", "glow": 2}, "glim1": {"name": "dim glim", "glow": 1}}, "test")
        assert glow_light(w, 10, 60) == 0
        w.add_object("glim2", 11, 60)
        assert glow_light(w, 10, 60) == 3 == SOFT_SIGHT and light_range(w, deep) == 3
        assert "a soft glow lets you see a step or two" in perceive(w, deep)
        w.remove_object(next(iter(w.objects)))
        w.add_object("glim1", 11, 60)
        assert glow_light(w, 10, 60) == 2 and light_range(w, deep) == 2
        w.add_object("campfire", 9, 60, lit=True)
        assert light_range(w, deep) == FIRE_SIGHT
        assert "firelight flickers on the stone" in perceive(w, deep)


def test_a_carried_light_helps_at_night_on_the_surface(lit):
    w, deep, top = lit
    w.tick = NIGHT
    assert light_range(w, top) == NIGHT_SIGHT
    give_lamp(w, top)
    assert light_range(w, top) == 4
    assert f"It is night, but your {w.catalog.name(LAMP)} lights the way." in perceive(w, top)
    w.tick = DAY
    assert light_range(w, top) == DAY_SIGHT


def test_underground_is_never_cold_or_wet(two_levels):
    w = two_levels(24)
    w.tick = NIGHT
    w.weather = "rain"
    deep, top = put(w, 10, 60), put(w, 10, 10, "Top")
    sim = Simulation(w)
    assert sim.exposure(deep) is None and sim.exposure(top) == "rain"
    text = perceive(w, deep)
    for word in ("cold air", "night air", "soaked", "Rain", "rain", "Fog"):
        assert word not in text.replace("cold stone", "")
    assert "soaked" in perceive(w, top)
    w.weather = "clear"
    assert sim.exposure(deep) is None and sim.exposure(top) == "cold"
    assert "night air is cold" not in perceive(w, deep)


def test_fog_stays_on_the_surface(two_levels, lamp):
    w = two_levels(24)
    w.weather = "fog"
    w.ext["weather"] = {"sight": 1}
    deep, top = put(w, 10, 60), put(w, 10, 10, "Top")
    give_lamp(w, deep)
    assert sight_range(w, deep) == 4 and sight_range(w, top) == 1
    assert "Fog" not in perceive(w, deep) and "Fog" in perceive(w, top)


def test_skylight_tiles_have_the_sky(two_levels):
    w = two_levels(24)
    w.skylight.add((10, 60))
    w.tick = DAY
    w.weather = "rain"
    lit_, dark = put(w, 10, 60), put(w, 14, 60, "Dark")
    sim = Simulation(w)
    assert light_range(w, lit_) == DAY_SIGHT and light_range(w, dark) == DARK_SIGHT
    assert "Rain is falling." in perceive(w, lit_) and sim.exposure(lit_) == "rain"
    assert "Rain" not in perceive(w, dark) and sim.exposure(dark) is None


def test_surface_light_unchanged_without_light_items(two_levels):
    w = two_levels(24)
    top = put(w, 10, 10)
    assert light_range(w, top) == DAY_SIGHT
    w.tick = NIGHT
    assert light_range(w, top) == NIGHT_SIGHT
    with registry.sandbox():
        registry.register_kinds({"glim": {"name": "glim", "glow": 2}}, "test")
        w.add_object("glim", 11, 10)
        assert light_range(w, top) == SOFT_SIGHT
    w.remove_object(next(iter(w.objects)))
    w.add_object("campfire", 11, 10, lit=True)
    assert light_range(w, top) == FIRE_SIGHT
