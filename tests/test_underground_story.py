"""The whole story, end to end (Task 15): one creature on a fresh world lights a torch, goes down a cave mouth, sees by
it, mines coal and iron, digs a tunnel, finds the ancient terminal, climbs back up and digs a shaft of its own; then on
the surface digs a trench that fills from the river, fills a pit back in, and digs an open pit that lets daylight and
rain into the cave below. Driven only through apply_intention, step_activity and Simulation.tick, with the perception
text checked at each step; the three anti-goals (no weather below, no sight or sound through the ground, no surface
systems in the deep) are checked along the way. Where a walk would be long, the creature is set down on a tile that
bfs_path shows it could have walked to, as /api/admin/move does.

This is an integration test over pieces built and tested one by one; it passed on its first run. To prove it can fail,
break one link (e.g. make climb refuse) and the story stops at the climb."""

import json
from collections import Counter, deque

from swarmworld.server.persistence import restore, save
from swarmworld.server.state import ServerState
from swarmworld.world import registry
from swarmworld.world.actions import Intention, apply_intention, bfs_path, step_activity
from swarmworld.world.events import hearers
from swarmworld.world.model import DAY_TICKS, Creature
from swarmworld.world.packs import underground
from swarmworld.world.perception import (
    DAY_SIGHT,
    light_range,
    perceive,
    visible_creatures,
)
from swarmworld.world.terrain import flow_at

DEEP_KINDS = {"coal_seam", "iron_vein", "copper_vein", "crystal_cluster", "cave_mushrooms", "rock", "cave_exit",
              "terminal", "tablet", "ladder", "campfire", "lit_torch"}
SIDES = ((1, 0), (-1, 0), (0, 1), (0, -1))
EXIT = (62, 252)  # the south cave's exit, below its mouth at (62, 92)
COAL, IRON, TUNNEL = (51, 251), (50, 255), (58, 253)  # a coal seam, an iron vein, a rock wall with open floor beyond
SHAFT = (75, 89)  # rocky ground in the hills, 7+ from the meadow's heart (64, 64)
RIVER, TRENCH = (58, 79), (59, 79)  # a river tile with grass to its east: the trench runs east from the water
PIT = (77, 63)  # grass with solid rock below


def person(w, name, x, y, *items):
    c = Creature(f"c{len(w.creatures) + 1}", name, x, y, asleep=False, wake_reason=None, last_think_tick=w.tick,
                 energy=100.0,
                 persona={"initiative": "reactive", "role": "follower", "novelty": "novelty"})
    for item in items:
        c.inventory[item] += 1
    w.creatures[c.id] = c
    return c


def act(w, c, verb, target="", **kw):
    """One intention through the real verbs (aliases resolved as the parser does), run to its end."""
    res = apply_intention(w, c, Intention(registry.VERB_ALIASES.get(verb, verb), target=target, **kw))
    assert res.ok, (verb, target, res.message)
    while c.activity:
        step_activity(w, c)
    return res


def beside(w, c, x, y):
    """Set c down on a tile next to (x, y) that it could have walked to (the way /api/admin/move would)."""
    goals = {(x + dx, y + dy) for dx, dy in SIDES if w.walkable(x + dx, y + dy)}
    path = bfs_path(w, (c.x, c.y), goals, limit=20000)
    assert path is not None, f"no walk from {(c.x, c.y)} to beside {(x, y)}"
    if path:
        c.x, c.y = path[-1]


def flood(w, start):
    """Every tile walkable from start in its region."""
    seen, q = {start}, deque([start])
    while q:
        x, y = q.popleft()
        for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if n not in seen and w.walkable(*n) and w.same_region(start, n):
                seen.add(n)
                q.append(n)
    return seen


def deep_objects(w):
    deep = w.region("deep")
    return [o for o in w.objects.values() if w.region_at(o.x, o.y) is deep]


def tick_to(st, tick):
    """The simulation, tick by tick, up to tick (each message drained as the server would)."""
    while st.world.tick < tick:
        st.tick_message(st.sim.tick())


def test_the_whole_story(prepack_save, tmp_path):
    # ---- a fresh world has a connected deep with everything in it
    st = ServerState(seed=7)
    w = st.world
    deep = w.region("deep")
    assert (w.width, w.height) == (128, 288) and deep.level == -1 and not deep.sky and not deep.weather
    mouths = [p for p in underground.portals(w) if p["kind"] == "cave"]
    assert len(mouths) >= 3 and all(w.object_at(*p["up"]).kind == "cave_mouth" for p in mouths)
    assert tuple(mouths[0]["up"]) == (62, 92) and tuple(mouths[0]["down"]) == EXIT
    cave = flood(w, EXIT)
    assert all(tuple(p["down"]) in cave for p in mouths)  # one connected deep
    kinds = Counter(o.kind for o in deep_objects(w))
    assert {"coal_seam", "crystal_cluster", "cave_mushrooms", "iron_vein", "terminal"} <= set(kinds)
    assert any(w.tile(x, y) == "u" for y in range(deep.y0, deep.y1) for x in range(w.width))  # cave water
    term = w.ext["underground"]["terminal"]
    assert w.object_at(term["x"], term["y"]).data["label"] == "ancient terminal"
    assert {w.object_at(*COAL).kind, w.object_at(*IRON).kind} == {"coal_seam", "iron_vein"}
    st.tick_message(st.sim.tick())  # landmarks are named on the next tick
    assert any(lm["name"] == "the ancient terminal" for lm in w.landmarks)
    assert Counter(c for row in w.tiles[deep.y0:deep.y1] for c in row).keys() <= {"c", "u", "R"}

    # ---- an old save gains a deep on load
    old = ServerState(seed=1)
    restore(old, prepack_save)
    assert old.world.region("deep") is not None and underground.portals(old.world)
    assert old.world.height > 64

    # ---- on the surface: carry the makings, make a torch, set the fire, light the torch
    ada = person(w, "Ada", *w.center, "stick", "stick", "stick", "plant_fiber", "charcoal", "stone_pickaxe", "hoe",
                 "campfire")
    act(w, ada, "place", "campfire")
    fire = next(o for o in w.objects.values() if o.kind == "campfire")
    assert fire.data["lit"]
    res = act(w, ada, "combine", items=["stick", "plant fiber", "charcoal"])
    assert ada.inventory["torch"] == 1 and "Light it at a burning campfire" in res.message
    res = act(w, ada, "light", "torch")
    assert res.message.startswith("You light your torch at the campfire") and ada.inventory["lit_torch"] == 1

    # ---- walk to the nearest cave mouth and climb down; the torch lights the stone
    beside(w, ada, 62, 92)
    assert "A dark cave mouth opens right beside you to the south" in perceive(w, ada)
    bo = person(w, "Bo", ada.x + 1, ada.y)  # a friend on the surface, right above the cave
    res = act(w, ada, "climb", "down")
    assert res.message.startswith("You climb down into the deep at the south cave.")
    assert "pitch dark" not in res.message and (ada.x, ada.y) == EXIT
    view = perceive(w, ada)
    assert "your lit torch lights the stone around you" in view and "You stand on cave floor, by a cave exit." in view
    assert "Grey daylight glimmers right here: the way up to the south cave." in view
    assert "cave mushrooms" in view

    # ---- anti-goals: no sight or sound through the ground, no weather below
    assert visible_creatures(w, ada) == [] and visible_creatures(w, bo) == []
    assert "Bo" not in view and "Ada" not in perceive(w, bo)
    assert [h.id for h in hearers(w, ada.x, ada.y, 10)] == [ada.id]
    act(w, bo, "say", text="Ada, can you hear me?")
    st.sim._process_events()
    assert not st.sim.heard[ada.id]
    w.weather = "rain"
    assert st.sim.exposure(ada) is None and "Rain" not in perceive(w, ada) and "rain" not in perceive(w, ada).lower()
    w.weather = "clear"

    # ---- mine coal and an iron vein
    beside(w, ada, *COAL)
    assert "a coal seam right beside you" in perceive(w, ada)
    assert act(w, ada, "gather", "coal").message.startswith("You gathered") and ada.inventory["coal"] >= 1
    beside(w, ada, *IRON)
    assert "a rust-streaked rock right beside you" in perceive(w, ada)
    act(w, ada, "gather", "iron ore")
    assert ada.inventory["iron_ore"] >= 1

    # ---- dig a tunnel through a wall (two tiles of rock, open floor beyond)
    ada.x, ada.y = TUNNEL
    assert (w.tile(59, 253), w.tile(60, 253), w.tile(61, 253)) == ("R", "R", "c")
    for n in range(3):
        res = act(w, ada, "dig", "east")
    assert res.message.startswith("You break through the rock wall to the east") and w.tile(59, 253) == "c"
    assert bfs_path(w, TUNNEL, {(59, 253)}, limit=20000) == [(59, 253)]
    ada.x = 59  # a step into the new tunnel
    for n in range(3):
        res = act(w, ada, "dig", "east")
    assert w.tile(60, 253) == "c" and len(bfs_path(w, TUNNEL, {(61, 253)}, limit=20000)) == 3
    assert ada.inventory["stone"] >= 6

    # ---- walk to the ancient terminal and read it
    beside(w, ada, term["x"], term["y"])
    assert "a strange terminal" in perceive(w, ada) and "the ancient terminal" in perceive(w, ada)
    assert "THE ANCIENT TERMINAL HUMS IN THE DARK" in act(w, ada, "read", "terminal").message

    # ---- climb back up (the way is remembered)
    beside(w, ada, 62, 252)
    res = act(w, ada, "climb", "up")
    assert res.message == "You climb back up to the surface at the south cave." and w.region_at(ada.x, ada.y).name == "surface"
    assert ada.y < 128

    # ---- dig a shaft of her own on rocky ground, climb down it and up again
    assert w.tile(*SHAFT) == "r"
    beside(w, ada, *SHAFT)
    ada.x, ada.y = SHAFT
    for n in range(4):
        assert "You dig down where you stand" in act(w, ada, "dig", "down").message
    res = act(w, ada, "dig", "down")
    assert "a shaft drops into the deep, with a ladder down" in res.message
    assert w.object_at(*SHAFT).kind == "mine_shaft"
    res = act(w, ada, "climb", "down")
    assert res.message.startswith("You climb down into the deep at Ada's shaft.")
    assert w.region_at(ada.x, ada.y) is deep and "lights the stone around you" in perceive(w, ada)
    assert act(w, ada, "climb", "up").message == "You climb back up to the surface at Ada's shaft."

    # ---- a trench from the river fills with water
    assert w.tile(*RIVER) == "w" and flow_at(w, *RIVER) is not None and w.tile(60, 79) in "gdsf"
    ada.x, ada.y = TRENCH
    act(w, ada, "dig", "here")  # the tile beside the water
    ada.x = 61
    act(w, ada, "dig", "west")  # and the next one out
    assert [w.tile(x, 79) for x in (59, 60)] == ["t", "t"]
    tick_to(st, w.tick + 130)
    assert [w.tile(x, 79) for x in (59, 60)] == ["w", "t"]  # the water comes in from the river, one tile at a time
    ada.x, ada.y = 61, 79  # beside the second tile, two from the first
    tick_to(st, w.tick + 40)
    assert "Water is seeping into the trench beside you." in perceive(w, ada)
    tick_to(st, w.tick + 120)
    assert [w.tile(x, 79) for x in (59, 60)] == ["w", "w"]
    assert "A trench beside you runs full of water." in perceive(w, ada)

    # ---- fill a pit back in with dirt
    ada.x, ada.y = PIT[0] + 1, PIT[1]
    act(w, ada, "dig", "west")
    act(w, ada, "dig", "west")
    assert w.tile(*PIT) == "h"
    ada.inventory["dirt"] = max(ada.inventory["dirt"], 1)
    res = act(w, ada, "fill_in", "west")
    assert res.message.startswith("You fill the pit to the west with 1 dirt; it is a trench again.") and w.tile(*PIT) == "t"

    # ---- dig a pit through into the deep; at midday the chamber below is lit and the tile is announced
    act(w, ada, "dig", "west")
    assert w.tile(*PIT) == "h"
    st.tick_message([])  # drain earlier tile changes
    for n in range(2):
        assert "You hack at the rock to the west" in act(w, ada, "dig", "west").message
    res = act(w, ada, "dig", "west")
    assert res.message.startswith("Your pickaxe breaks through! Daylight falls into the dark below")
    assert w.tile(*PIT) == "O" and w.object_at(*PIT).kind == "open_pit"
    day_base = (w.tick // DAY_TICKS + 1) * DAY_TICKS
    w.tick = day_base + int(DAY_TICKS * 0.3) - 1
    msg = json.loads(st.tick_message(st.sim.tick()))
    assert [PIT[0], PIT[1], "O"] in msg["tiles"] and msg["clock"]["phase"] == "day"
    pit = underground.portals(w)[-1]
    assert pit["kind"] == "pit" and pit["name"] == "Ada's pit"
    ada.x, ada.y = PIT[0], PIT[1] - 1
    act(w, ada, "climb", "down")
    assert w.region_at(ada.x, ada.y) is deep
    view = perceive(w, ada)
    assert "Daylight falls through an open pit far above you." in view
    assert light_range(w, ada) == DAY_SIGHT
    w.weather = "rain"  # rain falls through the hole, and only there
    assert st.sim.exposure(ada) == "rain" and "Rain is falling." in perceive(w, ada)
    other = person(w, "Cy", ada.x + 3, ada.y)
    assert st.sim.exposure(other) is None and "Rain" not in perceive(w, other)
    w.weather = "clear"

    # ---- no surface systems took hold in the deep
    tiles = Counter(c for row in w.tiles[deep.y0:deep.y1] for c in row)
    assert tiles.keys() <= {"c", "u", "R"}
    assert set(Counter(o.kind for o in deep_objects(w))) <= DEEP_KINDS
    assert all(w.region_at(c.x, c.y).name == "surface" or c.id in (ada.id, other.id) for c in w.creatures.values())

    # ---- save, load, save: the same world
    first, second = tmp_path / "a.json", tmp_path / "b.json"
    save(st, first)
    again = ServerState(seed=3)
    restore(again, first)
    save(again, second)
    a, b = json.loads(first.read_text()), json.loads(second.read_text())
    assert a["world"] == b["world"]
    w2 = again.world
    assert w2.tile(*PIT) == "O" and underground.portals(w2) == underground.portals(w)
    assert ["".join(r) for r in w2.tiles] == ["".join(r) for r in w.tiles]
