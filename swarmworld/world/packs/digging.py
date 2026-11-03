"""Digging: tunnels through the deep's rock, mine shafts of your own, and the surface reshaped: trenches that bring the
river's water, pits, and open pits into the deep (data: swarmworld/data/packs/digging/).

- dig (target), below: toward a rock wall on one of your four sides (north, south, east or west; else the first wall
  beside you). With a pickaxe, WALL_DIGS digs break it into cave floor, each giving a stone; the last also gives a
  piece of each vein or seam that touches the wall. The rock along the deep's edges is too thick to dig.
- dig down, on the surface: with a pickaxe, SHAFT_DIGS digs where you stand, each giving dirt (stone on rocky ground),
  sink a mine shaft ("Ada's shaft", then "Ada's second shaft"...). A chamber opens in the rock below with a ladder,
  and the shaft and the ladder are a way down and back up (the underground pack's portals, the chamber's tiles in
  the portal's record). The chamber is a pocket sealed in the rock: whoever climbs down digs their way on.
  why_not_dig says where the ground may not be dug; a shaft also needs room below for its ladder.
- dig here / toward a direction (north, south, east or west), on the surface: with a hoe or a pickaxe each dig lowers
  the land a step (LOWER): grass, dirt, sand or forest floor becomes a trench, a trench a pit; rocky ground takes a
  pickaxe and WALL_DIGS digs to become a trench, and so does the rock under a pit, which then breaks through: an open
  pit (the "O" tile, with an open_pit object on it) over a chamber below with a ladder, open to the sky within
  SKY_REACH of the spot below it (world.skylight: daylight and rain fall in). It is a way down like a shaft, "Ada's
  pit". Each dig gives dirt, sand or stone (DUG_YIELD). No pit opens near the meadow's heart (why_not_dig); trenches
  may come nearer, to water the fields.
- Water follows trenches: a trench with water on one of its four sides (the river, the lake, or a trench already
  full) fills over FLOW_TICKS and becomes shallow water, still (no flow, so nothing drifts in it). Crops beside water
  grow no faster in v1: farming has no such bonus to extend, and made_water is where one would look.
- fill_in: a step back up (RAISE) for the dug land or a trench's water in the direction named, here, or the first
  beside you, with a dirt, stone or sand you carry; an open pit filled closes its way down and its sky (the chamber
  below stays), and the last step leaves bare dirt. Only a trench's water can be filled, never the river, the lake or
  the marsh, and those are never dug. "fill the trench" and "place dirt" (or stone, by a hole) come here too.
- Anyone may help: digs at the same wall, shaft or rock add to one shared count, and every digger is named.
- What "dig" meant before stays on the surface: a bare "dig", or one naming anything but where to dig (down, here,
  a trench, pit or hole, a direction), is a gather, exactly as before ("dig clay", "dig the boulder" over there).
  Below, a target naming a resource ("dig coal") or a gatherable thing within reach gathers; the rest is digging.
  "dig_down" means dig "down", and "dig_trench" dig "trench" (registry alias_targets).
- Each dig is hard work (DIG_ENERGY); under MIN_ENERGY a creature must rest first. Dug land never grows back.

State: world.ext["digging"] = {"work": {"x,y": {"n", "by"}} for rock being dug (walls below, rocky ground and pit
bottoms above), "shafts": {"x,y": {"n", "by"}} for shafts being sunk, where n counts the digs so far and "by" names
who dug; "dug": {"x,y": the land it was} for the trenches, pits and open pits there are; "filling": {"x,y": ticks}
for trenches water is seeping into; "made_water": {"x,y": the tick it filled} for trenches full of water}. A
creature's c.ext["digging"]["told"] is the last line it was told about them. Nothing here draws from world.rng.

The underground pack is imported inside the functions that need it, never at the top: importing it here would
register it (its populate too) ahead of the food and nature packs, and a fresh world would be populated differently
(tests/test_pack_digging.py::test_the_underground_populates_after_food_and_nature)."""

from __future__ import annotations

import itertools
from collections import Counter
from typing import TYPE_CHECKING

from .. import actions, perception
from ..actions import (PLANT_TOOLS, TOOLS_PICK, VECTORS, ActionResult, _busy, _dir_hint, _has_tool, _items_text,
                       _words, find_object)
from ..caves import BORDER, carve_chamber, chamber_tiles
from ..model import WATER_TILES
from ..perception import DIRS, direction, dist
from ..registry import (GATHERABLE, HANDLERS, ITEM_SOURCES, Technique, register_handoff, register_perception,
                        register_system, register_technique, register_verb)

if TYPE_CHECKING:  # never at the top for real: simulation imports the packs (see registry.py)
    from ..actions import Intention
    from ..model import Creature, World
    from ..simulation import Simulation

PACK = "digging"
WALL_DIGS = 3  # digs that break a rock wall
SHAFT_DIGS = 5  # digs that sink a shaft into the deep
DIG_TICKS = 4  # busy this long after a dig
DIG_ENERGY = 2  # what a dig costs
MIN_ENERGY = 10  # too worn out to dig below this
HEART = 2  # no digging this near the meadow's heart (world.center), where newcomers wake
HEART_DEEP = 6  # no pit, open pit or shaft this near it
PACKED = {"terminal", "wishing_stone"}  # the ground within a step of these is too hard to dig
CHAMBER = {"shaft": 1, "pit": 2}  # the radius of the chamber a way down opens in the rock below it
VEINS = {"iron_vein": "iron_ore", "copper_vein": "copper_ore", "coal_seam": "coal"}  # what a broken wall's vein gives
SIDES = ("east", "south", "west", "north")  # the four sides, in the order perception.DIRS lists them
ORDINALS = ("second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth")
DOWN_WORDS = {"down", "shaft", "deeper"}
# words that make "dig" a dig, never a gather, whatever else the target names
DIG_WORDS = DOWN_WORDS | {"here", "wall", "walls", "tunnel", "through", "trench", "ditch", "pit", "hole"}
LAND_ITEMS = ("plant_fiber", "sand")  # gathered from the land itself rather than from a kind of thing
LAND_WORDS = {"grass", "fiber", "sand"}
DIG_SURFACE_LINE = ("dig (target): with a hoe or pickaxe, dig here or toward a direction: grass becomes a trench, a "
                    "trench a pit, and with a pickaxe a pit breaks through into the deep. A trench beside water fills "
                    "with it; dig down sinks a mine shaft.")
DIG_LINE = DIG_SURFACE_LINE + (' Below, dig into the rock wall beside you with a pickaxe, toward a direction like '
                               '"north"; a few digs break through and give stone.')  # one tip for both (R10)
TOO_THICK = "The rock here is too thick to dig through."
BARE_HANDS = "The rock is too hard for bare hands; you'd need a pickaxe."
TOO_TIRED = "You're too worn out to dig; rest first."
FLOOR = "Under the dust the cave floor is solid rock; dig into a wall instead."
WATER = "Water fills it as fast as you dig."
CORNER = "Dig straight north, south, east or west; you couldn't squeeze through a corner."
NO_ROOM = "There's no room below for a ladder; dig your shaft somewhere else."

LOWER = {"g": "t", "d": "t", "s": "t", "f": "t", "r": "t", "t": "h", "h": "O"}  # what a dig makes of the land
DUG_YIELD = {"g": "dirt", "d": "dirt", "f": "dirt", "t": "dirt", "s": "sand", "r": "stone", "h": "stone"}
HARD = {"r": "Rocky ground needs a pickaxe.",  # these take a pickaxe, and WALL_DIGS digs
        "h": "Only a pickaxe breaks through the rock under a pit."}
SOFT_TOOLS = TOOLS_PICK + PLANT_TOOLS  # a pickaxe or a hoe
NO_TOOL = "You'd need a hoe or a pickaxe to dig."
NO_GROUND = "There's no ground there to dig."
OPEN_ALREADY = "That pit is open already, right down into the deep."
STEP_ASIDE = "Step aside first: the next dig breaks through under your feet."
NO_ROOM_PIT = "There's no room below for a ladder; dig your pit somewhere else."
OPENED = "Your pickaxe breaks through! Daylight falls into the dark below: the pit opens into the deep (climb down)."
SKY_REACH = 1  # the chamber under an open pit is open to the sky this near the spot right below it
FLOW_TICKS = 120  # water fills a trench beside it in this long
WATER_EVERY = 20
RAISE = {"O": "h", "h": "t", "t": "d"}  # what filling makes of dug land; a trench's water ("w") becomes dirt too
EARTH = ("dirt", "stone", "sand")  # what fills a hole, the first carried used unless one is named
FILL_TICKS = 3
FILL_ENERGY = 1
HOLE_WORDS = {"trench", "ditch", "pit", "hole"}
NATURAL = "Only a trench's water can be filled in; the river and the lake are too much."
NOTHING = "There's no trench or pit beside you to fill."
NO_EARTH = "You'd need dirt or stone to fill it with."
FILL_LINE = ("fill_in (target): fill the trench or pit beside you back in, a step at a time, with dirt or stone you "
             "carry.")
FULL = "A trench beside you runs full of water."
SEEPING = "Water is seeping into the trench beside you."
DAYLIGHT = "Daylight falls through an open pit far above you."
NIGHT_SKY = "Through an open pit far above, you can see the night sky."
BESIDE = [VECTORS[d] for d in SIDES] + [VECTORS[d] for d in DIRS if d not in SIDES]  # the four sides first


def _state(world: World) -> dict:
    return world.ext.setdefault(PACK, {})


def _names(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _below_ground(world: World, x: int, y: int) -> bool:
    r = world.region_at(x, y)
    return bool(r and r.level < 0)


def _inside_deep(world: World, x: int, y: int) -> bool:
    """In a region below the surface, more than caves.BORDER from each of its edges (the rock there is too thick)."""
    r = world.region_at(x, y)
    return bool(r and r.level < 0 and BORDER < x < world.width - 1 - BORDER
                and BORDER < y - r.y0 < r.height - 1 - BORDER)


def _side(x: int, y: int, dirn: str) -> tuple[int, int]:
    return x + VECTORS[dirn][0], y + VECTORS[dirn][1]


def _key(x: int, y: int) -> str:
    return f"{x},{y}"


def _kept(world: World, name: str) -> dict:
    """A part of the pack's state, read only (an empty dict when there is none)."""
    return (world.ext.get(PACK) or {}).get(name) or {}


def _near(x: int, y: int) -> list[tuple[int, int]]:
    """The eight tiles beside (x, y), its four sides first, then (x, y) itself."""
    return [(x + dx, y + dy) for dx, dy in BESIDE] + [(x, y)]


# ------------------------------------------------------------------ where the ground may be dug
def _in_building(world: World, x: int, y: int) -> bool:
    """On a building's or a construction site's footprint (the building pack's rectangles x0, y0, x1, y1, inclusive),
    or on the doorstep before its door (doors face south)."""
    b = world.ext.get("building") or {}
    for r in [*(b.get("sites") or {}).values(), *(b.get("built") or {}).values()]:
        door = r.get("door")
        if (r["x0"] <= x <= r["x1"] and r["y0"] <= y <= r["y1"]) or (door and (x, y) == (door[0], door[1] + 1)):
            return True
    return False


def why_not_dig(world: World, c: Creature, x: int, y: int, deep: bool) -> str | None:
    """Why creature c may not dig the surface at (x, y), or None. deep: a pit, an open pit or a shaft, which keeps
    farther from the meadow's heart and leads down to rock that must lie inside the deep's border. A creature
    digging its own tile doesn't stand in its own way; only an object there does."""
    here = world.object_at(x, y)
    if here:
        return f"The {here.name} is in the way."
    if _in_building(world, x, y):
        return "You can't dig inside a building."
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            o = world.object_at(x + dx, y + dy)
            if o and o.kind in PACKED:
                return f"The ground by the {o.name} is packed too hard to dig."
    heart = dist(x, y, *world.center)
    if heart <= HEART:
        return "This is the heart of the meadow, where newcomers wake; leave it be."
    if deep and heart <= HEART_DEEP:
        return "Too near the heart of the meadow for a pit; dig farther out."
    if world.tile(x, y) in WATER_TILES:
        return WATER
    other = next((o for o in world.creatures.values() if o is not c and (o.x, o.y) == (x, y)), None)
    if other:
        return f"{other.name} is standing there."
    if deep:
        under = world.below(x, y)
        if under is None or not _inside_deep(world, *under):
            return "The rock below is too thick here."
    return None


def ladder_spot(world: World, x: int, y: int, kind: str) -> tuple[int, int] | None:
    """Where the ladder of a way down from (x, y) would stand, changing nothing: the spot below if nothing lies there,
    else the nearest free tile of the chamber that would open (radius CHAMBER[kind]); None when there is no room."""
    at = world.below(x, y)
    if at is None:
        return None
    free = [p for p in chamber_tiles(world, *at, CHAMBER[kind]) if p not in world.grid]
    return min(free, key=lambda p: (dist(*p, *at), abs(p[0] - at[0]) + abs(p[1] - at[1]), p[1], p[0]), default=None)


def way_name(world: World, who: str, kind: str) -> str:
    """A new way down's name, never one already taken: "Ada's shaft", then "Ada's second shaft" and so on."""
    from .underground import portals  # here, not at the top: see the module's docstring
    taken = {p["name"] for p in portals(world)}
    names = itertools.chain([f"{who}'s {kind}"], (f"{who}'s {o} {kind}" for o in ORDINALS),
                            (f"{who}'s {kind} {n}" for n in itertools.count(len(ORDINALS) + 2)))
    return next(n for n in names if n not in taken)


def make_way_down(world: World, x: int, y: int, kind: str, name: str) -> tuple[dict, list[tuple[int, int]]]:
    """Open a way down from (x, y) on the surface ("shaft" or "pit"): a chamber of radius CHAMBER[kind] carved in the
    rock below, a ladder on ladder_spot, and the portal pairing it with the surface end, its record keeping the
    chamber's tiles ("chamber"). The chamber stays a pocket sealed in the rock. Check why_not_dig and ladder_spot
    first: with no room for a ladder this raises ValueError and changes nothing. Returns the portal and the chamber."""
    from .underground import add_portal  # here, not at the top: see the module's docstring
    ladder = ladder_spot(world, x, y, kind)
    if ladder is None:
        raise ValueError(f"no room for a ladder below {(x, y)}")
    chamber = carve_chamber(world, *world.below(x, y), CHAMBER[kind])
    portal = add_portal(world, kind, name, (x, y), ladder)
    portal["chamber"] = [list(p) for p in chamber]
    return portal, chamber


# ------------------------------------------------------------------ digging
def _names_resource(world: World, c: Creature, target: str, rest: list[str], reach: int | None) -> bool:
    """The target names an item some kind gives (or sand or grass from the land), or a gatherable thing in sight
    within reach (any distance with reach None)."""
    iid = world.catalog.resolve(target) or world.catalog.resolve(" ".join(rest))
    return (iid in ITEM_SOURCES or iid in LAND_ITEMS or bool(LAND_WORDS & set(rest))
            or find_object(world, c, " ".join(rest), max_dist=reach, kinds=GATHERABLE) is not None)


def _gathers(world: World, c: Creature, target: str) -> bool:
    """What "dig" meant before this pack, still a gather. On the surface: a bare dig, or a target with no word for
    where to dig (DIG_WORDS or a direction), exactly as before; a direction with a resource named ("dig clay north").
    Below: a target naming a resource, or a gatherable thing within reach."""
    words = _words(target)
    below = _below_ground(world, c.x, c.y)
    if not words:
        return not below
    if DIG_WORDS & set(words):
        return False
    dirn, rest = _dir_hint(words)
    if not rest:
        return False
    if not below and dirn is None:
        return True
    return _names_resource(world, c, target, rest, 1 if below else None)


def _dig_at(world: World, c: Creature, what: str, x: int, y: int) -> dict:
    """One dig at rock ("work") or a shaft ("shafts"): the shared count goes up, the digger is named, it tires."""
    rec = _state(world).setdefault(what, {}).setdefault(f"{x},{y}", {"n": 0, "by": []})
    rec["n"] += 1
    if c.name not in rec["by"]:
        rec["by"].append(c.name)
    _tire(c)
    return rec


def _tire(c: Creature) -> None:
    c.energy = max(0.0, c.energy - DIG_ENERGY)
    c.stats["dug"] += 1


def _tunnel(world: World, c: Creature, words: list[str]) -> ActionResult:
    """Below: dig at the rock wall in the direction named, or else the first wall beside you."""
    if DOWN_WORDS & set(words):
        return ActionResult(False, "There is nothing deeper than the deep.")
    dirn, _ = _dir_hint(words)
    if dirn is not None and dirn not in SIDES:
        return ActionResult(False, CORNER)
    if dirn is None and "here" not in words:
        walls = [d for d in SIDES if world.tile(*_side(c.x, c.y, d)) == "R"]
        dirn = next((d for d in walls if _inside_deep(world, *_side(c.x, c.y, d))), walls[0] if walls else None)
    if dirn is None:
        return ActionResult(False, FLOOR)
    x, y = _side(c.x, c.y, dirn)
    tile = world.tile(x, y)
    if tile in WATER_TILES:
        return ActionResult(False, WATER)
    if tile != "R":
        return ActionResult(False, FLOOR)
    if not _inside_deep(world, x, y):
        return ActionResult(False, TOO_THICK)
    if not _has_tool(c, TOOLS_PICK):
        return ActionResult(False, BARE_HANDS)
    if c.energy < MIN_ENERGY:
        return ActionResult(False, TOO_TIRED)
    rec = _dig_at(world, c, "work", x, y)
    got = Counter(stone=1)
    label = f"digging into the rock to the {dirn}"
    if rec["n"] < WALL_DIGS:
        c.inventory.update(got)
        world.emit("dig", c.id, x, y, f"{c.name} chipped at the rock wall.")
        return _busy(c, DIG_TICKS, label, f"You chip at the rock wall to the {dirn} and get 1 stone. It is giving way "
                                          f"({rec['n']} of {WALL_DIGS}).")
    del _state(world)["work"][f"{x},{y}"]
    world.set_tile(x, y, "c")
    for d in SIDES:
        o = world.object_at(*_side(x, y, d))
        if o and o.kind in VEINS:
            got[VEINS[o.kind]] += 1
    c.inventory.update(got)
    world.emit("dig", c.id, x, y, f"{_names(rec['by'])} broke through the rock wall.")
    return _busy(c, DIG_TICKS, label,
                 f"You break through the rock wall to the {dirn} and get {_items_text(world, got)}.")


def _shaft(world: World, c: Creature) -> ActionResult:
    """On the surface: dig down where you stand, toward a shaft into the deep."""
    x, y = c.x, c.y
    if not _has_tool(c, TOOLS_PICK):
        return ActionResult(False, "Digging down into the deep takes a pickaxe.")
    why = why_not_dig(world, c, x, y, True)
    if why:
        return ActionResult(False, why)
    if ladder_spot(world, x, y, "shaft") is None:
        return ActionResult(False, NO_ROOM)
    if c.energy < MIN_ENERGY:
        return ActionResult(False, TOO_TIRED)
    rec = _dig_at(world, c, "shafts", x, y)
    item = "stone" if world.tile(x, y) == "r" else "dirt"
    c.inventory[item] += 1
    if rec["n"] < SHAFT_DIGS:
        world.emit("dig", c.id, x, y, f"{c.name} dug down into the ground.")
        return _busy(c, DIG_TICKS, "digging a shaft",
                     f"You dig down where you stand and get 1 {world.catalog.name(item)} ({rec['n']} of {SHAFT_DIGS}).")
    del _state(world)["shafts"][f"{x},{y}"]
    make_way_down(world, x, y, "shaft", way_name(world, c.name, "shaft"))
    world.emit("place", c.id, x, y, f"{_names(rec['by'])} dug a mine shaft down into the deep.",
               object_kind="mine_shaft")
    return _busy(c, DIG_TICKS, "digging a shaft", "The ground gives way beneath your pickaxe: a shaft drops into the "
                                                  "deep, with a ladder down (climb down).")


def _dig(world: World, c: Creature, it: Intention) -> ActionResult:
    target = it.target or (it.items[0] if it.items else "")
    if _gathers(world, c, target):
        return HANDLERS["gather"](world, c, it)
    words = _words(target)
    if _below_ground(world, c.x, c.y):
        return _tunnel(world, c, words)
    if DOWN_WORDS & set(words):
        return _shaft(world, c)
    return _terraform(world, c, words)


def _within(world: World, c: Creature, r: int, found) -> bool:
    """found(x, y) is true somewhere within r of the creature, in its region."""
    return any(found(x, y) for y in world.view_rows(c.y, r) for x in range(c.x - r, c.x + r + 1)
               if world.in_bounds(x, y))


def _dig_fits(world: World, c: Creature) -> float | None:
    """Below: carrying a pickaxe, beside rock that can be dug (6.0). On the surface, carrying a hoe or a pickaxe:
    beside dug land or a dig under way (5.5), or standing on ground you could dig within 2 of water and 3 of a crop,
    where a trench would bring the water to the field (4.4)."""
    if _below_ground(world, c.x, c.y):
        if not _has_tool(c, TOOLS_PICK):
            return None
        walls = [_side(c.x, c.y, d) for d in SIDES]
        return 6.0 if any(world.tile(*p) == "R" and _inside_deep(world, *p) for p in walls) else None
    if not _has_tool(c, SOFT_TOOLS):
        return None
    under_way = {*_kept(world, "shafts"), *_kept(world, "work")}
    if any(world.tile(*p) in RAISE or _key(*p) in under_way for p in _near(c.x, c.y)):
        return 5.5
    here = world.tile(c.x, c.y)
    if here not in LOWER or (here in HARD and not _has_tool(c, TOOLS_PICK)):
        return None

    def crop(x: int, y: int) -> bool:
        o = world.object_at(x, y)
        return o is not None and o.kind == "crop"
    near_field = _within(world, c, 2, lambda x, y: world.tile(x, y) in WATER_TILES) and _within(world, c, 3, crop)
    return 4.4 if near_field and why_not_dig(world, c, c.x, c.y, False) is None else None


# ------------------------------------------------------------------ terraforming the surface
def _lower(world: World, x: int, y: int, was: str) -> None:
    """The land at (x, y) a step lower (LOWER[was]), and kept among the dug land."""
    mine = _state(world)
    world.set_tile(x, y, LOWER[was])
    mine.setdefault("dug", {}).setdefault(_key(x, y), was)
    (mine.get("filling") or {}).pop(_key(x, y), None)  # a pit holds no seeping water


def _skylit(world: World, p: dict) -> set[tuple[int, int]]:
    """The tiles of an open pit's chamber open to the sky: within SKY_REACH of the spot right below the pit."""
    bx, by = world.below(*p["up"])
    return {(x, y) for x, y in p.get("chamber") or () if dist(x, y, bx, by) <= SKY_REACH}


def _open_pit(world: World, c: Creature, x: int, y: int, by: list[str]) -> ActionResult:
    """The last dig through the rock under a pit: a way down into the deep under the open sky."""
    portal, _ = make_way_down(world, x, y, "pit", way_name(world, c.name, "pit"))
    _lower(world, x, y, "h")
    world.skylight |= _skylit(world, portal)
    world.emit("place", c.id, x, y, f"{_names(by)} broke through into the deep: an open pit.", object_kind="open_pit")
    return _busy(c, DIG_TICKS, "digging a pit", OPENED)


def _terraform(world: World, c: Creature, words: list[str]) -> ActionResult:
    """On the surface: dig the ground a step lower where you stand, or beside you toward north, south, east or west."""
    dirn, _ = _dir_hint(words)
    if dirn is not None and dirn not in SIDES:
        return ActionResult(False, CORNER)
    x, y = _side(c.x, c.y, dirn) if dirn else (c.x, c.y)
    where = f"to the {dirn}" if dirn else "here"
    tile = world.tile(x, y)
    if tile == "O":
        return ActionResult(False, OPEN_ALREADY)
    if not world.same_region((c.x, c.y), (x, y)) or (tile not in LOWER and tile not in WATER_TILES):
        return ActionResult(False, NO_GROUND)
    if tile in LOWER and not _has_tool(c, TOOLS_PICK if tile in HARD else SOFT_TOOLS):
        return ActionResult(False, HARD.get(tile, NO_TOOL))
    why = why_not_dig(world, c, x, y, tile in ("t", "h"))  # the river and the lake: "Water fills it..."
    if why:
        return ActionResult(False, why)
    if tile == "h" and (x, y) == (c.x, c.y):
        return ActionResult(False, STEP_ASIDE)
    if tile == "h" and ladder_spot(world, x, y, "pit") is None:
        return ActionResult(False, NO_ROOM_PIT)
    if c.energy < MIN_ENERGY:
        return ActionResult(False, TOO_TIRED)
    item = DUG_YIELD[tile]
    if tile in HARD:
        rec = _dig_at(world, c, "work", x, y)
        if rec["n"] < WALL_DIGS:
            c.inventory[item] += 1
            world.emit("dig", c.id, x, y, f"{c.name} hacked at the rock.")
            return _busy(c, DIG_TICKS, "digging through rock",
                         f"You hack at the rock {where} and get 1 stone ({rec['n']} of {WALL_DIGS}).")
        del _state(world)["work"][_key(x, y)]
        by = rec["by"]
    else:
        _tire(c)
        by = [c.name]
    c.inventory[item] += 1
    if tile == "h":
        return _open_pit(world, c, x, y, by)
    _lower(world, x, y, tile)
    name = world.catalog.name(item)
    if tile == "t":
        world.emit("dig", c.id, x, y, f"{_names(by)} dug a pit.")
        return _busy(c, DIG_TICKS, "digging a pit", f"You dig the trench {where} down into a pit and get 1 {name}.")
    world.emit("dig", c.id, x, y, f"{_names(by)} dug a trench.")
    return _busy(c, DIG_TICKS, "digging a trench", f"You dig a trench {where} and get 1 {name}.")


# ------------------------------------------------------------------ water follows trenches
def _water_beside(world: World, x: int, y: int) -> bool:
    return any(world.in_bounds(x + dx, y + dy) and world.tile(x + dx, y + dy) in WATER_TILES
               for dx, dy in (VECTORS[d] for d in SIDES))


def _water(sim: Simulation, t: int) -> None:
    """Every trench with water on one of its four sides (and nothing standing in it) fills a little more; after
    FLOW_TICKS it is shallow water. The land's flow is left as it was, so the water is still."""
    w = sim.world
    mine = w.ext.get(PACK) or {}
    dug = mine.get("dug")
    if not dug:
        return
    wet = []
    for key in dug:
        x, y = map(int, key.split(","))
        if w.tile(x, y) == "t" and (x, y) not in w.grid and _water_beside(w, x, y):
            wet.append((key, x, y))
    if not wet:
        return
    filling = mine.setdefault("filling", {})
    for key, x, y in wet:  # all at once: the trench next along begins once this one is water, not the same tick
        filling[key] = filling.get(key, 0) + WATER_EVERY
        if filling[key] >= FLOW_TICKS:
            del filling[key], dug[key]
            w.set_tile(x, y, "w")
            mine.setdefault("made_water", {})[key] = t


# ------------------------------------------------------------------ filling in
def _fillable(world: World, x: int, y: int) -> bool:
    """Dug land on the surface (a trench, a pit, an open pit), or water a trench filled with."""
    r = world.region_at(x, y)
    if not (r and r.level == 0):
        return False
    t = world.tile(x, y)
    return t in RAISE or (t == "w" and _key(x, y) in _kept(world, "made_water"))


def _close_pit(world: World, x: int, y: int) -> None:
    """The open pit at (x, y) is a way down no more: its portal and its ends go, and its sky but where another open
    pit's reaches. The chamber below stays."""
    from .underground import portals, remove_portal  # here, not at the top: see the module's docstring
    pits = [p for p in portals(world) if p["kind"] == "pit"]
    p = next((p for p in pits if tuple(p["up"]) == (x, y)), None)
    if p is None:
        return
    others = set().union(*(_skylit(world, q) for q in pits if q is not p))
    world.skylight -= _skylit(world, p) - others
    remove_portal(world, p["id"])


def _raise(world: World, x: int, y: int) -> None:
    """Fill (x, y) a step back up; a trench's water, or a trench, ends as bare dirt."""
    mine = _state(world)
    key = _key(x, y)
    was = world.tile(x, y)
    if was == "O":
        _close_pit(world, x, y)
    if was == "w":
        mine.get("made_water", {}).pop(key, None)
    new = "d" if was == "w" else RAISE[was]
    if new == "d":
        mine.get("dug", {}).pop(key, None)
    for part in ("filling", "work"):  # water seeping in, or rock being broken there
        (mine.get(part) or {}).pop(key, None)
    world.set_tile(x, y, new)


def _earth(world: World, c: Creature, it: Intention) -> str | None:
    """The dirt, stone or sand to fill with: one named, if carried; else the first carried in EARTH's order."""
    named = [world.catalog.resolve(n) for n in (it.target, *it.items, *_words(it.target))]
    held = [i for i in named + list(EARTH) if i in EARTH and c.inventory.get(i, 0) > 0]
    return held[0] if held else None


def _fill_in(world: World, c: Creature, it: Intention) -> ActionResult:
    words = _words(f"{it.target} {it.text}")
    dirn, _ = _dir_hint(words)
    spots = [_side(c.x, c.y, dirn)] if dirn else [(c.x, c.y)] if "here" in words else _near(c.x, c.y)
    spot = next((p for p in spots if _fillable(world, *p)), None)
    if spot is None:
        wet = any(world.in_bounds(*p) and world.tile(*p) in WATER_TILES for p in spots)
        return ActionResult(False, NATURAL if wet else NOTHING)
    earth = _earth(world, c, it)
    if earth is None:
        return ActionResult(False, NO_EARTH)
    x, y = spot
    was = world.tile(x, y)
    _raise(world, x, y)
    c.inventory[earth] -= 1
    if c.inventory[earth] <= 0:
        del c.inventory[earth]
    c.energy = max(0.0, c.energy - FILL_ENERGY)
    where = "here" if spot == (c.x, c.y) else f"to the {direction(x - c.x, y - c.y)}"
    item = world.catalog.name(earth)
    text = {"O": f"You throw 1 {item} into the open pit {where}; it is a pit again, its way into the deep closed.",
            "h": f"You fill the pit {where} with 1 {item}; it is a trench again.",
            "t": f"You fill the trench {where} with 1 {item}; it is level ground again, bare dirt.",
            "w": f"You fill the trench's water {where} with 1 {item}; it is level ground again, bare dirt."}[was]
    what = {"O": "an open pit", "h": "a pit", "t": "a trench", "w": "a trench full of water"}[was]
    world.emit("dig", c.id, x, y, f"{c.name} filled in {what}.")
    return _busy(c, FILL_TICKS, "filling in the ground", text)


def _fills_a_hole(world: World, c: Creature, it: Intention) -> bool:
    """"fill the trench" (a ditch, a pit, a hole), or fill with dirt, stone or sand: filling in. Food's fill stays the
    pots': "fill the pot from the trench" is a pot's."""
    words = _words(it.target)
    pots = {empty for empty in actions.DRINKS.values() if empty}
    if HOLE_WORDS & set(words) and not any(world.catalog.resolve(w) in pots for w in words):
        return True
    return any(world.catalog.resolve(n) in EARTH for n in it.items)


def _places_earth(world: World, c: Creature, it: Intention) -> bool:
    """"place dirt" fills in the hole beside you, and so does "place stone" (or sand) while there is one."""
    name = it.target or (it.items[0] if it.items else "")
    iid = world.catalog.resolve(name) or world.catalog.resolve(" ".join(w for w in _words(name) if w not in DIRS))
    return iid == "dirt" or (iid in EARTH and any(_fillable(world, *p) for p in _near(c.x, c.y)))


def _fill_fits(world: World, c: Creature) -> float | None:
    """Carrying dirt, stone or sand beside dug land or a trench's water."""
    if not any(c.inventory.get(i, 0) > 0 for i in EARTH):
        return None
    return 5.0 if any(_fillable(world, *p) for p in _near(c.x, c.y)) else None


def _dug_line(world: World, c: Creature) -> str | None:
    """What digging made beside you, said when it changes: a trench full of water, or one water is seeping into; and
    below, the sky through an open pit overhead."""
    line = None
    if _below_ground(world, c.x, c.y):
        if (c.x, c.y) in world.skylight:
            line = NIGHT_SKY if world.clock()["phase"] == "night" else DAYLIGHT
    elif world.ext.get(PACK):
        made, filling = _kept(world, "made_water"), _kept(world, "filling")
        near = _near(c.x, c.y)
        if any(_key(*p) in made and world.tile(*p) == "w" for p in near):
            line = FULL
        elif any(_key(*p) in filling and world.tile(*p) == "t" for p in near):
            line = SEEPING
    told = (c.ext.get(PACK) or {}).get("told")
    if line == told:
        return None
    if line is None:
        del c.ext[PACK]["told"]
        return None
    c.ext.setdefault(PACK, {})["told"] = line
    return line


perception.FEATURES.update({"t": "a trench", "h": "a pit", "O": "an open pit"})
actions.TILE_TARGETS.update({"trench": "t", "ditch": "t", "pit": "hO", "hole": "hO"})
register_verb("dig", _dig, aliases=("tunnel", "excavate", "dig_down", "dig_tunnel", "dig_trench"), replaces_alias=True,
              alias_targets={"dig_down": "down", "dig_trench": "trench"})
register_verb("fill_in", _fill_in, aliases=("backfill", "fill_hole", "fill_trench", "fill_pit"))
register_handoff("fill", "fill_in", _fills_a_hole)
register_handoff("place", "fill_in", _places_earth)
register_system("digging water", WATER_EVERY, _water)
register_perception(_dug_line, priority=44)
register_technique(Technique("dig", DIG_LINE, _dig_fits))
register_technique(Technique("fill_in", FILL_LINE, _fill_fits))
