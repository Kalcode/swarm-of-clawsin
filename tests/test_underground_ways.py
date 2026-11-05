"""The underground pack II (Task 8): climbing down and up, the way back always told."""

from swarmworld.world import actions, perception, registry
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
    c.energy = 80
    res = climb(w, c, "down")
    assert res.ok and res.message == "You climb down into the deep at the north cave. It is pitch dark."
    assert (c.x, c.y) == tuple(p["down"]) and w.region_at(c.x, c.y).level == -1
    assert c.energy == 79 and p["id"] in c.ext["underground"]["ways"]
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


def test_climb_down_and_climb_up_say_which_way():
    """An alias that names the way is that way: a bare "climb_up" beside a cave mouth used to climb down it."""
    from swarmworld.world.actions import parse_intention
    targets = {a: parse_intention({"action": a}).target for a in ("climb_down", "climb_up", "descend", "ascend",
                                                                  "go_down", "go_up", "climb")}
    assert targets == {"climb_down": "down", "climb_up": "up", "descend": "down", "ascend": "up", "go_down": "down",
                       "go_up": "up", "climb": ""}
    assert parse_intention({"action": "climb_up", "target": "the ladder"}).target == "the ladder"
    w, p = world_with_mouth()
    c = person(w, "Ada", UP[0] + 1, UP[1])
    res = apply_intention(w, c, parse_intention({"action": "climb_up"}))
    assert not res.ok and res.message == "You're on the surface already; this is the way down."
    assert w.region_at(c.x, c.y).level == 0
    res = apply_intention(w, c, parse_intention({"action": "climb_down"}))
    assert res.message.startswith("You climb down into the deep at the north cave.")
    finish(w, c)
    res = apply_intention(w, c, parse_intention({"action": "climb_up"}))
    assert res.message == "You climb back up to the surface at the north cave."


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


def test_walk_to_deep_water_and_up_north_stay_plain_walks():
    w, _ = world_with_mouth()
    c = person(w, "Ada", UP[0] + 1, UP[1])
    for target in ("deep water", "deep forest", "up north"):
        assert not apply_intention(w, c, Intention("walk_to", target=target)).message.startswith("You climb"), target
    assert (c.x, c.y) == (UP[0] + 1, UP[1]) or w.region_at(c.x, c.y).level == 0
    assert apply_intention(w, c, Intention("walk_to", target="deep")).message.startswith("You climb down")


def test_no_way_line_leaves_no_trace_in_ext():
    w, _ = world_with_mouth()
    c = person(w, "Ada", 3, 3)
    assert underground._way_line(w, c) is None and "underground" not in c.ext


def test_shaft_line_within_three():
    w, _ = world_with_mouth()
    up = (UP[0] - 6, UP[1])
    down = w.below(*up)
    w.set_tile(*up, "g")
    w.set_tile(*down, "c")
    underground.add_portal(w, "shaft", "the east shaft", up, down)
    c = person(w, "Ada", up[0] + 2, up[1])
    assert underground._way_line(w, c) == "A mine shaft drops into the dark 2 steps west; a ladder leads down."


# ------------------------------------------------------------------ final fix wave: which way, and ways told
UP2 = (UP[0] + 10, UP[1])  # a second cave mouth, 10 steps east of the first


def clear_around(w, x, y, tile, r=4):
    for dx in range(-r, r + 1):
        for dy in range(-r, r + 1):
            w.set_tile(x + dx, y + dy, tile)
            if (x + dx, y + dy) in w.grid:
                w.remove_object(w.grid[(x + dx, y + dy)])


def world_with_two_mouths():
    w, p = world_with_mouth()
    clear_around(w, *UP2, "g")
    clear_around(w, *w.below(*UP2), "c")
    for end in (UP, p["down"]):  # nothing that glows near either end: the dark is dark
        clear_around(w, *end, w.tile(*end))
    return w, p, underground.add_portal(w, "cave", "the east cave", UP2, w.below(*UP2))


def at_night(w):
    from swarmworld.world.model import DAY_TICKS
    w.tick = DAY_TICKS * 2 + int(DAY_TICKS * 0.8)
    assert w.clock()["phase"] == "night"


def test_leaving_the_deep_climbs_up():
    """At a cave exit, words for leaving the deep mean up ("out of", "leave", "from" the deep, underground, the caves
    below); "up" and an up-verb win over a deep word; words both ways lead away from where you are; punctuation is no
    word."""
    from swarmworld.world.actions import parse_intention
    w, p = world_with_mouth()
    cases = [("climb", "out of the deep"), ("climb", "leave the deep"), ("go_up", "out of the deep"),
             ("ascend", "from underground"), ("climb_up", "out of the caves below"),
             ("walk_to", "up to the surface from underground"), ("walk_to", "the surface, out of the deep"),
             ("ascend", "the deep"), ("climb", "the deep, up!"), ("climb", "the surface, from the deep below")]
    for verb, target in cases:
        c = person(w, "Kit", *p["down"])
        c.energy = 80
        res = apply_intention(w, c, parse_intention({"action": verb, "target": target}))
        assert res.message == "You climb back up to the surface at the north cave.", (verb, target, res.message)
        del w.creatures[c.id]
    for verb, target in [("climb", "down from the surface"), ("climb", "the deep, out of the daylight"),
                         ("descend", "the surface")]:  # on the surface, both ways: away from it, down
        c = person(w, "Kit", UP[0] + 1, UP[1])
        res = apply_intention(w, c, parse_intention({"action": verb, "target": target}))
        assert res.message.startswith("You climb down into the deep at the north cave."), (verb, target, res.message)
        del w.creatures[c.id]
    d = person(w, "Bo", *p["down"])  # still a refusal when it says down and only down
    assert climb(w, d, "down into the deep").message == "This is the way up; there is nothing deeper."
    assert parse_intention({"action": "ascend", "target": "the deep"}).said == "ascend"
    assert parse_intention({"action": "climb", "target": "x"}).said == ""


def test_a_way_told_is_a_way_known_on_the_surface():
    """At night a cave mouth 3 steps off is out of sight (2), but the way line names it: climb down and walk_to the
    cave mouth then find it."""
    w, p = world_with_mouth()
    at_night(w)
    c = person(w, "Nim", UP[0] + 3, UP[1])
    c.energy = 80
    assert perception.sight_range(w, c) == perception.NIGHT_SIGHT
    assert underground._way_line(w, c).startswith("A dark cave mouth opens 3 steps west")
    assert p["id"] in c.ext["underground"]["ways"] and c.spots["cave_mouth"][:2] == UP
    assert "the north cave" in c.landmarks_seen
    res = climb(w, c, "down")
    assert res.ok and c.activity["type"] == "walk", res.message
    finish(w, c)
    assert w.region_at(c.x, c.y).level == -1
    d = person(w, "Oda", UP[0], UP[1] + 3)
    underground._way_line(w, d)
    res = apply_intention(w, d, Intention("walk_to", target="cave mouth"))
    assert res.ok and d.activity["type"] == "walk", res.message
    finish(w, d)
    assert max(abs(d.x - UP[0]), abs(d.y - UP[1])) <= 1


def test_below_the_nearer_way_told_is_the_one_climbed():
    """Climbed down at one cave, unlit (sight 1), 3 steps from another's exit: the daylight line names that exit, and
    climb up walks there, not back to the first."""
    w, p, q = world_with_two_mouths()
    c = person(w, "Kit", UP[0] + 1, UP[1])
    c.energy = 80
    climb(w, c, "down")
    finish(w, c)
    c.x, c.y = q["down"][0] - 3, q["down"][1]
    assert perception.light_range(w, c) == perception.DARK_SIGHT
    assert underground._way_line(w, c) == "Grey daylight glimmers 3 steps east: the way up to the east cave."
    res = climb(w, c, "up")
    assert res.ok and c.activity["label"] == "heading to the way up to the east cave", res.message
    finish(w, c)
    finish(w, c)
    assert (c.x, c.y) == UP2


def test_daylight_glimmers_only_by_day():
    w, p = world_with_mouth()
    c = person(w, "Ada", p["down"][0] + 2, p["down"][1])
    assert underground._way_line(w, c) == "Grey daylight glimmers 2 steps west: the way up to the north cave."
    at_night(w)
    assert underground._way_line(w, c) == ("Night air drifts in 2 steps west: the way up to the north cave opens to "
                                           "the night sky.")


def test_far_on_the_meadow_the_deep_names_nothing():
    """The review's case: on seed 7, a creature far from the surface's terminals and the cave mouths, walking to words
    the deep's places share ("terminal", "pool", "cave", "crystal", "hall"), keeps the old answer, or for a kind the
    surface has (a terminal, a cave mouth) is told to explore for one; one that has been near the ancient terminal is
    told the way down when it names it."""
    from swarmworld.world.perception import LANDMARK_RANGE, dist
    from swarmworld.world.simulation import Simulation
    w = generate_world(7)
    Simulation(w).tick()
    surface = [lm for lm in w.landmarks if lm["y"] < w.region("surface").y1]
    terminals = [(lm["x"], lm["y"]) for lm in surface if lm["kind"] == "terminal"]
    mouths = [(lm["x"], lm["y"]) for lm in surface if lm["kind"] == "way down"]
    spots = [(x, y) for y in range(4, 124, 6) for x in range(4, 124, 6) if w.walkable(x, y) and (x, y) not in w.grid
             and all(dist(x, y, *t) > actions.LANDMARK_WALK for t in terminals)
             and all(dist(x, y, *m) > LANDMARK_RANGE for m in mouths)][:3]
    assert len(spots) == 3
    for x, y in spots:
        c = person(w, "Quill", x, y)
        for target in ("terminal", "the terminal", "pool", "the pool", "cave", "a cave", "crystal", "hall", "the hall"):
            res = apply_intention(w, c, Intention("walk_to", target=target))
            look = "around you, and you don't know where one is. Explore to find one: explore north, south, east or west."
            kind = {"terminal": "strange terminal", "the terminal": "strange terminal", "cave": "cave mouth",
                    "a cave": "cave mouth"}.get(target)  # the surface has these; the deep's crystal stays unnamed
            want = f"You don't see any {kind} {look}" if kind else f"You don't see any '{target}' around you."
            assert res.message == want, (x, y, target, res.message)
        c.landmarks_seen.add("the ancient terminal")
        res = apply_intention(w, c, Intention("walk_to", target="the ancient terminal"))
        assert res.message.startswith("The deep is below; climb down at a cave mouth or a mine shaft."), res.message
        assert apply_intention(w, c, Intention("walk_to", target="terminal")).message.startswith("You don't see any")
        del w.creatures[c.id]


def test_a_way_is_a_known_place_once_seen():
    """R24: a way's landmark joins the places a creature knows when it sees the way (within its sight), not merely
    within LANDMARK_RANGE; till then walk_to doesn't find it by name either. Other places are known as before."""
    from swarmworld.world.actions import find_landmark
    from swarmworld.world.perception import LANDMARK_RANGE, note_spots, perceive, sight_range
    from swarmworld.world.simulation import Simulation
    w, p = world_with_mouth()
    Simulation(w)._landmarks()
    meadow = next(lm for lm in w.landmarks if lm["name"] == "the meadow")
    c = person(w, "Ada", UP[0] + 10, UP[1])
    assert sight_range(w, c) < 10 <= LANDMARK_RANGE and max(abs(meadow["x"] - c.x), abs(meadow["y"] - c.y)) <= 14
    note_spots(w, c, w.tick)
    view = perceive(w, c)
    assert "the north cave" not in c.landmarks_seen and "the north cave" not in view
    places = next(line for line in view.splitlines() if line.startswith("Places you know: "))
    assert "the meadow" in c.landmarks_seen and "the meadow" in places
    assert find_landmark(w, c, "the north cave") is None and find_landmark(w, c, "cave") is None
    c.x = UP[0] + 5  # in sight
    assert "the north cave 5 steps west" in perceive(w, c) and find_landmark(w, c, "the north cave")
    note_spots(w, c, w.tick)
    assert "the north cave" in c.landmarks_seen
    c.x = UP[0] + 10
    assert "the north cave 10 steps west" in perceive(w, c)
    assert find_landmark(w, c, "the north cave")["name"] == "the north cave"
