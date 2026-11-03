"""The digging pack II (Task 11): terraforming the surface. Trenches and pits, open pits into the deep, water that
follows a trench from the river, and filling it all back in."""

from collections import Counter

import pytest

from swarmworld.mind.techniques import relevant
from swarmworld.server.persistence import restore, save
from swarmworld.server.state import ServerState
from swarmworld.world import registry
from swarmworld.world.actions import TILE_TARGETS, Intention, apply_intention, parse_intention, step_activity
from swarmworld.world.caves import chamber_tiles
from swarmworld.world.model import DAY_TICKS, Creature
from swarmworld.world.packs import digging, nature, underground
from swarmworld.world.packs.digging import (DIG_LINE, DIG_SURFACE_LINE, DIG_TICKS, FILL_LINE, FLOW_TICKS, WALL_DIGS,
                                            why_not_dig)
from swarmworld.world.perception import DAY_SIGHT, DARK_SIGHT, FEATURES, NIGHT_SIGHT, light_range, perceive
from swarmworld.world.simulation import Simulation
from swarmworld.world.terrain import flow_at, generate_world

DAY = DAY_TICKS * 2 + int(DAY_TICKS * 0.3)
NIGHT = DAY_TICKS * 2 + int(DAY_TICKS * 0.8)
P = (12, 24)  # where the open pit opens, on generate_world(7, 48, 48): 12 steps west of the meadow's heart
OPENED = "Your pickaxe breaks through! Daylight falls into the dark below: the pit opens into the deep (climb down)."
NATURAL = "Only a trench's water can be filled in; the river and the lake are too much."
NOTHING = "There's no trench or pit beside you; dirt fills holes."
EDGE = "You stand at the edge of an open pit; far below, the dark of the deep."
SIDES = ((1, 0), (-1, 0), (0, 1), (0, -1))


def person(w, name, x, y, *items, energy=80.0):
    c = Creature(f"c{len(w.creatures) + 1}", name, x, y, asleep=False, energy=energy)
    for item in items:
        c.inventory[item] += 1
    w.creatures[c.id] = c
    return c


def act(w, c, verb, target="", **kw):
    res = apply_intention(w, c, Intention(registry.VERB_ALIASES.get(verb, verb), target=target, **kw))
    while c.activity:
        step_activity(w, c)
    return res


def dig(w, c, target):
    return act(w, c, "dig", target)


def clear(w, x, y, r, tile):
    for yy in range(y - r, y + r + 1):
        for xx in range(x - r, x + r + 1):
            w.set_tile(xx, yy, tile)
            if (xx, yy) in w.grid:
                w.remove_object(w.grid[(xx, yy)])


def river_world(two_levels):
    """two_levels(24) (the meadow's heart at (12, 12)) with a river running down column 5."""
    w = two_levels(24)
    for y in range(24):
        w.set_tile(5, y, "w")
    w.take_tile_changes()
    return w


def flood(w, runs, start=0):
    """The water system, run `runs` times (every 20 ticks)."""
    sim = Simulation(w)
    for k in range(start + 1, start + runs + 1):
        digging._water(sim, 20 * k)


def pit_world():
    """generate_world(7, 48, 48) with grass around P and solid rock around the spot below it."""
    w = generate_world(7, 48, 48)
    clear(w, *P, 2, "g")
    clear(w, *w.below(*P), 3, "R")
    return w


def open_pit(w, c, dirn="west"):
    """c, standing beside the spot, digs it from grass down through to the deep; the results."""
    return [dig(w, c, dirn).message for _ in range(2 + WALL_DIGS)]


def around(view):
    return next((line for line in view.splitlines() if line.startswith("Around you: ")), "")


def test_dig_a_trench_and_a_pit_with_a_hoe(two_levels):
    w = two_levels(24)
    c = person(w, "Ada", 19, 5)
    assert dig(w, c, "here").message == "You'd need a hoe or a pickaxe to dig." and w.tile(19, 5) == "g"
    c.inventory["hoe"] = 1
    res = apply_intention(w, c, Intention("dig", target="here"))
    assert res.message == "You dig a trench here and get 1 dirt." and c.activity["ticks"] == DIG_TICKS
    while c.activity:
        step_activity(w, c)
    assert w.tile(19, 5) == "t" and w.take_tile_changes() == [[19, 5, "t"]] and w.walkable(19, 5)
    assert w.ext["digging"]["dug"] == {"19,5": "g"} and c.energy == 78 and c.stats["dug"] == 1
    assert dig(w, c, "a pit").message == "You dig the trench here down into a pit and get 1 dirt."
    assert w.tile(19, 5) == "h" and w.walkable(19, 5) and c.inventory["dirt"] == 2 and c.energy == 76
    assert dig(w, c, "here").message == "Only a pickaxe breaks through the rock under a pit."
    c.x = 18  # toward a direction: the tile on that side
    assert dig(w, c, "east").message == "Only a pickaxe breaks through the rock under a pit."
    assert dig(w, c, "trench to the west").message == "You dig a trench to the west and get 1 dirt."
    assert w.tile(17, 5) == "t" and w.tile(18, 5) == "g" and w.ext["digging"]["dug"] == {"19,5": "g", "17,5": "g"}
    c.inventory["stone_pickaxe"] = 1  # a pickaxe digs soft ground as well
    assert dig(w, c, "south").message == "You dig a trench to the south and get 1 dirt."
    c.energy = 9.9  # digging tires: under 10 a creature must rest first
    assert dig(w, c, "north").message == "You're too worn out to dig; rest first."
    assert w.tile(18, 4) == "g" and c.inventory["dirt"] == 4 and c.energy == 9.9
    assert dig(w, c, "").message != "You're too worn out to dig; rest first."  # a bare dig is still a gather


def test_rocky_ground_needs_a_pickaxe_and_three_digs(two_levels):
    w = two_levels(24)
    w.set_tile(19, 5, "r")
    w.take_tile_changes()
    a = person(w, "Ada", 18, 5, "hoe")
    assert dig(w, a, "east").message == "Rocky ground needs a pickaxe." and "digging" not in w.ext
    a.inventory["stone_pickaxe"] = 1
    res = apply_intention(w, a, Intention("dig", target="east"))
    assert res.message == "You hack at the rock to the east and get 1 stone (1 of 3)." and a.activity["ticks"] == DIG_TICKS
    while a.activity:
        step_activity(w, a)
    assert w.ext["digging"]["work"]["19,5"] == {"n": 1, "by": ["Ada"]} and w.tile(19, 5) == "r"
    b = person(w, "Bo", 20, 5, "stone_pickaxe")  # the digs are shared
    assert dig(w, b, "west").message == "You hack at the rock to the west and get 1 stone (2 of 3)."
    assert w.take_tile_changes() is None
    assert dig(w, a, "east").message == "You dig a trench to the east and get 1 stone."
    assert WALL_DIGS == 3 and w.tile(19, 5) == "t" and w.take_tile_changes() == [[19, 5, "t"]]
    assert w.ext["digging"]["work"] == {} and w.ext["digging"]["dug"] == {"19,5": "r"}
    assert (a.inventory["stone"], b.inventory["stone"], a.energy, b.energy) == (2, 1, 76, 78)
    assert dig(w, b, "west").message == "You dig the trench to the west down into a pit and get 1 dirt."
    del b.inventory["stone_pickaxe"]
    b.inventory["hoe"] = 1
    assert dig(w, b, "west").message == "Only a pickaxe breaks through the rock under a pit."


def test_dig_yields_dirt_sand_or_stone(two_levels):
    got = {}
    for tile in "gdfsr":
        w = two_levels(24)
        w.set_tile(19, 5, tile)
        c = person(w, "Ada", 18, 5, "hoe", "stone_pickaxe")
        for step in (tile, tile + "t", tile + "th"):
            was = w.tile(19, 5)
            for _ in range(WALL_DIGS):  # rock takes three digs; the rest one
                if w.tile(19, 5) == was:
                    dig(w, c, "east")
            got[step] = {k: n for k, n in c.inventory.items() if k not in ("hoe", "stone_pickaxe")}
    assert got["g"] == got["d"] == got["f"] == {"dirt": 1} and got["s"] == {"sand": 1} and got["r"] == {"stone": 3}
    assert got["gt"] == {"dirt": 2} and got["st"] == {"sand": 1, "dirt": 1} and got["rt"] == {"stone": 3, "dirt": 1}
    assert got["gth"] == {"dirt": 2, "stone": 3}  # the rock under a pit gives stone, the breakthrough too


def test_trench_from_the_river_fills_with_water(two_levels):
    w = river_world(two_levels)
    c = person(w, "Ada", 7, 10, "hoe")
    for x in (6, 7, 8):  # a trench of three tiles from the river eastward, each dug from beside it
        c.x = x + 1
        assert dig(w, c, "west").message == "You dig a trench to the west and get 1 dirt."
    dry = person(w, "Cy", 16, 16, "hoe")
    dig(w, dry, "here")  # a trench far from any water
    c.x, c.y = 7, 14
    dig(w, c, "west")
    w.add_object("sign", 6, 14)  # and one by the river with a sign set up in it
    w.take_tile_changes()
    system = next(s for s in registry.SYSTEMS if s.name == "digging water")
    assert system.every == 20 and FLOW_TICKS == 120
    bo = person(w, "Bo", 6, 11)  # beside the first tile of the trench
    assert "Water is seeping into" not in perceive(w, bo)
    flood(w, 5)  # 100 ticks
    assert w.tile(6, 10) == "t" and w.ext["digging"]["filling"] == {"6,10": 100}
    assert "Water is seeping into the trench beside you." in perceive(w, bo)
    assert "Water is seeping into" not in perceive(w, bo)  # said when it changes
    flood(w, 1, start=5)  # 120 ticks: the first tile is water, and only then does the next begin
    assert [w.tile(x, 10) for x in (6, 7, 8)] == ["w", "t", "t"] and w.take_tile_changes() == [[6, 10, "w"]]
    mine = w.ext["digging"]
    assert mine["made_water"] == {"6,10": 120} and "6,10" not in mine["dug"] and mine["filling"] == {}
    assert "A trench beside you runs full of water." in perceive(w, bo)
    bo.x, bo.y = 20, 2  # away from every trench: nothing to say, and nothing kept
    assert "trench" not in perceive(w, bo) and "digging" not in bo.ext
    bo.x, bo.y = 6, 11
    flood(w, 5, start=6)
    assert w.tile(7, 10) == "t" and mine["filling"] == {"7,10": 100}
    flood(w, 1, start=11)
    assert [w.tile(x, 10) for x in (6, 7, 8)] == ["w", "w", "t"]
    flood(w, 6, start=12)
    assert [w.tile(x, 10) for x in (6, 7, 8)] == ["w", "w", "w"]
    assert set(mine["made_water"]) == {"6,10", "7,10", "8,10"}
    assert w.tile(16, 16) == "t" and "16,16" not in mine["filling"]  # no water beside it, no water in it
    assert w.tile(6, 14) == "t" and "6,14" not in mine["filling"]  # water never fills around a thing standing there
    assert w.tile(9, 10) == "g" and w.tile(5, 10) == "w"


def test_trench_water_is_still_and_drinkable():
    w = generate_world(7, 48, 48)
    c = person(w, "Ada", 0, 0, "hoe")
    river, spot = next(((x, y), (x + dx, y + dy)) for y in range(48) for x in range(48) if flow_at(w, x, y)
                       for dx, dy in SIDES
                       if w.tile(x + dx, y + dy) in "gdsf" and why_not_dig(w, c, x + dx, y + dy, False) is None)
    c.x, c.y = spot
    dig(w, c, "here")
    flood(w, FLOW_TICKS // 20)
    assert w.tile(*spot) == "w" and f"{spot[0]},{spot[1]}" in w.ext["digging"]["made_water"]
    assert flow_at(w, *river) is not None and flow_at(w, *spot) is None  # the river flows; the trench's water is still
    w.drop_items(*spot, Counter(stick=2))
    sim = Simulation(w)
    for t in range(1, 6):
        nature.drift_step(sim, t)
    assert w.ground.get(spot) == Counter(stick=2)
    c.energy = 50
    assert act(w, c, "drink").message == "You drink cool water and feel refreshed." and c.energy == 60


def test_fill_in_raises_a_step_and_ends_as_dirt(two_levels):
    w = river_world(two_levels)
    c = person(w, "Ada", 18, 5, "hoe")
    dig(w, c, "east")
    dig(w, c, "east")
    assert w.tile(19, 5) == "h" and c.inventory["dirt"] == 2
    c.inventory["stone"] = 1
    res = apply_intention(w, c, Intention("fill_in", target="east"))
    assert res.message == "You fill the pit to the east with 1 dirt; it is a trench again." and c.activity["ticks"] == 3
    while c.activity:
        step_activity(w, c)
    assert w.tile(19, 5) == "t" and c.energy == 75 and c.inventory["dirt"] == 1  # dirt first, the stone kept
    assert act(w, c, "fill_in").message == ("You fill the trench to the east with 1 dirt; it is level ground again, "
                                            "bare dirt.")
    assert w.tile(19, 5) == "d" and "19,5" not in w.ext["digging"]["dug"] and "dirt" not in c.inventory
    assert act(w, c, "fill_in", "east").message == NOTHING and c.inventory["stone"] == 1
    c.x, c.y = 7, 10  # a trench from the river, full of water: filled with stone, the earth there is dirt
    dig(w, c, "west")
    flood(w, FLOW_TICKS // 20)
    assert w.tile(6, 10) == "w" and "dirt" in c.inventory
    del c.inventory["dirt"]
    assert act(w, c, "backfill", "west").message == ("You fill the trench's water to the west with 1 stone; it is "
                                                     "level ground again, bare dirt.")
    assert w.tile(6, 10) == "d" and w.ext["digging"]["made_water"] == {} and "stone" not in c.inventory
    dig(w, c, "here")  # standing in your own trench: "here" fills it, and with nothing to fill it with you can't
    del c.inventory["dirt"]
    assert act(w, c, "fill_in", "here").message == "You'd need dirt or stone to fill it with." and w.tile(7, 10) == "t"
    c.inventory["sand"] = 1
    assert act(w, c, "fill_in", "here").message == ("You fill the trench here with 1 sand; it is level ground again, "
                                                    "bare dirt.")
    assert w.tile(7, 10) == "d"


def test_fill_trench_goes_to_fill_in_and_pots_still_fill(two_levels):
    w = river_world(two_levels)
    c = person(w, "Ada", 9, 10, "hoe", "clay_pot")
    dig(w, c, "west")
    dig(w, c, "south")
    c.inventory["dirt"] = 1
    assert act(w, c, "fill", "the trench to the west").message.startswith("You fill the trench to the west with 1 dirt")
    assert w.tile(8, 10) == "d" and c.inventory["clay_pot"] == 1
    c.inventory["stone"] = 1
    assert act(w, c, "fill", "", items=["stone"]).message.startswith("You fill the trench to the south with 1 stone")
    assert w.tile(9, 11) == "d"
    assert parse_intention({"action": "fill_trench"}).action == "fill_in"
    assert {registry.VERB_ALIASES[a] for a in ("backfill", "fill_hole", "fill_trench", "fill_pit")} == {"fill_in"}
    c.x = 6  # beside the river: fill means the pot
    res = act(w, c, "fill", "my pot")
    assert res.message.startswith("You fill your clay pot with water at the water's edge.")
    assert c.inventory["water_pot"] == 1 and "clay_pot" not in c.inventory
    c.inventory["clay_pot"] = 1  # by a trench of water too: a pot named is the pot's
    c.inventory["dirt"] = 1
    dig(w, c, "south")
    flood(w, FLOW_TICKS // 20)
    assert w.tile(6, 11) == "w"
    res = act(w, c, "fill", "the pot at the trench")
    assert res.message.startswith("You fill your clay pot with water") and w.tile(6, 11) == "w"
    assert c.inventory["dirt"] == 2 and c.inventory["water_pot"] == 2


def test_place_dirt_fills_a_trench(two_levels):
    w = two_levels(24)
    c = person(w, "Ada", 18, 5, "hoe")
    dig(w, c, "east")
    dig(w, c, "west")
    assert act(w, c, "place", "dirt").message.startswith("You fill the trench to the east with 1 dirt")
    assert w.tile(19, 5) == "d" and c.inventory["dirt"] == 1
    c.inventory["stone"] = 1
    assert act(w, c, "place", "stone").message.startswith("You fill the trench to the west with 1 stone")
    assert w.tile(17, 5) == "d"
    c.inventory["stone"] = 1  # with no dug ground beside you, placing stone is what it always was
    assert act(w, c, "place", "stone").message == "A stone isn't something you can set down as a structure. Try drop."


def test_natural_water_cannot_be_filled_or_dug(two_levels):
    w = river_world(two_levels)
    w.set_tile(5, 11, "W")
    c = person(w, "Ada", 6, 10, "hoe", "stone_pickaxe", "dirt")
    assert dig(w, c, "west").message == "Water fills it as fast as you dig."
    assert act(w, c, "fill_in", "west").message == NATURAL
    assert act(w, c, "fill_in", "the river").message == NATURAL
    c.y = 11
    assert dig(w, c, "west").message == "Water fills it as fast as you dig."
    assert act(w, c, "fill_in", "west").message == NATURAL
    assert w.tile(5, 10) == "w" and w.tile(5, 11) == "W" and c.inventory["dirt"] == 1 and "digging" not in w.ext


def test_open_pit_lets_daylight_and_rain_into_the_deep():
    w = pit_world()
    bx, by = w.below(*P)
    c = person(w, "Ada", P[0] + 1, P[1], "stone_pickaxe")
    assert open_pit(w, c) == ["You dig a trench to the west and get 1 dirt.",
                              "You dig the trench to the west down into a pit and get 1 dirt.",
                              "You hack at the rock to the west and get 1 stone (1 of 3).",
                              "You hack at the rock to the west and get 1 stone (2 of 3).", OPENED]
    assert w.tile(*P) == "O" and not w.walkable(*P) and w.object_at(*P).kind == "open_pit"
    p = underground.portals(w)[-1]
    assert (p["kind"], p["name"], p["up"], p["down"]) == ("pit", "Ada's pit", list(P), [bx, by])
    assert w.object_at(bx, by).kind == "ladder" and len(p["chamber"]) == 21  # a chamber of radius 2
    assert w.skylight == {(bx + dx, by + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)}
    assert w.ext["digging"]["work"] == {} and w.ext["digging"]["dug"] == {f"{P[0]},{P[1]}": "g"}
    assert dig(w, c, "west").message == "That pit is open already, right down into the deep."
    w.tick = DAY
    res = act(w, c, "climb", "down")
    assert res.message == "You climb down into the deep at Ada's pit. Solid stone all around: dig your way out."
    assert (c.x, c.y) == (bx, by) and light_range(w, c) == DAY_SIGHT
    assert "Daylight falls through an open pit far above you." in perceive(w, c)
    sim = Simulation(w)
    w.weather = "rain"
    assert sim.exposure(c) == "rain" and "Rain is falling." in perceive(w, c)
    bo = person(w, "Bo", bx + 2, by)  # in the chamber, but not under the hole
    assert light_range(w, bo) == DARK_SIGHT and sim.exposure(bo) is None and "Rain" not in perceive(w, bo)
    w.weather, w.tick = "clear", NIGHT
    assert "Through an open pit far above, you can see the night sky." in perceive(w, c)
    assert light_range(w, c) == NIGHT_SIGHT
    assert act(w, c, "climb", "up").message == "You climb back up to the surface at Ada's pit."
    assert (c.x, c.y) == (P[0], P[1] - 1)  # beside the open pit


def test_the_open_pit_shows_from_above():
    w = pit_world()
    c = person(w, "Ada", P[0] + 1, P[1], "stone_pickaxe")
    open_pit(w, c)
    view = perceive(w, c)
    assert "an open pit right beside you to the west" in around(view) and EDGE in view
    bo = person(w, "Bo", P[0] + 3, P[1])
    view = perceive(w, bo)
    assert "an open pit 3 steps west" in around(view)
    assert "An open pit gapes 3 steps west; far below, the dark of the deep." in view
    cy = person(w, "Cy", P[0], P[1] + 2, "hoe")  # a trench and a pit beside it show too
    dig(w, cy, "east")
    dig(w, cy, "west")
    dig(w, cy, "west")
    view = around(perceive(w, cy))
    assert "a trench right beside you to the east" in view and "a pit right beside you to the west" in view
    assert {"t": "a trench", "h": "a pit", "O": "an open pit"}.items() <= FEATURES.items()
    assert {TILE_TARGETS[k] for k in ("trench", "ditch")} == {"t"} and TILE_TARGETS["pit"] == TILE_TARGETS["hole"] == "hO"


def test_filling_an_open_pit_closes_the_way():
    w = pit_world()
    bx, by = w.below(*P)
    c = person(w, "Ada", P[0] + 1, P[1], "stone_pickaxe")
    open_pit(w, c)
    chamber = [tuple(t) for t in underground.portals(w)[-1]["chamber"]]
    below = "Someone is down there; you can't fill the pit while they're below."
    bo = person(w, "Bo", bx, by)  # on the ladder: filling would shut them in the rock for good
    cy = person(w, "Cy", bx + 2, by)
    cy.collapsed_until = w.tick + 100
    before = (dict(c.inventory), c.energy, dict(w.grid), set(w.skylight), [dict(p) for p in underground.portals(w)])
    for who in (bo, cy):
        res = apply_intention(w, c, Intention("fill_in", target="west"))
        assert not res.ok and res.message == below and c.activity is None
        assert w.tile(*P) == "O" and before == (dict(c.inventory), c.energy, dict(w.grid), set(w.skylight),
                                                [dict(p) for p in underground.portals(w)])
        who.x, who.y = 30, 30  # out of the chamber, back on the surface
    res = act(w, c, "fill_in", "the pit to the west")
    assert res.message == "You throw 1 dirt into the open pit to the west; it is a pit again, its way into the deep closed."
    assert w.tile(*P) == "h" and w.walkable(*P) and w.object_at(*P) is None and w.object_at(bx, by) is None
    assert [p for p in underground.portals(w) if p["kind"] == "pit"] == [] and w.skylight == set()
    assert all(w.tile(*t) == "c" for t in chamber)  # the chamber stays
    assert underground.portal_near(w, c.x, c.y) is None  # no way down here now (a cave mouth is the nearest known)
    assert "Ada's pit" not in apply_intention(w, c, Intention("climb", target="down")).message
    c.activity = None
    act(w, c, "fill_in", "west")
    assert w.tile(*P) == "t"
    c.inventory["dirt"] = 1
    act(w, c, "fill_in", "west")
    assert w.tile(*P) == "d" and w.ext["digging"]["dug"] == {}
    # Two open pits side by side share sky: filling one leaves the other's daylight.
    w = pit_world()
    clear(w, P[0], P[1] - 1, 1, "g")
    c = person(w, "Ada", P[0] + 1, P[1], "stone_pickaxe")
    open_pit(w, c)
    c.y -= 1
    assert open_pit(w, c)[-1] == OPENED
    names = [p["name"] for p in underground.portals(w) if p["kind"] == "pit"]
    assert names == ["Ada's pit", "Ada's second pit"]
    second = {(bx + dx, by - 1 + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)}
    assert w.skylight == second | {(bx + dx, by + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)}
    c.y += 1
    act(w, c, "fill_in", "west")
    assert w.tile(*P) == "h" and w.skylight == second


def test_trench_and_pit_limits(two_levels):
    w = two_levels(24)  # the meadow's heart at (12, 12)
    c = person(w, "Ada", 15, 12, "hoe", "stone_pickaxe")
    assert dig(w, c, "here").message == "You dig a trench here and get 1 dirt."  # 3 from the heart: a trench may
    assert dig(w, c, "here").message == "Too near the heart of the meadow for a pit; dig farther out."
    assert w.tile(15, 12) == "t"
    c.x = 13
    assert dig(w, c, "here").message == "This is the heart of the meadow, where newcomers wake; leave it be."
    assert dig(w, c, "northeast").message == ("Dig straight north, south, east or west; you couldn't squeeze through "
                                              "a corner.")
    c.x, c.y = 19, 5
    dig(w, c, "here")
    dig(w, c, "here")
    assert w.tile(19, 5) == "h"
    before = (dict(c.inventory), c.energy)
    assert dig(w, c, "here").message == "Step aside first: the next dig breaks through under your feet."
    assert dig(w, c, "pit").message == "Step aside first: the next dig breaks through under your feet."
    assert (dict(c.inventory), c.energy) == before and w.ext["digging"].get("work", {}) == {}
    c.x = 18  # beside the pit, but no room below for a ladder: no dig is spent
    below = chamber_tiles(w, *w.below(19, 5), 2)
    for x, y in below:
        w.add_object("rock", x, y)
    assert dig(w, c, "east").message == "There's no room below for a ladder; dig your pit somewhere else."
    assert (dict(c.inventory), c.energy, w.tile(19, 5)) == (*before, "h") and w.ext["digging"].get("work", {}) == {}
    for x, y in below:
        w.remove_object(w.grid[(x, y)])
    c.x = 19
    person(w, "Bo", 20, 5)
    assert dig(w, c, "east").message == "Bo is standing there."
    w.add_object("rock", 19, 6)
    assert dig(w, c, "south").message == "The boulder is in the way."
    c.x, c.y = 6, 0
    assert dig(w, c, "north").message == "There's no ground there to dig."
    assert w.tile(19, 6) == "g" and w.tile(20, 5) == "g"


def test_dig_tip_for_irrigation_only_near_water_and_crops(two_levels):
    tips = [t for t in registry.TECHNIQUES if t.name == "dig"]
    assert len(tips) == 1 and tips[0].line == DIG_LINE and DIG_LINE.startswith(DIG_SURFACE_LINE)
    tip = tips[0]
    w = river_world(two_levels)
    w.add_object("crop", 10, 16, crop="wheat", stage=1)
    c = person(w, "Ada", 7, 16)  # 2 from the river, 3 from the crop
    assert tip.trigger(w, c) is None  # no tool
    c.inventory["hoe"] = 1
    assert tip.trigger(w, c) == 4.4 and DIG_LINE in relevant(w, c, packs_only=True)
    c.x = 8  # 3 from the river
    assert tip.trigger(w, c) is None
    c.x, c.y = 7, 12  # 4 from the crop
    assert tip.trigger(w, c) is None
    c.y = 16
    w.set_tile(7, 16, "r")  # rocky ground takes a pickaxe
    assert tip.trigger(w, c) is None
    c.inventory["stone_pickaxe"] = 1
    assert tip.trigger(w, c) == 4.4
    c.x, c.y = 18, 5  # far from water and fields: beside a trench, or a shaft under way
    assert tip.trigger(w, c) is None
    w.set_tile(19, 6, "t")
    assert tip.trigger(w, c) == 5.5
    w.set_tile(19, 6, "g")
    w.ext.setdefault("digging", {})["shafts"] = {"17,4": {"n": 1, "by": ["Bo"]}}
    assert tip.trigger(w, c) == 5.5
    del c.inventory["hoe"], c.inventory["stone_pickaxe"]
    assert tip.trigger(w, c) is None
    fill = next(t for t in registry.TECHNIQUES if t.name == "fill_in")
    assert fill.line == FILL_LINE and fill.trigger(w, c) is None
    w.set_tile(19, 6, "t")
    assert fill.trigger(w, c) is None  # nothing to fill it with
    c.inventory["sand"] = 1
    assert fill.trigger(w, c) == 5.0 and FILL_LINE in relevant(w, c, packs_only=True)
    c.x, c.y = 6, 10  # beside the river: natural water is no use
    assert fill.trigger(w, c) is None


def test_dig_down_and_dig_trench_aliases_say_where():
    w = pit_world()
    assert parse_intention({"action": "dig_down"}).target == "down"
    assert parse_intention({"action": "dig_trench"}).target == "trench"
    assert parse_intention({"action": "dig_down", "target": "here"}).target == "here"
    assert parse_intention({"action": "dig"}).target == ""
    c = person(w, "Ada", *P, "stone_pickaxe")
    res = apply_intention(w, c, parse_intention({"action": "dig_down"}))
    assert res.message == "You dig down where you stand and get 1 dirt (1 of 5)."
    c.x += 1
    res = apply_intention(w, c, parse_intention({"action": "dig_trench"}))
    assert res.message == "You dig a trench here and get 1 dirt."
    with registry.sandbox():  # the registry checks an alias_targets word is an alias, and a sandbox undoes them
        with pytest.raises(ValueError, match="aren't its aliases"):
            registry.register_verb("probe_dig", lambda *a: None, aliases=("probe_a",), alias_targets={"probe_b": "x"})
        registry.register_verb("probe_go", lambda *a: None, aliases=("probe_up",), alias_targets={"probe_up": "up"})
        assert parse_intention({"action": "probe_up"}).target == "up"
    assert "probe_up" not in registry.ALIAS_TARGETS
    assert {a: t for a, t in registry.ALIAS_TARGETS.items() if a.startswith("dig")} == {"dig_down": "down",
                                                                                        "dig_trench": "trench"}


def test_digging_survives_a_save(tmp_path):
    st = ServerState(seed=7)
    w = st.world
    pit, trench, wet, rock = (40, 64), (46, 70), (45, 70), (50, 76)
    clear(w, *pit, 2, "g")
    clear(w, *w.below(*pit), 3, "R")
    clear(w, 47, 72, 3, "g")
    w.set_tile(*wet, "w")  # a pond's edge
    clear(w, *rock, 0, "r")
    c = person(w, "Ada", pit[0] + 1, pit[1], "hoe", "stone_pickaxe")
    assert open_pit(w, c)[-1] == OPENED
    c.x, c.y = trench[0] + 1, trench[1]
    dig(w, c, "west")
    dig(w, c, "here")
    flood(w, FLOW_TICKS // 20)  # the trench beside the pond is water; the one beside it has begun to fill
    flood(w, 2, start=FLOW_TICKS // 20)
    c.x, c.y = rock[0] - 1, rock[1]
    dig(w, c, "east")
    mine = w.ext["digging"]
    assert w.tile(*trench) == "w" and mine["filling"] == {"47,70": 40} and mine["work"] == {"50,76": {"n": 1, "by": ["Ada"]}}
    path = tmp_path / "world.json"
    save(st, path)
    st2 = ServerState(seed=99)
    restore(st2, path)
    w2 = st2.world
    assert w2.tiles == w.tiles and w2.ext["digging"] == mine and w2.skylight == w.skylight and w2.skylight
    assert underground.portals(w2) == underground.portals(w)
    bx, by = w.below(*pit)
    assert w2.object_at(*pit).kind == "open_pit" and w2.object_at(bx, by).kind == "ladder"
    flood(w2, 4, start=100)  # the work goes on where it left off
    assert w2.tile(47, 70) == "w" and set(w2.ext["digging"]["made_water"]) == {"46,70", "47,70"}
