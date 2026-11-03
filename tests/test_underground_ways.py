"""The underground pack II (Task 8): climbing down and up, the way back always told."""

from swarmworld.world import actions, registry
from swarmworld.world.actions import Intention, apply_intention, step_activity
from swarmworld.world.model import LIGHT_ITEMS, Creature
from swarmworld.world.packs import underground
from swarmworld.world.packs.underground import CLIMB_LINE
from swarmworld.world.terrain import generate_world

UP = (24, 24)  # the cave mouth, always on grass-free ground we make walkable


def person(w, name, x, y):
    c = Creature(f"c{len(w.creatures) + 1}", name, x, y, asleep=False)
    w.creatures[c.id] = c
    return c


def world_with_mouth():
    """A 48x48 world with one cave mouth placed explicitly (R14), clear floor around both ends."""
    w = generate_world(7, 48, 48)
    for p in list(underground.portals(w)):
        underground.remove_portal(w, p["id"])
    for dx in range(-3, 4):
        for dy in range(-3, 4):
            x, y = UP[0] + dx, UP[1] + dy
            w.set_tile(x, y, "g")
            if (x, y) in w.grid:
                w.remove_object(w.grid[(x, y)])
    down = w.below(*UP)
    for dx in range(-3, 4):
        for dy in range(-3, 4):
            w.set_tile(down[0] + dx, down[1] + dy, "c")
            if (down[0] + dx, down[1] + dy) in w.grid:
                w.remove_object(w.grid[(down[0] + dx, down[1] + dy)])
    p = underground.add_portal(w, "cave", "the north cave", UP, down)
    return w, p


def finish(w, c):
    while c.activity:
        step_activity(w, c)


def climb(w, c, target=""):
    return apply_intention(w, c, Intention("climb", target=target))


def test_climb_down_and_back_up():
    w, p = world_with_mouth()
    c = person(w, "Ada", UP[0] + 1, UP[1])
    res = climb(w, c, "down")
    assert res.ok and res.message == "You climb down into the deep at the north cave. It is pitch dark."
    assert (c.x, c.y) == tuple(p["down"]) and w.region_at(c.x, c.y).level == -1
    assert c.energy <= 99 and p["id"] in c.ext["underground"]["ways"]
    assert c.activity["ticks"] == 4
    finish(w, c)
    res = climb(w, c, "")  # none: the way the end beside you goes
    assert res.message == "You climb back up to the surface at the north cave."
    assert (c.x, c.y) == UP


def test_climb_walks_to_a_way_in_sight_first():
    w, p = world_with_mouth()
    c = person(w, "Ada", UP[0] + 3, UP[1] + 3)
    res = climb(w, c, "down")
    assert res.ok and c.activity["type"] == "walk" and c.activity["then"].action == "climb"
    finish(w, c)
    assert w.region_at(c.x, c.y).level == -1 and (c.x, c.y) == tuple(p["down"])


def test_climb_remembers_a_way_out_of_sight():
    w, p = world_with_mouth()
    c = person(w, "Ada", UP[0] + 1, UP[1])
    climb(w, c, "down")
    finish(w, c)
    c.x, c.y = p["down"][0] + 3, p["down"][1] + 3
    res = climb(w, c, "up")
    assert res.ok and c.activity["type"] == "walk"
    finish(w, c)
    assert w.region_at(c.x, c.y).level == 0


def test_no_way_known():
    w, _ = world_with_mouth()
    c = person(w, "Ada", 3, 3)
    assert climb(w, c, "down").message.startswith("You don't know a way down. Cave mouths open in the rocky hills")
    d = person(w, "Bo", 5, w.region("deep").y0 + 40)
    w.set_tile(d.x, d.y, "c")
    assert climb(w, d, "up").message == ("You don't know a way up from here. Look for a cave exit or a ladder, or dig "
                                         "your way.")


def test_climbing_the_wrong_way_is_refused():
    w, p = world_with_mouth()
    c = person(w, "Ada", UP[0] + 1, UP[1])
    res = climb(w, c, "up")
    assert not res.ok and res.message == "You're on the surface already; this is the way down."
    assert w.region_at(c.x, c.y).level == 0
    d = person(w, "Bo", p["down"][0] + 1, p["down"][1])
    res = climb(w, d, "down")
    assert not res.ok and res.message == "This is the way up; there is nothing deeper."


def test_climbing_into_a_crowd_steps_beside_it():
    w, p = world_with_mouth()
    dx, dy = p["down"]
    person(w, "Bo", dx, dy)
    c = person(w, "Ada", UP[0] + 1, UP[1])
    res = climb(w, c, "down")
    assert res.ok and max(abs(c.x - dx), abs(c.y - dy)) == 1 and w.region_at(c.x, c.y).level == -1
    # everything within 2 of the other end is taken: told, and stays
    w2, p2 = world_with_mouth()
    dx, dy = p2["down"]
    for ox in range(-2, 3):
        for oy in range(-2, 3):
            person(w2, f"N{ox}{oy}", dx + ox, dy + oy)
    e = person(w2, "Ada", UP[0] + 1, UP[1])
    res = climb(w2, e, "down")
    assert not res.ok and res.message == "Someone is in the way at the other end; you wait."
    assert (e.x, e.y) == (UP[0] + 1, UP[1])


def test_walk_to_the_deep_climbs():
    w, p = world_with_mouth()
    c = person(w, "Ada", UP[0] + 1, UP[1])
    res = apply_intention(w, c, Intention("walk_to", target="the deep"))
    assert res.message.startswith("You climb down into the deep")
    # on the surface, "surface" stays a plain walk (R15); below it climbs
    d = person(w, "Bo", UP[0], UP[1] + 1)
    assert not apply_intention(w, d, Intention("walk_to", target="outside")).message.startswith("You climb")
    f = person(w, "Cy", p["down"][0] + 1, p["down"][1])
    assert apply_intention(w, f, Intention("walk_to", target="the surface")).message.startswith("You climb back up")


def test_way_to_region_names_the_nearest_known_way():
    w, p = world_with_mouth()
    deep = w.region("deep")
    c = person(w, "Ada", UP[0] + 5, UP[1])
    plain = actions.way_to_region(w, c, deep)
    assert plain.startswith("The deep is below; climb down at a cave mouth or a mine shaft.")
    assert "nearest way you know: the north cave, about 5 steps west" in plain
    far = person(w, "Bo", 3, 3)
    assert actions.way_to_region(w, far, deep) == "The deep is below; climb down at a cave mouth or a mine shaft."
    d = person(w, "Cy", p["down"][0] + 2, p["down"][1])
    d.ext["underground"] = {"ways": [p["id"]]}
    assert actions.way_to_region(w, d, w.region("surface")) == (
        "The surface is above; climb up at a cave exit or a ladder. The nearest way you know: the way up to the north "
        "cave, about 2 steps west.")


def test_cave_mouth_line_and_torch_hint(monkeypatch):
    w, _ = world_with_mouth()
    c = person(w, "Ada", UP[0] + 3, UP[1])
    c.wake_reason = None
    line = underground._way_line(w, c)
    assert line == ("A dark cave mouth opens 3 steps west; cool air breathes out of it. Inside it is pitch dark: a torch "
                    "(a stick, plant fiber and charcoal) would light the way.")
    assert underground._way_line(w, c) is None  # said once
    c.wake_reason = "woke"
    assert underground._way_line(w, c) == line
    c.wake_reason = None
    monkeypatch.setitem(LIGHT_ITEMS, "probe_lamp", 4)
    c.inventory["probe_lamp"] = 1
    c.x = UP[0] + 2
    assert underground._way_line(w, c) == "A dark cave mouth opens 2 steps west; cool air breathes out of it."


def test_the_way_back_line_below():
    w, p = world_with_mouth()
    dx, dy = p["down"]
    c = person(w, "Ada", dx + 2, dy)
    assert underground._way_line(w, c) == "Grey daylight glimmers 2 steps west: the way up to the north cave."
    c.x, c.y = dx + 3, dy + 3
    c.inventory.clear()
    far = person(w, "Bo", 40, w.region("deep").y0 + 40)
    assert underground._way_line(w, far) == "You don't know a way up from here."
    far.ext["underground"]["ways"] = [p["id"]]
    assert underground._way_line(w, far).startswith("The nearest way up you know: the way up to the north cave, about ")


def test_climb_tip_only_beside_a_way():
    w, _ = world_with_mouth()
    c = person(w, "Ada", UP[0] + 1, UP[1])
    near = [t for t in registry.TECHNIQUES if t.name == "climb"][0]
    assert near.line == CLIMB_LINE and near.trigger(w, c) == 6.4
    c.x = UP[0] + 4
    assert near.trigger(w, c) is None
