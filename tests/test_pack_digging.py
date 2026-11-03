"""The digging pack I (Task 10): tunnels through the deep's rock and shafts of your own; dig clay still gathers."""

from swarmworld.mind.techniques import relevant
from swarmworld.world import registry
from swarmworld.world.actions import Intention, apply_intention, parse_intention, step_activity
from swarmworld.world.caves import BORDER
from swarmworld.world.model import Creature
from swarmworld.world.packs import underground
from swarmworld.world.packs.digging import DIG_LINE, DIG_TICKS, SHAFT_DIGS, WALL_DIGS, why_not_dig
from swarmworld.world.perception import dist
from swarmworld.world.terrain import generate_world

SPOT = (12, 24)  # on generate_world(7, 48, 48): 12 steps west of the meadow's heart
PLACEHOLDER = "You can only dig down here, with a pickaxe."  # surface digging comes with Task 11


def person(w, name, x, y, *tools, energy=80.0):
    c = Creature(f"c{len(w.creatures) + 1}", name, x, y, asleep=False, energy=energy)
    for t in tools:
        c.inventory[t] += 1
    w.creatures[c.id] = c
    return c


def dig(w, c, target=""):
    res = apply_intention(w, c, Intention("dig", target=target))
    while c.activity:
        step_activity(w, c)
    return res


def rocky_deep(two_levels):
    """two_levels(24) (the deep is rows 56-79) with rock along the deep's edges, BORDER thick, and a wall of rock at
    x >= 12: a creature at (11, 66) has rock to its east."""
    w = two_levels(24)
    deep = w.region("deep")
    for y in range(deep.y0, deep.y1):
        for x in range(w.width):
            edge = x < BORDER or x >= w.width - BORDER or y < deep.y0 + BORDER or y >= deep.y1 - BORDER
            if edge or x >= 12:
                w.set_tile(x, y, "R")
    w.take_tile_changes()
    return w


def clear(w, x, y, r, tile):
    for yy in range(y - r, y + r + 1):
        for xx in range(x - r, x + r + 1):
            w.set_tile(xx, yy, tile)
            if (xx, yy) in w.grid:
                w.remove_object(w.grid[(xx, yy)])


def shaft_world():
    """generate_world(7, 48, 48) with grass around SPOT and solid rock around the spot below it."""
    w = generate_world(7, 48, 48)
    clear(w, *SPOT, 1, "g")
    clear(w, *w.below(*SPOT), 2, "R")
    return w


def outcome(w, c, res):
    return res.ok, res.message, dict(c.inventory), sorted((o.kind, o.x, o.y, tuple(sorted(o.data.items())))
                                                          for o in w.objects.values())


def test_dig_clay_still_gathers_clay(two_levels):
    seen = []
    for verb, target, tools in (("gather", "clay", ()), ("dig", "clay", ()), ("dig", "clay", ("stone_pickaxe",))):
        w = two_levels(24)
        w.add_object("clay", 6, 5)
        c = person(w, "Ada", 5, 5, *tools)
        res = apply_intention(w, c, Intention(verb, target=target))
        c.inventory.pop("stone_pickaxe", None)
        seen.append(outcome(w, c, res))
    assert seen[0] == seen[1] == seen[2] and seen[0][2] == {"clay": 3}
    sand = []
    for verb in ("gather", "dig"):
        w = two_levels(24)
        w.set_tile(6, 5, "s")
        c = person(w, "Ada", 5, 5, "hoe")
        sand.append(outcome(w, c, apply_intention(w, c, Intention(verb, target="sand"))))
    assert sand[0] == sand[1] and sand[0][2] == {"hoe": 1, "sand": 1}
    far = []  # a clay bank in sight but out of reach: "dig clay" walks there to gather, as before
    for verb in ("gather", "dig"):
        w = two_levels(24)
        w.add_object("clay", 9, 5)
        c = person(w, "Ada", 5, 5, "stone_pickaxe")
        res = apply_intention(w, c, Intention(verb, target="clay"))
        far.append((outcome(w, c, res), c.activity["type"], c.activity["path"], c.activity["then"].target))
        while c.activity:
            step_activity(w, c)
        far.append(c.inventory["clay"])
    assert far[0] == far[2] and far[0][1] == "walk" and far[1] == far[3] == 3
    w = two_levels(24)  # a direction digs: the clay bank east of you isn't named
    w.add_object("clay", 6, 5)
    c = person(w, "Ada", 5, 5, "stone_pickaxe")
    assert dig(w, c, "east").message == PLACEHOLDER and "clay" not in c.inventory


def test_bare_dig_without_a_tool_still_gathers(two_levels):
    seen = []
    for verb, kind, tools in (("gather", "bush", ()), ("dig", "bush", ()),
                              ("gather", "rock", ("stone_pickaxe",)), ("dig", "rock", ("stone_pickaxe",))):
        w = two_levels(24)
        w.add_object(kind, 6, 5)
        c = person(w, "Ada", 5, 5, *tools)
        seen.append(outcome(w, c, apply_intention(w, c, Intention(verb))))
    assert seen[0] == seen[1] and seen[0][2] == {"berries": 3}
    assert seen[2] == seen[3] and seen[2][2]["stone"] >= 1  # on the surface a bare dig gathers, whatever you carry
    w = two_levels(24)  # it takes a word for where to dig
    w.add_object("rock", 6, 5)
    c = person(w, "Ada", 5, 5, "stone_pickaxe")
    assert dig(w, c, "here").message == PLACEHOLDER and "stone" not in c.inventory


def test_dig_a_thing_on_the_surface_is_gather_at_any_distance(two_levels):
    for target, kind in (("boulder", "rock"), ("the clay bank", "clay"), ("tree", "tree"), ("berry bush", None),
                         ("the boulder to the east", "rock")):
        seen = []
        for verb in ("gather", "dig"):
            w = two_levels(24)
            if kind:
                w.add_object(kind, 10, 5)
            c = person(w, "Ada", 5, 5, "stone_pickaxe")
            res = apply_intention(w, c, Intention(verb, target=target))
            act = c.activity or {}
            seen.append((outcome(w, c, res), act.get("type"), act.get("path")))
            while c.activity:
                step_activity(w, c)
            seen.append(dict(c.inventory))
        assert seen[0] == seen[2] and seen[1] == seen[3], target
        assert (seen[0][1] == "walk") == bool(kind), target  # walked 5 steps to it, or found none, as gather did


def test_mine_still_gathers_ore(two_levels):
    assert registry.VERB_ALIASES["mine"] == "gather" and "dig" in registry.VERBS and "dig" not in registry.VERB_ALIASES
    assert parse_intention({"action": "mine", "target": "iron"}).action == "gather"
    assert {registry.VERB_ALIASES[a] for a in ("tunnel", "excavate", "dig_down", "dig_tunnel", "dig_trench")} == {"dig"}
    seen = []
    for raw in ({"action": "mine", "target": "iron"}, {"action": "dig", "target": "iron"}):
        w = two_levels(24)
        w.add_object("iron_vein", 6, 5)
        c = person(w, "Ada", 5, 5, "stone_pickaxe")
        seen.append(outcome(w, c, apply_intention(w, c, parse_intention(raw))))
    assert seen[0] == seen[1] and seen[0][2]["iron_ore"] == 1
    w = rocky_deep(two_levels)  # below too: a named seam is mined, not tunnelled into
    w.add_object("coal_seam", 11, 65)
    c = person(w, "Ada", 11, 66, "stone_pickaxe")
    res = dig(w, c, "coal")
    assert res.message.startswith("You gathered ") and c.inventory["coal"] >= 1 and w.tile(12, 66) == "R"


def test_dig_a_tunnel_through_rock(two_levels):
    w = rocky_deep(two_levels)
    c = person(w, "Ada", 11, 66, "stone_pickaxe")
    res = apply_intention(w, c, Intention("dig", target="east"))
    assert res.message == "You chip at the rock wall to the east and get 1 stone. It is giving way (1 of 3)."
    assert c.activity["ticks"] == DIG_TICKS and w.ext["digging"]["work"]["12,66"] == {"n": 1, "by": ["Ada"]}
    while c.activity:
        step_activity(w, c)
    assert dig(w, c, "the rock wall to the east").message.endswith("It is giving way (2 of 3).")
    assert w.tile(12, 66) == "R" and w.take_tile_changes() is None
    assert dig(w, c, "east").message == "You break through the rock wall to the east and get 1 stone."
    assert WALL_DIGS == 3 and c.inventory["stone"] == 3 and w.tile(12, 66) == "c" and w.walkable(12, 66)
    assert w.take_tile_changes() == [[12, 66, "c"]] and w.ext["digging"]["work"] == {}
    c.x, c.y = 11, 64  # no direction: the first rock wall beside you
    w.add_object("rock", 10, 64)  # a boulder in reach: "the rock wall" still means the wall
    assert dig(w, c).message == "You chip at the rock wall to the east and get 1 stone. It is giving way (1 of 3)."
    assert dig(w, c, "rock wall").message.endswith("(2 of 3).") and w.object_at(10, 64).data.get("stone") is None
    before = dict(w.ext["digging"]["work"])  # the rock to the northeast: no tunnel squeezes through a corner
    assert dig(w, c, "northeast").message == ("Dig straight north, south, east or west; you couldn't squeeze through "
                                              "a corner.")
    assert w.tile(12, 63) == "R" and w.ext["digging"]["work"] == before and c.inventory["stone"] == 5


def test_breaking_a_wall_by_a_seam_gives_its_coal(two_levels):
    w = rocky_deep(two_levels)
    for x, y, kind in ((12, 65, "coal_seam"), (12, 67, "iron_vein"), (11, 65, "copper_vein")):
        w.set_tile(x, y, "c")
        w.add_object(kind, x, y)  # a coal seam and an iron vein touch the wall at (12, 66); the copper only its corner
    c = person(w, "Ada", 11, 66, "stone_pickaxe")
    for _ in range(WALL_DIGS - 1):
        assert "stone." in dig(w, c, "east").message
    res = dig(w, c, "east")
    assert res.message == "You break through the rock wall to the east and get 1 stone, 1 iron ore, 1 coal."
    assert [c.inventory[i] for i in ("stone", "iron_ore", "coal", "copper_ore")] == [3, 1, 1, 0]


def test_no_digging_the_deeps_border(two_levels):
    w = rocky_deep(two_levels)
    deep = w.region("deep")
    c = person(w, "Ada", BORDER, 66, "stone_pickaxe")
    assert dig(w, c, "west").message == "The rock here is too thick to dig through."
    w.set_tile(BORDER, 66, "R")  # the first column inside the border is still too near the edge
    c.x = BORDER + 1
    assert dig(w, c, "west").message == "The rock here is too thick to dig through."
    w.set_tile(BORDER + 1, 66, "R")
    c.x = BORDER + 2
    assert dig(w, c, "west").message.startswith("You chip at the rock wall to the west")
    c.x, c.y = 6, deep.y0 + BORDER
    assert dig(w, c, "north").message == "The rock here is too thick to dig through."
    c.x, c.y = 6, deep.y1 - BORDER - 1
    assert dig(w, c, "south").message == "The rock here is too thick to dig through."
    assert c.inventory["stone"] == 1 and list(w.ext["digging"]["work"]) == [f"{BORDER + 1},66"]


def test_dig_needs_a_pickaxe_below(two_levels):
    w = rocky_deep(two_levels)
    c = person(w, "Ada", 11, 66)
    bare = "The rock is too hard for bare hands; you'd need a pickaxe."
    assert dig(w, c, "east").message == bare
    assert dig(w, c).message == bare  # a bare dig below is no gather
    assert w.tile(12, 66) == "R" and not c.inventory and "digging" not in w.ext
    c.inventory["stone_pickaxe"] = 1
    assert dig(w, c, "down").message == "There is nothing deeper than the deep."
    floor = "Under the dust the cave floor is solid rock; dig into a wall instead."
    assert dig(w, c, "west").message == floor and dig(w, c, "here").message == floor
    c.x = 6  # nothing but floor around
    assert dig(w, c).message == floor
    w.set_tile(7, 66, "u")
    assert dig(w, c, "east").message == "Water fills it as fast as you dig."
    assert c.inventory == {"stone_pickaxe": 1} and "digging" not in w.ext


def test_dig_down_sinks_a_shaft_with_a_ladder_below():
    w = shaft_world()
    bx, by = w.below(*SPOT)
    c = person(w, "Ada", *SPOT, "stone_pickaxe")
    res = apply_intention(w, c, Intention("dig", target="down"))
    assert res.message == "You dig down where you stand and get 1 dirt (1 of 5)." and c.activity["ticks"] == DIG_TICKS
    assert w.ext["digging"]["shafts"]["12,24"] == {"n": 1, "by": ["Ada"]}
    while c.activity:
        step_activity(w, c)
    for n in range(2, SHAFT_DIGS):
        assert dig(w, c, "a shaft").message == f"You dig down where you stand and get 1 dirt ({n} of 5)."
    assert underground.portal_near(w, *SPOT) is None and w.tile(bx, by) == "R"
    assert dig(w, c, "down").message == ("The ground gives way beneath your pickaxe: a shaft drops into the deep, "
                                         "with a ladder down (climb down).")
    assert SHAFT_DIGS == 5 and c.inventory["dirt"] == 5 and w.ext["digging"]["shafts"] == {}
    assert w.object_at(*SPOT).kind == "mine_shaft" and w.object_at(bx, by).kind == "ladder"
    p = underground.portals(w)[-1]
    assert (p["kind"], p["name"], p["up"], p["down"]) == ("shaft", "Ada's shaft", list(SPOT), [bx, by])
    assert all(w.tile(bx + dx, by + dy) == "c" for dx in (-1, 0, 1) for dy in (-1, 0, 1))  # a chamber of radius 1
    ring = [(bx + dx, by + dy) for dx in range(-2, 3) for dy in range(-2, 3) if max(abs(dx), abs(dy)) == 2]
    assert all(w.tile(*q) == "R" for q in ring)  # sealed in the rock
    res = apply_intention(w, c, Intention("climb", target="down"))
    assert res.message == ("You climb down into the deep at Ada's shaft. It is pitch dark. Solid stone all around: "
                           "dig your way out.")
    assert (c.x, c.y) == (bx, by)
    # On rocky ground each dig gives stone; a ladder steps aside from a thing below; a shaft into a cave is open.
    up = (36, 24)
    clear(w, *up, 1, "r")
    down = w.below(*up)
    clear(w, *down, 3, "c")
    w.add_object("rock", *down)
    b = person(w, "Bo", *up, "stone_pickaxe")
    assert dig(w, b, "down").message == "You dig down where you stand and get 1 stone (1 of 5)."
    for _ in range(SHAFT_DIGS - 1):
        dig(w, b, "down")
    assert b.inventory["stone"] == 5 and w.object_at(down[0], down[1] - 1).kind == "ladder"
    assert apply_intention(w, b, Intention("climb", target="down")).message == (
        "You climb down into the deep at Bo's shaft. It is pitch dark.")


def sink(w, c):
    for _ in range(SHAFT_DIGS):
        res = dig(w, c, "down")
    return res


def test_a_shaft_chamber_is_sealed_only_while_it_opens_onto_nothing_more():
    w = shaft_world()  # sealed: the chamber is all the open ground there is (the main shaft test climbs into it)
    bx, by = w.below(*SPOT)
    a = person(w, "Ada", *SPOT, "stone_pickaxe")
    sink(w, a)
    p = underground.portals(w)[-1]
    assert sorted(map(tuple, p["chamber"])) == sorted((bx + dx, by + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1))
    assert underground._sealed(w, p, (bx, by))
    up = (36, 24)  # a small natural pocket of two tiles just past the chamber's edge: not sealed any more
    clear(w, *up, 1, "g")
    down = w.below(*up)
    clear(w, *down, 4, "R")
    w.set_tile(down[0] + 2, down[1], "c")
    w.set_tile(down[0] + 3, down[1], "c")
    b = person(w, "Bo", *up, "stone_pickaxe")
    sink(w, b)
    assert apply_intention(w, b, Intention("climb", target="down")).message == (
        "You climb down into the deep at Bo's shaft. It is pitch dark.")
    w.set_tile(bx - 2, by, "c")  # Ada digs her way out of hers: no longer sealed
    assert not underground._sealed(w, p, (bx, by))


def test_no_room_below_for_a_ladder_wastes_no_dig():
    w = shaft_world()
    bx, by = w.below(*SPOT)
    c = person(w, "Ada", *SPOT, "stone_pickaxe")
    for _ in range(SHAFT_DIGS - 1):
        dig(w, c, "down")
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            w.add_object("rock", bx + dx, by + dy)
    w.take_tile_changes()
    res = dig(w, c, "down")
    assert not res.ok and res.message == "There's no room below for a ladder; dig your shaft somewhere else."
    assert w.ext["digging"]["shafts"]["12,24"] == {"n": 4, "by": ["Ada"]} and c.inventory["dirt"] == 4
    assert c.energy == 80 - 2 * 4 and c.stats["dug"] == 4
    assert w.tile(bx, by) == "R" and w.take_tile_changes() is None and underground.portal_near(w, *SPOT) is None
    w.remove_object(w.grid[(bx + 1, by + 1)])
    assert dig(w, c, "down").message.startswith("The ground gives way beneath your pickaxe")
    assert w.object_at(bx + 1, by + 1).kind == "ladder"


def test_a_second_shaft_gets_an_ordinal():
    w = shaft_world()
    c = person(w, "Ada", *SPOT, "stone_pickaxe")
    sink(w, c)
    for x in (36, 30):
        clear(w, x, 36, 1, "g")
        clear(w, *w.below(x, 36), 2, "R")
        c.x, c.y = x, 36
        sink(w, c)
    names = [p["name"] for p in underground.portals(w) if p["kind"] == "shaft"]
    assert names == ["Ada's shaft", "Ada's second shaft", "Ada's third shaft"]
    assert {"Ada's shaft", "Ada's second shaft", "the way up to Ada's third shaft"} <= {
        lm["name"] for lm in underground._places(w)}


def test_the_underground_populates_after_food_and_nature():
    """digging.py imports the underground pack inside a function: imported at its top, it would register the
    underground pack (its populate too) ahead of food and nature, and a fresh world would be populated differently."""
    order = [p.name for p in registry.POPULATE]
    assert order.index("underground") > max(order.index("food game and forage"), order.index("nature"))


def test_shaft_limits():
    w = generate_world(7, 48, 48)
    cx, cy = w.center
    clear(w, *SPOT, 2, "g")
    c = person(w, "Ada", *SPOT, "stone_pickaxe")
    assert why_not_dig(w, c, *SPOT, True) is None  # its own tile: only an object there counts, not the digger
    w.add_object("clay", *SPOT)
    assert why_not_dig(w, c, *SPOT, False) == "The clay bank is in the way."
    w.remove_object(w.grid[SPOT])
    clear(w, 30, 34, 3, "g")
    w.ext["building"] = {"built": {"b1": {"x0": 29, "y0": 33, "x1": 31, "y1": 34, "door": [30, 34]}},
                         "sites": {"o99": {"x0": 6, "y0": 34, "x1": 7, "y1": 35, "door": None}}}
    clear(w, 6, 34, 1, "g")
    inside = "You can't dig inside a building."
    assert why_not_dig(w, c, 30, 33, False) == inside and why_not_dig(w, c, 30, 35, False) == inside  # doorstep
    assert why_not_dig(w, c, 7, 35, False) == inside and why_not_dig(w, c, 32, 33, False) is None
    clear(w, 38, 12, 1, "g")
    w.add_object("terminal", 38, 12)
    assert why_not_dig(w, c, 39, 13, False) == "The ground by the strange terminal is packed too hard to dig."
    stone = next(o for o in w.objects.values() if o.kind == "wishing_stone")
    beside = next((stone.x + dx, stone.y + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                  if (stone.x + dx, stone.y + dy) not in w.grid)
    assert why_not_dig(w, c, *beside, False) == "The ground by the wishing stone is packed too hard to dig."
    near = next((cx + dx, cy + 2) for dx in range(-2, 3) if (cx + dx, cy + 2) not in w.grid
                and dist(cx + dx, cy + 2, stone.x, stone.y) > 1)
    assert why_not_dig(w, c, *near, False) == "This is the heart of the meadow, where newcomers wake; leave it be."
    clear(w, cx + 6, cy, 0, "g")
    assert why_not_dig(w, c, cx + 6, cy, True) == "Too near the heart of the meadow for a pit; dig farther out."
    assert why_not_dig(w, c, cx + 6, cy, False) is None  # a trench may come that near
    clear(w, cx + 7, cy, 0, "g")
    assert why_not_dig(w, c, cx + 7, cy, True) is None
    wet = next((x, y) for y in range(48) for x in range(48) if w.tile(x, y) in "wW" and (x, y) not in w.grid)
    assert why_not_dig(w, c, *wet, False) == "Water fills it as fast as you dig."
    person(w, "Bo", SPOT[0] + 1, SPOT[1])
    assert why_not_dig(w, c, SPOT[0] + 1, SPOT[1], False) == "Bo is standing there."
    for x in (BORDER, w.width - 1 - BORDER):
        clear(w, x, 24, 0, "g")
        assert why_not_dig(w, c, x, 24, True) == "The rock below is too thick here."
        assert why_not_dig(w, c, x, 24, False) is None
    clear(w, BORDER + 1, 24, 0, "g")
    assert why_not_dig(w, c, BORDER + 1, 24, True) is None
    c.x, c.y = cx + 6, cy  # through the verb: refused, and no work is counted
    assert dig(w, c, "down").message == "Too near the heart of the meadow for a pit; dig farther out."
    del c.inventory["stone_pickaxe"]
    c.x, c.y = SPOT
    assert dig(w, c, "down").message == "Digging down into the deep takes a pickaxe."
    assert "digging" not in w.ext and c.inventory.get("dirt") is None


def test_two_diggers_share_the_work(two_levels):
    w = rocky_deep(two_levels)
    w.set_tile(13, 66, "c")  # a pocket on the far side of the wall at (12, 66)
    a = person(w, "Ada", 11, 66, "stone_pickaxe")
    b = person(w, "Bo", 13, 66, "stone_pickaxe")
    dig(w, a, "east")
    dig(w, a, "east")
    assert w.ext["digging"]["work"]["12,66"] == {"n": 2, "by": ["Ada"]}
    assert dig(w, b, "west").message == "You break through the rock wall to the west and get 1 stone."
    assert (a.inventory["stone"], b.inventory["stone"], w.tile(12, 66)) == (2, 1, "c")
    assert (a.stats["dug"], b.stats["dug"]) == (2, 1)
    assert w.events[-1].kind == "dig" and w.events[-1].text == "Ada and Bo broke through the rock wall."
    w = shaft_world()
    a = person(w, "Ada", *SPOT, "stone_pickaxe")
    b = person(w, "Bo", *SPOT, "stone_pickaxe")
    assert dig(w, b, "down").message == "Ada is standing there."
    b.x += 2
    dig(w, a, "down")
    dig(w, a, "down")
    a.x -= 2
    b.x -= 2
    assert dig(w, b, "down").message == "You dig down where you stand and get 1 dirt (3 of 5)."
    dig(w, b, "down")
    assert w.ext["digging"]["shafts"]["12,24"] == {"n": 4, "by": ["Ada", "Bo"]}
    b.x += 1
    a.x += 2
    assert dig(w, a, "down").message.startswith("The ground gives way beneath your pickaxe")
    assert (a.inventory["dirt"], b.inventory["dirt"]) == (3, 2) and underground.portals(w)[-1]["name"] == "Ada's shaft"
    done = next(e for e in reversed(w.events) if e.kind == "place")
    assert done.text == "Ada and Bo dug a mine shaft down into the deep."


def test_digging_tires(two_levels):
    w = rocky_deep(two_levels)
    c = person(w, "Ada", 11, 66, "stone_pickaxe", energy=50.0)
    dig(w, c, "east")
    assert c.energy == 48.0
    c.energy = 9.9
    assert dig(w, c, "east").message == "You're too worn out to dig; rest first."
    assert c.energy == 9.9 and c.inventory["stone"] == 1 and w.ext["digging"]["work"]["12,66"]["n"] == 1
    w = shaft_world()
    c = person(w, "Bo", *SPOT, "stone_pickaxe", energy=11.0)
    dig(w, c, "down")
    assert c.energy == 9.0
    assert dig(w, c, "down").message == "You're too worn out to dig; rest first."
    assert w.ext["digging"]["shafts"]["12,24"]["n"] == 1


def test_dig_tip_beside_rock_with_a_pickaxe_only(two_levels):
    tips = [t for t in registry.TECHNIQUES if t.name == "dig"]
    assert len(tips) == 1 and tips[0].line == DIG_LINE
    tip = tips[0]
    w = rocky_deep(two_levels)
    c = person(w, "Ada", 11, 66)
    assert tip.trigger(w, c) is None  # no pickaxe
    c.inventory["stone_pickaxe"] = 1
    assert tip.trigger(w, c) == 6.0 and DIG_LINE in relevant(w, c, packs_only=True)
    c.x = 6  # out in the cave, no wall beside
    assert tip.trigger(w, c) is None
    c.x = BORDER  # beside only the deep's border
    assert tip.trigger(w, c) is None
    c.x, c.y = 11, 5  # up on the surface (Task 11 adds the surface's cases)
    assert tip.trigger(w, c) is None
