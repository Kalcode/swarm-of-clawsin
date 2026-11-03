"""Food and work: fish species by water type and time of day, cooking at a campfire, oven or smoker, a drying rack and
a well, clay pots that carry water, wild deer, rabbits and boar to hunt with a spear or a sling (meat, hide and bone;
leather from hide), mushrooms and wild herbs to forage, and raw meat and fish that spoil unless cooked, smoked or dried.

Data: swarmworld/data/packs/food/ (items, recipes, kinds, and food.json for fishing, keeping, drying, water and
weapons). Wild game is an ordinary animal kind with "wild", "wary" and "flee" in its data, so the world's own animal
state machine (Simulation._animals) moves it; it just flees sooner and farther, and is never tamed."""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import TYPE_CHECKING

from .. import actions, perception
from ..actions import ActionResult, Intention, _busy, find_object, start_walk, station_near, water_kinds
from ..catalog import DATA
from ..model import WATER_TILES
from ..perception import dist, direction, sight_range, visible_objects
from ..registry import (ANIMALS, KINDS, STORES, Technique, register_perception, register_populate, register_system,
                        register_technique, register_verb)

if TYPE_CHECKING:  # never at the top for real: simulation imports the packs (see registry.py)
    from ..model import Creature, World, WorldObject
    from ..simulation import Simulation

PACK = "food"
CONFIG = json.loads((DATA / "packs" / PACK / "food.json").read_text())

FISHING = CONFIG["fishing"]
FISHING_ITEMS = {f["item"] for f in FISHING["catches"]}
PERISHABLE = tuple(CONFIG["keeping"]["perishable"])
SPOILS_AFTER = CONFIG["keeping"]["spoils_after"]
WARN_AFTER = CONFIG["keeping"]["warn_after"]
SPOIL_EVERY = 20
DRY_TICKS = CONFIG["drying"]["ticks"]
DRY_MAKES = CONFIG["drying"]["makes"]
DRY_EVERY = 10
WET = set(CONFIG["drying"]["wet_weather"])
FAST = set(CONFIG["drying"]["fast_weather"])
FILL = CONFIG["water"]["fill"]  # empty container -> full
WEAPONS = {k: v for k, v in CONFIG["weapons"].items() if isinstance(v, dict)}
COOK_STATIONS = ("campfire", "oven", "smoker")
STALK_TRIES = 3  # walks after the same animal before it has got away
MISS_PER_STEP = 0.06  # each step farther than arm's length makes a hit less likely
MISS_BOLT = 3  # a missed animal runs this many steps more than it flees from a stranger: usually out of sight
WILDLIFE_EVERY = 300
GAME_KEEPS_OFF = 8  # new game appears at least this far from anyone
WHEN = {"dawn": "at dawn", "day": "by day", "dusk": "at dusk", "night": "at night"}


def _state(holder) -> dict:
    """This pack's state on a creature or the world (saved with it)."""
    return holder.ext.setdefault(PACK, {})


def _and(words: list[str]) -> str:
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]


def _take(c: Creature, item: str, n: int = 1) -> None:
    c.inventory[item] -= n
    if c.inventory[item] <= 0:
        del c.inventory[item]


def _around(world: World, x: int, y: int, include_self: bool = False) -> set[tuple[int, int]]:
    return {(x + dx, y + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)
            if (dx or dy or include_self) and world.walkable(x + dx, y + dy)}


def _weather(world: World) -> str:
    return getattr(world, "weather", "clear")


# ------------------------------------------------------------------ fishing: species by water and time
def _water_type(world: World, x: int, y: int) -> str | None:
    """The water within reach of (x, y): "deep" if any of it is deep, "shallow" (cave water too), or None."""
    near = {world.tile(x + dx, y + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if world.in_bounds(x + dx, y + dy)}
    return "deep" if "W" in near else "shallow" if near & {"w", "u"} else None


def _biting(water: str, phase: str) -> list[dict]:
    return [f for f in FISHING["catches"] if water in f["water"] and phase in f["times"]]


def _catch(world: World, c: Creature) -> str | None:
    """One cast (actions.catch_fish): a bite is likelier at dawn and dusk; what bites depends on the water and the
    hour."""
    phase = world.clock()["phase"]
    if world.rng.random() >= FISHING["bite"].get(phase, 0.5):
        return None
    fits = _biting(_water_type(world, c.x, c.y) or "shallow", phase)
    if not fits:
        return "fish"
    return world.rng.choices([f["item"] for f in fits], weights=[f["weight"] for f in fits])[0]


actions.catch_fish = _catch


def _fishing_line(world: World, c: Creature) -> str | None:
    """Beside water with a rod: what bites here at this hour, said when the water or the hour changes."""
    if not c.inventory.get("fishing_rod"):
        return None
    water = _water_type(world, c.x, c.y)
    if water is None:
        return None
    phase = world.clock()["phase"]
    mine = _state(c)
    if mine.get("fishing") == f"{water}/{phase}":
        return None
    mine["fishing"] = f"{water}/{phase}"
    fits = sorted(_biting(water, phase), key=lambda f: -f["weight"])
    if not fits:
        return None
    names = _and([world.catalog.name(f["item"]) for f in fits])
    return f"In the {water} water beside you, {names} bite {WHEN.get(phase, 'now')}."


# ------------------------------------------------------------------ water: wells and clay pots
actions.DRINKS.update({full: empty for empty, full in FILL.items()})  # drink a pot of water anywhere; the pot stays


def _water_in_reach(world: World, c: Creature) -> str | None:
    """What you could fill a pot from right here: "well" (or another water kind's name), "water", or None."""
    well = find_object(world, c, "", max_dist=1, kinds=water_kinds())
    if well:
        return well.name
    return "water" if _water_type(world, c.x, c.y) else None


def _water_in_sight(world: World, c: Creature) -> tuple[int, int, int] | None:
    r = sight_range(world, c)
    best = None
    for y in world.view_rows(c.y, r):
        for x in range(c.x - r, c.x + r + 1):
            if world.in_bounds(x, y) and world.tile(x, y) in WATER_TILES:
                d = dist(c.x, c.y, x, y)
                if best is None or d < best[2]:
                    best = (x, y, d)
    return best


def _fill(world: World, c: Creature, it: Intention) -> ActionResult:
    empties = {e: c.inventory[e] for e in FILL if c.inventory.get(e, 0) > 0}
    if not empties:
        if any(c.inventory.get(full, 0) > 0 for full in FILL.values()):
            return ActionResult(False, "Your pot is already full of water. Drink from it (drink), or hold it while you "
                                       "cook a stew.")
        return ActionResult(False, "You'd need an empty clay pot to carry water in. (A pot is made of clay, fired.)")
    source = _water_in_reach(world, c)
    if source is None:
        kinds = water_kinds()
        well = find_object(world, c, it.target, kinds=kinds) if it.target else None
        well = well or find_object(world, c, "", kinds=kinds)
        water = _water_in_sight(world, c)
        if well and (water is None or dist(c.x, c.y, well.x, well.y) <= water[2]):
            res = start_walk(world, c, _around(world, well.x, well.y), f"walking to the {well.name}",
                             f"You arrive beside the {well.name}.")
        elif water:
            res = start_walk(world, c, _around(world, water[0], water[1], include_self=True), "walking to the water",
                             "You reach the water.")
        else:
            return ActionResult(False, "There's no well or water in sight to fill your pot from.")
        if c.activity:
            c.activity["then"] = it
        return res
    want = it.count if it.count > 1 else sum(empties.values())
    filled = 0
    for empty, n in empties.items():
        k = min(n, want - filled)
        if k > 0:
            _take(c, empty, k)
            c.inventory[FILL[empty]] += k
            filled += k
    world.sound(c.x, c.y, "water sloshing into a pot", radius=4, kind="splash", source=c.id)
    pots = "your clay pot" if filled == 1 else f"{filled} clay pots"
    where = "at the water's edge" if source == "water" else f"at the {source}"
    return _busy(c, 2, "filling a pot with water",
                 f"You fill {pots} with water {where}. Carry it and drink from it anywhere (drink); "
                 f"stews and broth need a pot of water in hand.")


def _fill_fits(world: World, c: Creature) -> float | None:
    if not any(c.inventory.get(e, 0) > 0 for e in FILL):
        return None
    if find_object(world, c, "", kinds=water_kinds()) or _water_in_sight(world, c):
        return 4.2
    return None


# ------------------------------------------------------------------ hunting
def _wild_kinds() -> set[str]:
    return {k for k in ANIMALS if actions.is_wild(k)}


def _held_weapons(world: World, c: Creature) -> dict[str, str]:
    """Weapon kind ("spear", "sling") -> the item carried for it: the real one, or an invention named for it."""
    held: dict[str, str] = {}
    for iid, n in sorted(c.inventory.items()):
        if n <= 0:
            continue
        item = world.catalog.items.get(iid)
        for kind in WEAPONS:
            if iid == kind or (item and "invention" in item.tags and re.search(rf"\b{kind}", item.name.lower())):
                held.setdefault(kind, iid)
    return held


def _odds(prey: WorldObject, weapon: str, d: int, night: bool) -> float:
    base = KINDS[prey.kind]["game"]["hit"].get(weapon, 0.3)
    return max(0.05, base - MISS_PER_STEP * max(0, d - 1) - (0.1 if night else 0.0))


def _bolt(world: World, o: WorldObject, fx: int, fy: int, steps: int) -> None:
    """An animal runs from (fx, fy): greedy steps to whichever free tile is farthest away."""
    o.data["state"] = "wary"
    for _ in range(steps):
        here = (o.x - fx) ** 2 + (o.y - fy) ** 2
        opts = [(o.x + dx, o.y + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy]
        world.rng.shuffle(opts)
        opts.sort(key=lambda p: -((p[0] - fx) ** 2 + (p[1] - fy) ** 2))
        if not any((p[0] - fx) ** 2 + (p[1] - fy) ** 2 > here and not world.occupied(*p) and world.move_object(o, *p)
                   for p in opts):
            return


def _startle(world: World, x: int, y: int, spared: str | None = None) -> None:
    """The noise of a hunt sends other game nearby running."""
    for o in list(world.objects.values()):
        if o.id != spared and actions.is_wild(o.kind) and dist(o.x, o.y, x, y) <= 4:
            _bolt(world, o, x, y, KINDS[o.kind].get("flee", 1))


def _stalk(world: World, c: Creature, prey: WorldObject, reach: int, it: Intention) -> ActionResult:
    mine = _state(c)
    chase = mine.get("chase") or {}
    again = chase.get("prey") == prey.id and world.tick - chase.get("tick", -10**9) < 100
    tries = chase.get("n", 0) + 1 if again else 1
    if tries > STALK_TRIES:
        mine.pop("chase", None)
        return ActionResult(False, f"The {prey.name} keeps slipping away from you. Wild game bolts when anyone comes "
                                   f"within a few steps; a sling strikes from farther off.")
    mine["chase"] = {"prey": prey.id, "n": tries, "tick": world.tick}
    r = max(1, reach - 1)
    goals = {(x, y) for x in range(prey.x - r, prey.x + r + 1) for y in range(prey.y - r, prey.y + r + 1)
             if (x, y) != (prey.x, prey.y) and world.walkable(x, y)}
    res = start_walk(world, c, goals, f"stalking the {prey.name}", f"You creep closer to the {prey.name}.")
    if c.activity:
        c.activity["then"] = it
    return res


def _hunt(world: World, c: Creature, it: Intention) -> ActionResult:
    wild = _wild_kinds()
    target = (it.target or (it.items[0] if it.items else "")).strip()
    prey = find_object(world, c, target, kinds=wild) if target else find_object(world, c, "", kinds=wild)
    if prey is None:
        tame = find_object(world, c, target, kinds=ANIMALS - wild) if target else None
        if tame and tame.data.get("tamed_by"):
            return ActionResult(False, f"The {tame.name} isn't game: it belongs to {tame.data['tamed_by']}.")
        other = find_object(world, c, "", kinds=wild)
        if tame:
            msg = f"The {tame.name} isn't game: feed it, and it may come to trust you. Only wild game is hunted."
        elif target:
            msg = f"You see no {target} to hunt; only wild game (deer, rabbits, boar) is hunted."
        else:
            msg = ("There's no wild game in sight. Deer and boar keep to the woods, rabbits to open grass, and all "
                   "of them bolt when anyone comes near.")
        if other:
            d = dist(c.x, c.y, other.x, other.y)
            msg += f" A {other.name} is {d} steps {direction(other.x - c.x, other.y - c.y)}, though."
        return ActionResult(False, msg)
    held = _held_weapons(world, c)
    if not held:
        return ActionResult(False, f"You'd need a hunting weapon to bring down the {prey.name}: a spear, or a sling "
                                   f"with stones.")
    usable = [k for k in held if not WEAPONS[k].get("ammo") or c.inventory.get(WEAPONS[k]["ammo"], 0) > 0]
    if not usable:
        kind = next(iter(held))
        ammo = world.catalog.name(WEAPONS[kind]["ammo"])
        return ActionResult(False, f"Your {world.catalog.name(held[kind])} needs a {ammo} to throw. Gather some from a "
                                   f"boulder.")
    d = dist(c.x, c.y, prey.x, prey.y)
    in_reach = [k for k in usable if d <= WEAPONS[k]["reach"]]
    if not in_reach:
        return _stalk(world, c, prey, max(WEAPONS[k]["reach"] for k in usable), it)
    _state(c).pop("chase", None)
    night = world.clock()["phase"] == "night"
    weapon = max(in_reach, key=lambda k: _odds(prey, weapon=k, d=d, night=night))
    ammo = WEAPONS[weapon].get("ammo")
    if ammo:
        _take(c, ammo)
    c.energy = max(0.0, c.energy - 2)
    throw = f"throw your {world.catalog.name(held[weapon])}" if not ammo else \
        f"let fly a {world.catalog.name(ammo)} from your {world.catalog.name(held[weapon])}"
    x, y = prey.x, prey.y
    if world.rng.random() < _odds(prey, weapon, d, night):
        got = Counter()
        for item, (lo, hi) in KINDS[prey.kind]["game"]["gives"].items():
            n = world.rng.randint(lo, hi)
            if n:
                got[item] += n
        world.remove_object(prey.id)
        c.inventory.update(got)
        c.stats["hunted"] += 1
        c.stats["gathered"] += sum(got.values())
        took = ", ".join(f"{n} {world.catalog.name(i)}" for i, n in got.items())
        world.sound(x, y, f"a {prey.name}'s cry, cut short", radius=8, kind="hunt", source=c.id)
        world.emit("gather", c.id, x, y, f"{c.name} hunted a {prey.name} and took {took}.", hunted=prey.kind)
        _startle(world, x, y)
        keep = " Raw meat spoils in about two days unless you cook, smoke or dry it." if got.get("meat") else ""
        return _busy(c, 6, f"butchering the {prey.name}",
                     f"You {throw} and it strikes true: the {prey.name} falls. You butcher it and take {took}.{keep}")
    _bolt(world, prey, c.x, c.y, KINDS[prey.kind].get("flee", 1) + MISS_BOLT)
    world.sound(x, y, f"a {prey.name} crashing away", radius=8, kind="hunt", source=c.id)
    _startle(world, x, y, spared=prey.id)
    away = direction(prey.x - c.x, prey.y - c.y)
    return _busy(c, 2, f"hunting the {prey.name}",
                 f"You {throw} at the {prey.name} but miss. It bolts away {away}.")


def _hunt_fits(world: World, c: Creature) -> float | None:
    if _held_weapons(world, c) and find_object(world, c, "", kinds=_wild_kinds()):
        return 6.2
    return None


# ------------------------------------------------------------------ cooking and drying: what fits when
def _cook_fits(world: World, c: Creature) -> float | None:
    """Raw food in hand and a station beside you that turns it into a meal."""
    for r in world.catalog.recipes:
        if (r.station in COOK_STATIONS and world.catalog.items[r.output].food > 0
                and all(c.inventory.get(i, 0) >= n for i, n in r.inputs.items())
                and all(c.inventory.get(t, 0) > 0 for t in r.tools) and station_near(world, c, r.station)):
            return 5.0
    return None


def _dry_fits(world: World, c: Creature) -> float | None:
    if any(c.inventory.get(i, 0) > 0 for i in DRY_MAKES) and find_object(world, c, "", kinds={"drying_rack"}):
        return 4.8
    return None


def _rack_line(world: World, c: Creature) -> str | None:
    """Beside a drying rack with raw food on it: how far along it is, or that the weather keeps it wet."""
    for o, _, _ in visible_objects(world, c, 1):
        held = (o.data.get("items") or {}) if o.kind == "drying_rack" else {}
        raw = [i for i, n in held.items() if i in DRY_MAKES and n > 0]
        if raw:
            break
    else:
        return None
    names = _and([world.catalog.name(i) for i in raw])
    if _weather(world) in WET and world.under_sky(o.x, o.y):
        return f"The drying rack beside you is wet with {_weather(world)}: the {names} won't dry until it clears."
    done = min(o.data.get("drying", {}).get(i, 0) for i in raw) / DRY_TICKS
    how = "only just set out" if done < 1 / 3 else "half dry" if done < 2 / 3 else "nearly dry"
    return f"On the drying rack beside you, the {names} {'is' if len(raw) == 1 else 'are'} {how}."


def _dry(sim: Simulation, t: int) -> None:
    """Racks dry raw meat and fish in dry weather (faster in wind or heat, slower at night); the rain stops them. Below
    the sky no weather reaches a rack: it dries as on a still, dry day."""
    w = sim.world
    night = w.clock()["phase"] == "night"
    for rack in [o for o in w.objects.values() if o.kind == "drying_rack"]:
        weather = _weather(w) if w.under_sky(rack.x, rack.y) else "clear"
        if weather in WET:
            continue
        step = DRY_EVERY * (2 if weather in FAST else 1)
        if night:
            step //= 2
        items = rack.data.get("items") or {}
        drying = rack.data.get("drying", {})
        drying = {i: v for i, v in drying.items() if items.get(i, 0) > 0}
        done = []
        for item, n in list(items.items()):
            if item not in DRY_MAKES or n <= 0:
                continue
            drying[item] = drying.get(item, 0) + step
            if drying[item] >= DRY_TICKS:
                product = DRY_MAKES[item]
                del items[item], drying[item]
                items[product] = items.get(product, 0) + n
                done.append((item, n, product))
        rack.data["items"] = items
        if drying:
            rack.data["drying"] = drying
        else:
            rack.data.pop("drying", None)
        if done:
            w.changed_objects.add(rack.id)
            text = "; ".join(f"{w.catalog.name(i)} has dried into {n} {w.catalog.name(p)}" for i, n, p in done)
            w.emit("dry", None, rack.x, rack.y, f"On the drying rack, the {text}.")
            for h in w.creatures.values():
                if (not h.collapsed and dist(h.x, h.y, rack.x, rack.y) <= sight_range(w, h)
                        and w.same_region((h.x, h.y), (rack.x, rack.y))):
                    where = direction(rack.x - h.x, rack.y - h.y)
                    sim.remember(h, f"On the drying rack {where} of you, the {text}.", 1)


# ------------------------------------------------------------------ keeping: raw meat and fish spoil
def _age(held: dict, since: dict, t: int) -> list[tuple[str, int]]:
    """Age the raw food in one container (since: item -> tick it was first there); returns what spoiled now. A batch
    keeps the age of its oldest piece until the last of it is gone."""
    for item in [i for i in since if held.get(i, 0) <= 0]:
        del since[item]
    spoiled = []
    for item in PERISHABLE:
        n = held.get(item, 0)
        if n > 0 and t - since.setdefault(item, t) >= SPOILS_AFTER:
            spoiled.append((item, n))
            del since[item]
    return spoiled


def _went_bad(sim: Simulation, x: int, y: int, item: str, n: int, where: str) -> None:
    """Food left in a store or on the ground spoiled: an event, and a memory for those who see it (as _dry tells)."""
    w = sim.world
    name = w.catalog.name(item)
    what = name if n == 1 else f"{n} {name}"
    w.emit("spoil", None, x, y, f"The {what} {where} spoiled.")
    for h in w.creatures.values():
        d = dist(h.x, h.y, x, y)
        if not h.collapsed and d <= sight_range(w, h) and w.same_region((h.x, h.y), (x, y)):
            spot = "right here" if d == 0 else f"{direction(x - h.x, y - h.y)} of you"
            sim.remember(h, f"The {what} {where} {spot} went bad.", 1)


def _spoil(sim: Simulation, t: int) -> None:
    w = sim.world
    for c in w.creatures.values():
        if c.collapsed:
            continue
        if c.asleep:  # its mind is away and the body in stasis: its food keeps too
            for item in (c.ext.get(PACK) or {}).get("since", {}):
                c.ext[PACK]["since"][item] += SPOIL_EVERY
            continue
        if not any(c.inventory.get(i, 0) > 0 for i in PERISHABLE) and not (c.ext.get(PACK) or {}).get("since"):
            continue
        mine = _state(c)
        since, warned = mine.setdefault("since", {}), set(mine.get("warned", []))
        for item, n in _age(c.inventory, since, t):
            del c.inventory[item]
            warned.discard(item)
            name = w.catalog.name(item)
            w.emit("spoil", c.id, c.x, c.y, f"{c.name}'s {n} {name} spoiled.")
            what = name if n == 1 else f"{n} {name}"
            sim.remember(c, f"Your {what} went bad, and you threw it away. Raw meat and fish keep about two days: "
                            f"cook, smoke or dry them before then.", 2)
        for item, start in since.items():
            if t - start >= WARN_AFTER and item not in warned:
                warned.add(item)
                sim.remember(c, f"Your {w.catalog.name(item)} is starting to smell. Cook, smoke or dry it soon, or it "
                                f"will spoil.", 2)
        warned &= set(since)
        mine["warned"] = sorted(warned)
    for o in w.objects.values():
        if o.kind in STORES and o.kind != "drying_rack" and o.data.get("items"):
            since = o.data.setdefault("fresh_since", {})
            for item, n in _age(o.data["items"], since, t):
                del o.data["items"][item]
                w.changed_objects.add(o.id)
                _went_bad(sim, o.x, o.y, item, n, f"in the {o.name}")
            if not since:
                o.data.pop("fresh_since", None)
    piles = _state(w).setdefault("piles", {})
    for key in [k for k in piles if tuple(map(int, k.split(","))) not in w.ground]:
        del piles[key]
    for (x, y), pile in list(w.ground.items()):
        if any(pile.get(i, 0) > 0 for i in PERISHABLE) or f"{x},{y}" in piles:
            since = piles.setdefault(f"{x},{y}", {})
            for item, n in _age(dict(pile), since, t):
                w.take_items(x, y, item, n)
                _went_bad(sim, x, y, item, n, "on the ground")
            if not since:
                del piles[f"{x},{y}"]
    if not piles:
        _state(w).pop("piles", None)


# ------------------------------------------------------------------ wild game and forage: placing and coming back
def habitat_kinds() -> dict[str, dict]:
    return {k: spec["habitat"] for k, spec in KINDS.items() if spec.get("habitat")}


def population(world: World, kind: str) -> int:
    """How many of a kind a surface this size holds (its habitat's per_4096: per 64x64 tiles)."""
    x0, y0, x1, y1 = world.region_bounds("surface")
    return max(1, round(KINDS[kind]["habitat"]["per_4096"] * (x1 - x0) * (y1 - y0) / 4096))


def _fits(world: World, x: int, y: int, hab: dict, keep_off: int = 0) -> bool:
    cx, cy = world.center
    return (world.tile(x, y) in hab["tiles"] and (x, y) not in world.grid and world.walkable(x, y)
            and dist(x, y, cx, cy) >= hab.get("away", 0) and not world.occupied(x, y)
            and not any(not c.collapsed and dist(c.x, c.y, x, y) < keep_off for c in world.creatures.values()))


def _place(world: World, rng, kind: str, n: int, keep_off: int = 0, tries: int = 400) -> int:
    hab, placed = KINDS[kind]["habitat"], 0
    x0, y0, x1, y1 = world.region_bounds("surface")
    for _ in range(tries):
        if placed >= n:
            break
        x, y = rng.randrange(x0, x1), rng.randrange(y0, y1)
        if _fits(world, x, y, hab, keep_off):
            world.add_object(kind, x, y)
            placed += 1
    return placed


def _populate(world: World, rng, fresh: bool) -> None:
    """Game and forage in their habitats, once per world (new or restored): deer and boar in the woods, rabbits on the
    grass, mushrooms on the forest floor, herbs in the grass, all away from the meadow, on the surface."""
    mine = _state(world)
    if mine.get("placed"):
        return
    x0, y0, x1, y1 = world.region_bounds("surface")
    for kind, hab in habitat_kinds().items():
        spots = [(x, y) for y in range(y0, y1) for x in range(x0, x1) if _fits(world, x, y, hab)]
        for x, y in rng.sample(spots, min(population(world, kind), len(spots))):
            world.add_object(kind, x, y)
    mine["placed"] = True


def _wildlife(sim: Simulation, t: int) -> None:
    """Hunted game and picked mushrooms come back slowly, out of sight of anyone; mushrooms faster after rain."""
    w = sim.world
    counts = Counter(o.kind for o in w.objects.values())
    wet = _weather(w) in WET
    for kind, hab in habitat_kinds().items():
        if not hab.get("top_up"):
            continue
        n = hab["top_up"] * (hab.get("after_rain", 1) if wet else 1)
        missing = population(w, kind) - counts[kind]
        if missing > 0:
            _place(w, w.rng, kind, min(n, missing), keep_off=GAME_KEEPS_OFF if kind in ANIMALS else 0)


# ------------------------------------------------------------------ what the world already knows, told about food
actions.SOURCE_HINT.update({
    "meat": "hunt deer, rabbits or boar with a spear or sling", "hide": "it comes from hunted game",
    "bone": "it comes from hunted game", "mushroom": "they grow on the forest floor",
    "herbs": "they grow wild in the grass", "water_pot": "fill a clay pot at a well or the water's edge",
})
perception.REMEMBERED_KINDS.update({"well", "oven", "smoker", "drying_rack"})  # places worth walking back to

register_verb("hunt", _hunt, aliases=("go_hunting", "stalk", "hunt_game", "throw_spear"))
register_verb("fill", _fill, aliases=("fill_pot", "draw_water", "fetch_water", "fill_water"))
register_technique(Technique(
    "hunt", "hunt (target): hunt a deer, rabbit or boar in sight with your spear (3 steps) or sling and stones "
            "(5 steps) for raw meat, hide and bone. You may miss, and game bolts if you come near.", _hunt_fits))
register_technique(Technique(
    "fill", "fill (target): fill an empty pot at a well or the water's edge, to carry water and drink it later "
            "(drink), or to hold while you cook a stew.", _fill_fits))
register_technique(Technique(
    "cook", "combine (items): cook food you carry beside a burning campfire, an oven or a smoker. Cooked, smoked and "
            "dried food keeps; raw meat and fish spoil in about two days.", _cook_fits, ()))
register_technique(Technique(
    "drying rack", "store (target \"drying rack\", items): lay raw meat or fish on a drying rack; in dry weather it "
                   "becomes jerky or dried fish that keeps. Take it when it's done.", _dry_fits, ()))
register_system("food drying", DRY_EVERY, _dry)
register_system("food spoilage", SPOIL_EVERY, _spoil)
register_system("food wildlife", WILDLIFE_EVERY, _wildlife)
register_perception(_rack_line, priority=60)
register_perception(_fishing_line, priority=72)
register_populate("food game and forage", _populate)
