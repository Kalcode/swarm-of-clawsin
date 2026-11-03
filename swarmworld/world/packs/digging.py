"""Digging: tunnels through the deep's rock and mine shafts of your own (data: swarmworld/data/packs/digging/).

- dig (target), below: toward a rock wall on one of your four sides (north, south, east or west; else the first wall
  beside you). With a pickaxe, WALL_DIGS digs break it into cave floor, each giving a stone; the last also gives a
  piece of each vein or seam that touches the wall. The rock along the deep's edges is too thick to dig.
- dig down, on the surface: with a pickaxe, SHAFT_DIGS digs where you stand, each giving dirt (stone on rocky ground),
  sink a mine shaft ("Ada's shaft", then "Ada's second shaft"...). A chamber opens in the rock below with a ladder,
  and the shaft and the ladder are a way down and back up (the underground pack's portals, the chamber's tiles in
  the portal's record). The chamber is a pocket sealed in the rock: whoever climbs down digs their way on.
  why_not_dig says where the ground may not be dug; a shaft also needs room below for its ladder.
- Anyone may help: digs at the same wall or shaft add to one shared count, and every digger is named.
- What "dig" meant before stays on the surface: a bare "dig", or one naming anything but where to dig (down, here,
  a trench, pit or hole, a direction), is a gather, exactly as before ("dig clay", "dig the boulder" over there).
  Below, a target naming a resource ("dig coal") or a gatherable thing within reach gathers; the rest is digging.
- Each dig is hard work (DIG_ENERGY); under MIN_ENERGY a creature must rest first.

State: world.ext["digging"] = {"work": {"x,y": {"n", "by"}} for rock walls being dug, "shafts": {"x,y": {"n", "by"}}
for shafts being sunk}, where n counts the digs so far and "by" names who dug. Nothing here draws from world.rng.

The underground pack is imported inside the functions that need it, never at the top: importing it here would
register it (its populate too) ahead of the food and nature packs, and a fresh world would be populated differently
(tests/test_pack_digging.py::test_the_underground_populates_after_food_and_nature)."""

from __future__ import annotations

import itertools
from collections import Counter
from typing import TYPE_CHECKING

from ..actions import (TOOLS_PICK, VECTORS, ActionResult, _busy, _dir_hint, _has_tool, _items_text, _words,
                       find_object)
from ..caves import BORDER, carve_chamber, chamber_tiles
from ..model import WATER_TILES
from ..perception import dist
from ..registry import GATHERABLE, HANDLERS, ITEM_SOURCES, Technique, register_technique, register_verb

if TYPE_CHECKING:  # never at the top for real: simulation imports the packs (see registry.py)
    from ..actions import Intention
    from ..model import Creature, World

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
DIG_LINE = ('dig (target): dig into the rock wall beside you with a pickaxe, toward a direction like "north"; a few '
            'digs break through and give stone. Up on the surface, dig down sinks a shaft of your own, and with a hoe '
            'or pickaxe you can dig a trench or a pit, here or toward a direction.')
TOO_THICK = "The rock here is too thick to dig through."
BARE_HANDS = "The rock is too hard for bare hands; you'd need a pickaxe."
TOO_TIRED = "You're too worn out to dig; rest first."
FLOOR = "Under the dust the cave floor is solid rock; dig into a wall instead."
WATER = "Water fills it as fast as you dig."
CORNER = "Dig straight north, south, east or west; you couldn't squeeze through a corner."
NO_ROOM = "There's no room below for a ladder; dig your shaft somewhere else."


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
    """One dig at a wall ("work") or a shaft ("shafts"): the shared count goes up, the digger is named, it tires."""
    rec = _state(world).setdefault(what, {}).setdefault(f"{x},{y}", {"n": 0, "by": []})
    rec["n"] += 1
    if c.name not in rec["by"]:
        rec["by"].append(c.name)
    c.energy = max(0.0, c.energy - DIG_ENERGY)
    c.stats["dug"] += 1
    return rec


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
    return ActionResult(False, "You can only dig down here, with a pickaxe.")


def _dig_fits(world: World, c: Creature) -> float | None:
    """Below, carrying a pickaxe, beside rock that can be dug."""
    if not _below_ground(world, c.x, c.y) or not _has_tool(c, TOOLS_PICK):
        return None
    walls = [_side(c.x, c.y, d) for d in SIDES]
    return 6.0 if any(world.tile(*p) == "R" and _inside_deep(world, *p) for p in walls) else None


register_verb("dig", _dig, aliases=("tunnel", "excavate", "dig_down", "dig_tunnel", "dig_trench"), replaces_alias=True)
register_technique(Technique("dig", DIG_LINE, _dig_fits))
