"""Building: tents, huts, storehouses, workshops, wells and bridges, raised from designs in
swarmworld/data/packs/building/designs.json.

- build (target) with a design's name lays out a construction site on clear land beside you (a bridge runs straight
  across the water from where you stand). Beside a site, build adds the materials you carry that it still needs and,
  once it has them all, a turn of work. Anyone may help; a site nobody touches for a few days falls apart and leaves
  its materials on the ground. Whatever else "build" names goes to craft, as the word did before this pack.
- When the work is done the site becomes the building: wall and door objects on the map, its furniture inside (a hut's
  bed, a storehouse's shelves, a workshop's workbench), and a record the viewer reads for floors and roofs
  (World.building_dicts). A well is the food pack's well; a bridge is a row of spans you can walk on over deep water.
- Inside a roofed building you're out of the rain and cold: this pack provides perception.roof_over, which
  Simulation.exposure, the "soaked and shivering" line and station_near (a bed inside serves those inside) ask.
- Two perception lines: what the site beside you still needs (when you come to it, or it changed), and that you're
  inside, with what's in there (when you come in, it changed, or the weather outside makes it matter).

State: world.ext["building"] = {"sites": {marker object id: site}, "built": {building id: building}}, where a site
and a building are rectangles of tiles (x0, y0, x1, y1, inclusive); c.ext["building"] holds what the lines last said.
World systems here never act for a creature: they keep insects off sites and floors and clear away what's gone."""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import replace
from typing import TYPE_CHECKING

from .. import perception
from ..actions import FILLER, SOURCE_HINT, ActionResult, Intention, start_walk
from ..catalog import DATA
from ..model import DAY_TICKS, WATER_TILES, wet
from ..perception import article, dist, direction, sight_range
from ..registry import (ANIMALS, BLOCKING, HANDLERS, KINDS, STORES, Technique, register_perception, register_shift_hook,
                        register_system, register_technique, register_verb)

if TYPE_CHECKING:  # never at the top for real: simulation imports the packs (see registry.py)
    from ..model import Creature, World
    from ..simulation import Simulation

PACK = "building"
DESIGNS: dict[str, dict] = {k: v for k, v in json.loads((DATA / "packs" / PACK / "designs.json").read_text()).items()
                            if not k.startswith("_")}
SITE_KIND = "building_site"
REACH = 1  # at a site: within this many steps of its footprint
PLOT_REACH = 2  # a new site is laid out at most this many steps from you
ADD_TICKS, WORK_TICKS = 2, 8  # busy for this long after bringing materials, after a turn of work
WORK_ENERGY = 2
STALE_TICKS = 3 * DAY_TICKS  # a site nobody has touched for this long falls apart
UPKEEP_EVERY = 50
STRAND_REACH = 8  # a creature left on deep water finds land within this many steps (half the longest bridge, and more)
MATERIALS = {i for d in DESIGNS.values() for i in d["needs"]} - {"stick", "stone", "plant_fiber", "rope"}  # say "build"
SITE_WORDS = {"", "site", "building site", "construction site", "construction", "building", "frame", "foundation",
              "it", "work"}
CUT = re.compile(r"\b(?:at|near|by|beside|for|to|with|in|on|across|over|next|along|from|of)\b")


# ------------------------------------------------------------------ state and geometry
def _state(world: World) -> dict:
    return world.ext.setdefault(PACK, {})


def sites(world: World) -> dict[str, dict]:
    """Construction sites, by the id of their marker object."""
    return _state(world).setdefault("sites", {})


def buildings(world: World) -> dict[str, dict]:
    """What stands, by building id."""
    return _state(world).setdefault("built", {})


def _read(world: World, what: str) -> dict:
    """sites or built, for reading: a world from before this pack has neither, and reading doesn't add them."""
    return (world.ext.get(PACK) or {}).get(what) or {}


def _mine(c: Creature) -> dict:
    return c.ext.setdefault(PACK, {})


def rect_dist(r: dict, x: int, y: int) -> int:
    """Steps from (x, y) to the nearest tile of a site's or building's rectangle (0 on it)."""
    return max(r["x0"] - x, 0, x - r["x1"], r["y0"] - y, 0, y - r["y1"])


def _tiles(r: dict) -> list[tuple[int, int]]:
    return [(x, y) for y in range(r["y0"], r["y1"] + 1) for x in range(r["x0"], r["x1"] + 1)]


def _rect(x0: int, y0: int, w: int, h: int) -> dict:
    return {"x0": x0, "y0": y0, "x1": x0 + w - 1, "y1": y0 + h - 1}


def _touches(a: dict, b: dict, margin: int = 1) -> bool:
    return not (a["x1"] + margin < b["x0"] or b["x1"] + margin < a["x0"] or a["y1"] + margin < b["y0"]
                or b["y1"] + margin < a["y0"])


def _footprints(world: World) -> list[dict]:
    return list(_read(world, "sites").values()) + list(_read(world, "built").values())


def _insect(kind: str) -> bool:
    """Bees, butterflies and fireflies (the nature pack's): they flit off wherever something is built."""
    return "insect" in KINDS.get(kind, {}).get("aliases", ())


def _shoo_insects(world: World, r: dict) -> None:
    for x, y in _tiles(r):
        o = world.object_at(x, y)
        if o and _insect(o.kind):
            world.remove_object(o.id)


def roof_over(world: World, x: int, y: int) -> str | None:
    """The roofed building whose inside (x, y) is (not its walls or doorway), or None: perception.roof_over."""
    for bid, b in _read(world, "built").items():
        if b["roof"] and b["x0"] < x < b["x1"] and b["y0"] < y < b["y1"]:
            return bid
    return None


def floor_at(world: World, x: int, y: int) -> str | None:
    """Inside a building (not its walls or doorway): its floor, "the hut's earthen floor"; perception.floor_at."""
    for b in _read(world, "built").values():
        d = DESIGNS.get(b["design"], {})
        if d.get("floor") and b["x0"] < x < b["x1"] and b["y0"] < y < b["y1"]:
            return f"the {d['name']}'s {d['floor']}"
    return None


perception.roof_over = roof_over
perception.floor_at = floor_at


# ------------------------------------------------------------------ words
def _and(words: list[str]) -> str:
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]


def _items(world: World, items: dict) -> str:
    return _and([f"{n} {world.catalog.name(i)}" for i, n in items.items() if n > 0]) if items else "nothing"


def _names(names: list[str]) -> str:
    return _and(list(names)) if names else "someone"


def _phrase(text: str) -> str:
    return " " + " ".join(w for w in re.findall(r"[a-z]+", text.lower().replace("-", " ")) if w not in FILLER) + " "


def _design_in(text: str) -> str | None:
    """The design a phrase names ("a small hut" -> hut), the first one if it names several."""
    t = _phrase(text)
    found = []
    for key, d in DESIGNS.items():
        for name in (key, d["name"], *d["aliases"]):
            at = t.find(_phrase(name))
            if at >= 0:
                found.append((at, key))
    return min(found)[1] if found else None


def design_for(world: World, target: str) -> str | None:
    """The design a build target means, or None when it names something else (that's craft's). "campfire at home"
    is a campfire: what comes before at, by, for... is the thing; and a thing that's an item is that item, unless the
    item is what the design makes (a well)."""
    head = CUT.split(target.lower(), maxsplit=1)[0]
    key = _design_in(head)
    item = world.catalog.resolve(head)
    if item and not (key and item in _products(key)):
        return None
    return key


def _products(key: str) -> set[str]:
    return {spec["kind"] for spec in DESIGNS[key].get("legend", {}).values()}


def _missing(site: dict) -> dict[str, int]:
    return {i: n - site["have"].get(i, 0) for i, n in site["needs"].items() if n > site["have"].get(i, 0)}


def _hints(world: World, c: Creature, items: dict) -> str:
    out = []
    for i in list(items)[:2]:
        name = world.catalog.name(i).capitalize()
        if i in SOURCE_HINT:
            out.append(f"{name}: {SOURCE_HINT[i]}.")
        elif i in c.known_recipes:
            out.append(f"{name}: you know how to make it.")
    return (" " + " ".join(out)) if out else ""


def _turns(n: int) -> str:
    return "1 more turn" if n == 1 else f"{n} more turns"


def _work(n: int) -> str:
    return "1 turn of work" if n == 1 else f"{n} turns of work"


def _status(world: World, site: dict) -> str:
    """What a site still needs: "still needs 2 thatch, then 4 turns of work" or "has all it needs; 3 more turns..."."""
    missing = _missing(site)
    left = site["work"] - site["done"]
    if missing:
        return f"still needs {_items(world, missing)}, then {_work(left)}"
    return f"has all it needs; {_turns(left)} of work (build) will finish it"


def _label(world: World, site: dict) -> str:
    name = DESIGNS[site["design"]]["name"]
    missing = _missing(site)
    if missing:
        return f"{name} site (needs {_items(world, missing).replace(' and ', ', ')})"
    left = site["work"] - site["done"]
    return f"{name} site ({left} turn{'s' if left != 1 else ''} of work left)"


def _size(site: dict) -> str:
    return f"{site['x1'] - site['x0'] + 1} by {site['y1'] - site['y0'] + 1} steps"


def designs_text(world: World) -> str:
    parts = []
    for key, d in DESIGNS.items():
        if d.get("over_water"):
            parts.append(f"{d['about']} ({_items(world, d['needs'])} for each step of water)")
        else:
            parts.append(f"{d['about']} ({_items(world, d['needs'])}; {_work(d['work'])})")
    return "You could build " + "; ".join(parts[:-1]) + "; or " + parts[-1] + ". Name one, standing beside clear land."


def _update_marker(world: World, sid: str, site: dict) -> None:
    marker = world.objects.get(sid)
    if marker is None:
        return
    have = sum(min(site["have"].get(i, 0), n) for i, n in site["needs"].items()) / max(1, sum(site["needs"].values()))
    marker.data["label"] = _label(world, site)
    marker.data["stage"] = min(3, int(2 * (have + site["done"] / site["work"])))
    world.changed_objects.add(sid)


# ------------------------------------------------------------------ finding a site and laying one out
def _site_near(world: World, c: Creature, key: str | None = None) -> tuple[str, dict] | None:
    """The site you'd mean: one within reach, else the nearest in sight (of the design named, if one is)."""
    r = sight_range(world, c)
    best = None
    for sid, site in _read(world, "sites").items():
        if sid not in world.objects or (key and site["design"] != key):
            continue
        d = rect_dist(site, c.x, c.y)
        if d <= max(r, REACH) and (best is None or d < best[0]):
            best = (d, sid, site)
    return (best[1], best[2]) if best else None


def _clear(world: World, rect: dict, others: list[dict]) -> bool:
    for x, y in _tiles(rect):
        if not world.in_bounds(x, y) or world.tile(x, y) in "wW":
            return False
        o = world.object_at(x, y)
        if (o and not _insect(o.kind)) or any(c.x == x and c.y == y for c in world.creatures.values()):
            return False
    return not any(_touches(rect, r) for r in others)


def _plot(world: World, c: Creature, d: dict) -> dict | None:
    """Where a design fits beside you: clear land, apart from other buildings, the door opening onto open ground;
    the one whose doorstep is nearest you."""
    rows = d["layout"]
    h, w = len(rows), len(rows[0])
    door = next(((i, j) for j, row in enumerate(rows) for i, ch in enumerate(row) if ch == "D"), None)
    others = _footprints(world)
    best = None
    for y0 in range(c.y - h - PLOT_REACH + 1, c.y + PLOT_REACH + 1):
        for x0 in range(c.x - w - PLOT_REACH + 1, c.x + PLOT_REACH + 1):
            rect = _rect(x0, y0, w, h)
            near = rect_dist(rect, c.x, c.y)
            if not 1 <= near <= PLOT_REACH or not _clear(world, rect, others):
                continue
            step = None
            if door:
                step = (x0 + door[0], y0 + door[1] + 1)
                if not world.walkable(*step) or any(rect_dist(r, *step) == 0 for r in others):
                    continue
            key = (dist(c.x, c.y, *step) if step else near, near, y0, x0)
            if best is None or key < best[0]:
                best = (key, rect, [x0 + door[0], y0 + door[1]] if door else None)
    if best is None:
        return None
    rect = best[1]
    rect["door"] = best[2]
    return rect


def _crossing(world: World, c: Creature, d: dict) -> tuple[dict | None, str]:
    """A straight run of water from where you stand to walkable land on the far side, or why there's none."""
    longest = d.get("max_length", 8)
    others = _footprints(world)
    best, why = None, ""
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        run, x, y = [], c.x + dx, c.y + dy
        while world.in_bounds(x, y) and world.tile(x, y) in "wW" and len(run) <= longest:
            run.append((x, y))
            x, y = x + dx, y + dy
        if not run:
            continue
        way = direction(dx, dy)
        if len(run) > longest:
            why = why or (f"The water runs on for more than {longest} steps {way} of you; a bridge spans at most "
                          f"{longest}.")
        elif not world.walkable(x, y):
            why = why or f"There's no clear bank to land on across the water to the {way}."
        elif all(world.tile(*p) == "w" for p in run):
            why = why or f"The water to the {way} is shallow enough to wade; a bridge is for deep water."
        elif any(world.object_at(*p) for p in run) or any(rect_dist(r, *p) == 0 for r in others for p in run):
            why = why or f"Something is already in the water to the {way}."
        elif best is None or len(run) < len(best[0]):
            best = (run, way)
    if best is None:
        return None, why or ("Stand at the water's edge to build a bridge: it runs straight north, south, east or "
                             "west from where you stand to the far bank.")
    run, way = best
    xs, ys = [p[0] for p in run], [p[1] for p in run]
    return {"x0": min(xs), "y0": min(ys), "x1": max(xs), "y1": max(ys), "door": None, "start": list(run[0]),
            "way": way}, ""


def _lay_out(world: World, c: Creature, key: str) -> ActionResult:
    d = DESIGNS[key]
    if world.region_at(c.x, c.y) is not world.region("surface"):
        return ActionResult(False, "There's no room to raise a building down here; build up on the surface.")
    for sid, site in _read(world, "sites").items():
        if site.get("started_by") == c.id and sid in world.objects:
            where = _where(c, site)
            return ActionResult(False, f"You've already marked out a {DESIGNS[site['design']]['name']} site {where}; "
                                       f"finish it first (others can help), then start another.")
    if d.get("over_water"):
        rect, why = _crossing(world, c, d)
        if rect is None:
            return ActionResult(False, why)
        length = max(rect["x1"] - rect["x0"], rect["y1"] - rect["y0"]) + 1
        needs = {i: n * length for i, n in d["needs"].items()}
        work = d["work"] * length
        marker_at = tuple(rect.pop("start"))
        way = rect.pop("way")
        laid = f"You mark out a {d['name']} {length} steps long, straight {way} across the water to the far bank."
    else:
        rect = _plot(world, c, d)
        if rect is None:
            rows = d["layout"]
            return ActionResult(False, f"There's no room for a {d['name']} beside you: it needs clear, dry land "
                                       f"{len(rows[0])} by {len(rows)} steps, with nothing on it and a step apart from "
                                       f"other buildings. Try more open ground.")
        needs, work = dict(d["needs"]), d["work"]
        marker_at = tuple(rect["door"]) if rect["door"] else (rect["x0"], rect["y0"])
        where = direction((rect["x0"] + rect["x1"]) // 2 - c.x, (rect["y0"] + rect["y1"]) // 2 - c.y)
        door = "; its door will face south" if rect["door"] else ""
        laid = f"You mark out {article(d['name'])} {d['name']}, {_size(rect)}, just {where} of you{door}."
    _shoo_insects(world, rect)
    site = {**rect, "design": key, "needs": needs, "have": {}, "work": work, "done": 0, "by": [],
            "started_by": c.id, "touched": world.tick}
    marker = world.add_object(SITE_KIND, *marker_at, design=key, builder=c.name)
    sites(world)[marker.id] = site
    given = _deliver(c, site)
    _update_marker(world, marker.id, site)
    world.emit("place", c.id, *marker_at, f"{c.name} marked out {article(d['name'])} {d['name']} site.",
               object_kind=SITE_KIND, design=key)
    world.sound(*marker_at, "stakes being knocked into the ground", radius=6, kind="build", source=c.id)
    msg = f"{laid} It needs {_items(world, needs)}, then {_work(work)}."
    if given:
        msg += f" You set down your {_items(world, given)}."
    missing = _missing(site)
    if missing and given:
        msg += f" Still needed: {_items(world, missing)}."
    msg += " Build beside it to add materials and work; anyone can help."
    return _busy(c, ADD_TICKS, f"marking out a {d['name']}", msg)


def _where(c: Creature, r: dict) -> str:
    x, y = (r["x0"] + r["x1"]) // 2, (r["y0"] + r["y1"]) // 2
    d = dist(c.x, c.y, x, y)
    return "right here" if d <= 2 else f"{d} steps {direction(x - c.x, y - c.y)}"


def _busy(c: Creature, ticks: int, label: str, result: str) -> ActionResult:
    c.activity = {"type": "busy", "ticks": max(1, ticks), "label": label, "result": result}
    return ActionResult(True, result, instant=False)


# ------------------------------------------------------------------ helping: materials and work
def _deliver(c: Creature, site: dict) -> Counter:
    given: Counter = Counter()
    for item, n in _missing(site).items():
        k = min(n, c.inventory.get(item, 0))
        if k > 0:
            c.inventory[item] -= k
            if c.inventory[item] <= 0:
                del c.inventory[item]
            site["have"][item] = site["have"].get(item, 0) + k
            given[item] = k
    if given and c.name not in site["by"]:
        site["by"].append(c.name)
    return given


def _help(world: World, c: Creature, sid: str, site: dict, it: Intention) -> ActionResult:
    name = DESIGNS[site["design"]]["name"]
    if rect_dist(site, c.x, c.y) > REACH:
        goals = {(x, y) for x in range(site["x0"] - 1, site["x1"] + 2) for y in range(site["y0"] - 1, site["y1"] + 2)
                 if rect_dist(site, x, y) == 1 and world.walkable(x, y)}
        res = start_walk(world, c, goals, f"walking to the {name} site", f"You reach the {name} site.")
        if c.activity:
            c.activity["then"] = it
        return res
    given = _deliver(c, site)
    missing = _missing(site)
    site["touched"] = world.tick
    if missing:
        _update_marker(world, sid, site)
        if not given:
            return ActionResult(False, f"The {name} site still needs {_items(world, missing)}, and you carry none "
                                       f"of it.{_hints(world, c, missing)}")
        world.emit("build", c.id, c.x, c.y, f"{c.name} brought {_items(world, given)} to the {name} site.")
        return _busy(c, ADD_TICKS, f"bringing materials to the {name} site",
                     f"You add {_items(world, given)} to the {name} site. It still needs {_items(world, missing)}.")
    if c.name not in site["by"]:
        site["by"].append(c.name)
    site["done"] += 1
    c.energy = max(0.0, c.energy - WORK_ENERGY)
    world.sound(c.x, c.y, "hammering and sawing", radius=8, kind="build", source=c.id)
    lead = f"You add {_items(world, given)} to the {name} site; now it has everything. " if given else ""
    if site["done"] >= site["work"]:
        return _busy(c, WORK_TICKS, f"finishing the {name}", lead + _complete(world, sid, site, c))
    _update_marker(world, sid, site)
    world.emit("build", c.id, c.x, c.y, f"{c.name} worked on the {name} site.")
    left = _turns(site["work"] - site["done"])
    return _busy(c, WORK_TICKS, f"building the {name}", f"{lead}You work on the {name}: {left} of work will finish it.")


# ------------------------------------------------------------------ the finished building
def _plan(site: dict) -> dict[tuple[int, int], dict]:
    """What goes where: tile -> {"kind", "label"?}."""
    d = DESIGNS[site["design"]]
    if d.get("over_water"):
        return {p: {"kind": d["kind"]} for p in _tiles(site)}
    return {(site["x0"] + i, site["y0"] + j): d["legend"][ch] for j, row in enumerate(d["layout"])
            for i, ch in enumerate(row) if ch != "."}


def _free_spot(world: World, x: int, y: int, avoid: set, r: int = 4) -> tuple[int, int] | None:
    for k in range(1, r + 1):
        ring = [(x + dx, y + dy) for dx in range(-k, k + 1) for dy in range(-k, k + 1) if max(abs(dx), abs(dy)) == k]
        for p in sorted(ring, key=lambda p: (abs(p[0] - x) + abs(p[1] - y), p[1], p[0])):
            if p not in avoid and world.walkable(*p) and world.tile(*p) not in WATER_TILES and not world.object_at(*p) \
                    and not any(c.x == p[0] and c.y == p[1] for c in world.creatures.values()):
                return p
    return None


def _step_aside(world: World, c: Creature, spot: tuple[int, int], why: str) -> None:
    """Move a creature out of the way and tell it (the "building news" system remembers it for them)."""
    c.x, c.y = spot
    if (c.activity or {}).get("type") == "walk":
        c.activity = None
    _state(world).setdefault("news", {}).setdefault(c.id, []).append(why)


def _clear_the_way(world: World, plan: dict, rect: dict) -> set[tuple[int, int]]:
    """Insects flit off, animals are shooed out, and creatures, things and piles in the way of a wall move aside.
    Returns the tiles where something wouldn't budge (the building goes up around it)."""
    _shoo_insects(world, rect)
    inside = set(_tiles(rect))
    for x, y in inside:  # an animal would be shut in (animals don't pass doors): out it goes
        o = world.object_at(x, y)
        spot = _free_spot(world, x, y, inside) if o and o.kind in ANIMALS else None
        if spot:
            world.move_object(o, *spot)
    solid = {p for p, spec in plan.items() if spec["kind"] in BLOCKING}
    avoid = set(plan)
    stuck = set()
    for c in world.creatures.values():
        if (c.x, c.y) in solid:
            spot = _free_spot(world, c.x, c.y, avoid)
            if spot:
                _step_aside(world, c, spot, "You step aside as the walls go up.")
    for p in plan:
        o = world.object_at(*p)
        if o and o.kind != SITE_KIND:
            spot = _free_spot(world, *p, avoid)
            if not (spot and world.move_object(o, *spot)):
                stuck.add(p)
        if p in solid and p in world.ground:
            spot = _free_spot(world, *p, avoid)
            if spot:
                pile = world.ground.pop(p)
                world.changed_objects.discard(f"pile:{p[0]}:{p[1]}")
                world.removed_objects.add(f"pile:{p[0]}:{p[1]}")
                world.drop_items(*spot, pile)
    return stuck


def _complete(world: World, sid: str, site: dict, c: Creature) -> str:
    key = site["design"]
    d = DESIGNS[key]
    plan = _plan(site)
    world.remove_object(sid)
    stuck = _clear_the_way(world, plan, site)
    bid = world.new_id("b")
    pieces, furniture = [], []
    for (x, y), spec in plan.items():
        if (x, y) in stuck:
            continue
        data = {"builder": site["by"][0] if site["by"] else c.name, "building": bid}
        if spec.get("label"):
            data["label"] = spec["label"]
        if spec["kind"] in STORES:
            data["items"] = {}
        obj = world.add_object(spec["kind"], x, y, **data)
        inner = site["x0"] < x < site["x1"] and site["y0"] < y < site["y1"]
        (furniture if inner else pieces).append(obj.id)
    buildings(world)[bid] = {"design": key, "x0": site["x0"], "y0": site["y0"], "x1": site["x1"], "y1": site["y1"],
                             "door": site["door"], "roof": bool(d["roof"]), "by": list(site["by"]),
                             "tick": world.tick, "pieces": pieces, "furniture": furniture}
    del sites(world)[sid]
    world.buildings_changed = True
    for other in world.creatures.values():
        if other.name in site["by"]:
            other.stats["built"] += 1
    cx, cy = (site["x0"] + site["x1"]) // 2, (site["y0"] + site["y1"]) // 2
    world.emit("place", c.id, cx, cy, f"{_names(site['by'])} finished building {article(d['name'])} {d['name']}.",
               object_kind=key, building=bid)
    inside = [world.objects[o].name for o in furniture]
    if d.get("over_water"):
        return (f"You finish the {d['name']}! {_names(site['by'])} built it, and now anyone can walk across the "
                f"water here.")
    if not d["roof"]:
        return f"You finish the {d['name']}! {_names(site['by'])} built it."
    has = f", {_and([f'{article(n)} {n}' for n in inside])} inside" if inside else ""
    return (f"You finish the {d['name']}! {_names(site['by'])} built it: walls, a door to the south{has}. "
            f"Inside it you're out of the rain and the cold.")


# ------------------------------------------------------------------ the verb
def _build(world: World, c: Creature, it: Intention) -> ActionResult:
    named = it.target.strip()
    if _phrase(named).strip() in SITE_WORDS:  # "build" beside a site, or "build site": work on it
        near = _site_near(world, c)
        if near:
            return _help(world, c, *near, it)
    target = named or (it.items[0] if it.items else "")
    key = design_for(world, target)
    if key is None:
        if _phrase(target).strip() in SITE_WORDS:
            if not named:
                return ActionResult(False, f"Build what? {designs_text(world)}")
            return ActionResult(False, f"There's no building site in sight. {designs_text(world)}")
        return HANDLERS["craft"](world, c, it)
    if "well" in _products(key) and c.inventory.get("well", 0) > 0:  # a well already made: set it down
        return HANDLERS["place"](world, c, replace(it, action="place", target="well", items=[]))
    near = _site_near(world, c, key)
    if near:
        return _help(world, c, *near, it)
    return _lay_out(world, c, key)


def _ready(world: World, c: Creature) -> bool:
    return any(not d.get("over_water") and all(c.inventory.get(i, 0) >= n for i, n in d["needs"].items())
               for d in DESIGNS.values())


def _build_fits(world: World, c: Creature) -> float | None:
    if _site_near(world, c):
        return 6.4
    if _ready(world, c):
        return 5.6
    if any(c.inventory.get(i, 0) > 0 for i in MATERIALS):
        return 3.4
    if (c.persona or {}).get("drive") == "builder":
        return 2.8
    return None


# ------------------------------------------------------------------ perception
def _contents(world: World, b: dict) -> str:
    things = []
    for x, y in _tiles(b):
        if not (b["x0"] < x < b["x1"] and b["y0"] < y < b["y1"]):
            continue
        o = world.object_at(x, y)
        if o and not _insect(o.kind):
            held = o.data.get("items") if o.kind in STORES else None
            if o.kind in STORES:
                things.append(f"{article(o.name)} {o.name} holding {_items(world, held)}" if held
                              else f"an empty {o.name}")
            else:
                things.append(f"{article(o.name)} {o.name}")
        pile = world.ground.get((x, y))
        if pile:
            things.append(f"{_items(world, dict(pile))} on the floor")
    return _and(things) if things else ""


def _cozy(world: World) -> str:
    weather = getattr(world, "weather", "clear")
    if weather == "storm":
        return "The storm rages outside, but you're dry in here."
    if wet(world, drizzle=True):
        return "Rain drums on the roof, but you're dry in here."
    if world.clock()["phase"] == "night":
        return "The night is cold outside, but it's sheltered in here."
    return "It's dry and out of the wind in here."


def inside_line(world: World, c: Creature) -> str | None:
    """You're inside: said when you come in or what's in there changed, and every turn the weather makes it matter."""
    bid = roof_over(world, c.x, c.y)
    if bid is None:
        if (c.ext.get(PACK) or {}).get("inside"):
            del c.ext[PACK]["inside"]
        return None
    b = buildings(world)[bid]
    what = _contents(world, b)
    line = (f"You're inside the {DESIGNS[b['design']]['name']} {_names(b['by'])} built"
            f"{', with ' + what if what else ''}. {_cozy(world)}")
    matters = wet(world, drizzle=True) or world.clock()["phase"] == "night"
    mine = _mine(c)
    if mine.get("inside") == line and not matters:
        return None
    mine["inside"] = line
    return line


def site_line(world: World, c: Creature) -> str | None:
    """The site beside you and what it still needs: when you come to it, and when that changed."""
    near = _site_near(world, c)
    mine = c.ext.get(PACK) or {}
    if near is None or rect_dist(near[1], c.x, c.y) > REACH:
        mine.pop("site", None)
        return None
    sid, site = near
    told = f"{sid}:{sorted(site['have'].items())}:{site['done']}"
    if mine.get("site") == told:
        return None
    _mine(c)["site"] = told
    return f"The {DESIGNS[site['design']]['name']} site beside you {_status(world, site)}."


# ------------------------------------------------------------------ upkeep
def _abandon(sim: Simulation, sid: str, site: dict) -> None:
    w = sim.world
    marker = w.objects.get(sid)
    x, y = (marker.x, marker.y) if marker else (site["x0"], site["y0"])
    if marker:
        w.remove_object(sid)
    if site["have"]:
        w.drop_items(x, y, Counter(site["have"]))
    del sites(w)[sid]
    name = DESIGNS[site["design"]]["name"]
    left = f"; its {_items(w, site['have'])} lie on the ground" if site["have"] else ""
    w.emit("build", None, x, y, f"The unfinished {name} site, untouched for days, has fallen apart{left}.")
    for c in w.creatures.values():
        if c.name in site["by"] or c.id == site.get("started_by"):
            sim.remember(c, f"The {name} site you worked on, left untouched for days, has fallen apart{left}.", 2)


def _news(sim: Simulation, t: int) -> None:
    """What happened to creatures because of a building (moved aside as its walls went up), remembered by them."""
    news = (sim.world.ext.get(PACK) or {}).pop("news", None)
    for cid, texts in (news or {}).items():
        c = sim.world.creatures.get(cid)
        for text in texts if c else ():
            sim.remember(c, text, 1)


def _unstrand(sim: Simulation) -> None:
    """Nobody stays where no one can stand (a bridge span taken away from under them): to the nearest open land."""
    w = sim.world
    for c in w.creatures.values():
        if c.collapsed or w.walkable(c.x, c.y):  # a collapsed body is moved when it comes round (Simulation._respawn)
            continue
        spot = _free_spot(w, c.x, c.y, set(), r=STRAND_REACH)
        if spot:
            water = w.tile(c.x, c.y) == "W"
            _step_aside(w, c, spot, "The bridge under you is gone; you scramble out of the deep water." if water
                        else "You squeeze out onto open ground.")
    _news(sim, w.tick)


def _upkeep(sim: Simulation, t: int) -> None:
    """Sites nobody tends fall apart; insects flit off sites and floors; a building mostly taken down is gone; whoever
    is left where no one can stand moves to open land."""
    w = sim.world
    st = w.ext.get(PACK)
    if not st:
        return
    _unstrand(sim)
    for sid, site in list(st.get("sites", {}).items()):
        if sid not in w.objects or t - site.get("touched", t) >= STALE_TICKS:
            _abandon(sim, sid, site)
        else:
            _shoo_insects(w, site)
    for bid, b in list(st.get("built", {}).items()):
        standing = [oid for oid in b["pieces"] if oid in w.objects]
        if 2 * len(standing) < len(b["pieces"]):
            for oid in standing + [o for o in b["furniture"] if o in w.objects]:
                w.objects[oid].data.pop("building", None)
            del st["built"][bid]
            w.buildings_changed = True
        elif b["roof"]:
            _shoo_insects(w, {"x0": b["x0"] + 1, "y0": b["y0"] + 1, "x1": b["x1"] - 1, "y1": b["y1"] - 1})


perception.REMEMBERED_KINDS.update({SITE_KIND, "shelves", "bridge"})  # places worth walking back to

register_verb("build", _build, aliases=("construct",), replaces_alias=True)
register_technique(Technique(
    "build", "build (target): lay out a tent, hut, storehouse, workshop, well or bridge beside you, then build beside "
             "the site to bring what it needs and to work on it; anyone can help. Build alone lists what each needs.",
    _build_fits))
register_system("building upkeep", UPKEEP_EVERY, _upkeep)
register_system("building news", 1, _news)
register_perception(inside_line, priority=46)
register_perception(site_line, priority=47)


def _shift(world: World, n: int) -> None:
    """New land in the west: every site and building (x0..x1, door, start) moves n east."""
    for rec in list(_read(world, "sites").values()) + list(_read(world, "built").values()):
        rec["x0"] += n
        rec["x1"] += n
        for k in ("door", "start"):
            if rec.get(k):
                rec[k] = [rec[k][0] + n, *rec[k][1:]]


register_shift_hook("building", _shift, stores=("ext.building.sites", "ext.building.built"))
