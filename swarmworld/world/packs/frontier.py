"""The frontier: new land laid down at the map's east and west edges, a strip at a time
(docs/superpowers/specs/2026-11-03-frontier-design.md).

A strip is `strip` columns wide (32) and as tall as the surface, cut into lands strip x strip (the last one shorter
when the surface's height isn't a multiple of it). Each land comes from swarmworld/world/lands.py, fitted to the old
edge and to the land above it, and the packs' land hooks then fill it. The rock band and the deep get rock. At most
one strip every `pace` ticks, world-wide, and never wider than `cap` (World.frontier_settings, which the server sets
at every start: --frontier on|off). A strip to the west moves the whole world east by its width (World.shift_x).

State, world.ext["frontier"] (saved), made at the first growth:
  {"origin_x", "home_width" (World.frontier_record), "seed", "strip", "strips": {"east": n, "west": n},
   "last_grow": tick or None, "failed": tick of the last growth that failed (taken back), if any,
   "lands": {"lx,ly": {"theme", "side", "heart": [hx, hy] (inside the land), "name", "found_by", "tick"}}}
lx counts strips out from the home lands (east 1, 2...; west -1, -2...), ly lands down from the surface's top row.
They count from the home lands, so a shift never moves them. `strip` is the one the first growth used, from then on.

Nothing here rolls the world's dice: each land, and the filling of it, has a random.Random of its own, seeded from the
frontier seed and the land's place. A growth that fails half-way is taken back whole, and nothing grows."""

from __future__ import annotations

import copy
import logging
import random
import traceback
import zlib
from typing import TYPE_CHECKING

from .. import actions, lands
from ..actions import ActionResult, Intention, bfs_path, start_walk
from ..model import DAY_TICKS
from ..perception import sight_range
from ..registry import register_landmarks, register_perception, register_system, run_populate_land

if TYPE_CHECKING:
    from ..model import Creature, World

PACK = "frontier"
SIDES = ("east", "west")
log = logging.getLogger("swarmworld.packs")

EDGE_NEAR = 24   # within this many steps of a growable edge, exploring toward it walks there (an explorer: from anywhere)
FAIL_HOLD = 300  # a failed growth is not tried again for this many ticks, whatever the pace
EDGE_REACH = 1   # this close counts as at the edge
WALK_ON = 6      # after laying land, the explorer walks this many columns into it
SIDE_DIRS = {"east": ("east", "northeast", "southeast"), "west": ("west", "northwest", "southwest")}
EDGE_LINE = "To the {side} the land fades into unknown country; exploring might reveal more."
ANOTHER_DAY = "The unknown country beyond looks hard going; perhaps another day."
HEAD_TO_EDGE = "You head off {d}, toward the edge of the known land."
REACH_EDGE = "You reach the edge of the known land to the {side}."
NEW_COUNTRY = "New country opens before you to the {side}."
ON_INTO = "New country opens before you to the {side}; you walk on into it."
FOUND = "You found new country to the {side}: {label}. From now on it is {name}."
LAND_EVENT = "{who} found new country to the {side}: {label}. It is {name} now."
PULL = "The unknown country to the {side} calls to you, some {d} steps away: explore {side} to go and see."


def _side(side: str) -> str:
    if side not in SIDES:
        raise ValueError(f"new land goes to the east or the west, not {side!r}")
    return side


def _strip(world: World) -> int:
    return (world.ext.get(PACK) or {}).get("strip") or world.frontier_settings.strip


def frontier_seed(world: World) -> int:
    """The seed every land is made from: the one in the record, else the world's, else read from the home lands'
    surface (a save without a seed)."""
    rec = world.ext.get(PACK) or {}
    if "seed" in rec:
        return rec["seed"]
    if world.seed is not None:
        return world.seed
    x0, y0, x1, y1 = world.home_bounds()
    return zlib.crc32("\n".join("".join(world.tiles[y][x0:x1]) for y in range(y0, y1)).encode())


def why_not_grow(world: World, side: str) -> str | None:
    """Why no strip may be laid to this side now: "off", "cap" (it would make the map wider than the cap) or "pace"
    (one was laid less than `pace` ticks ago); None when one may."""
    _side(side)
    settings = world.frontier_settings
    if not settings.on:
        return "off"
    if world.width + _strip(world) > settings.cap:
        return "cap"
    rec = world.ext.get(PACK) or {}
    for key, hold in (("last_grow", settings.pace), ("failed", max(settings.pace, FAIL_HOLD))):
        was = rec.get(key)  # a failed growth holds the next try back as long as a laid one (at least FAIL_HOLD)
        if was is not None and world.tick - was < hold:
            return "pace"
    return None


def _rect(world: World, lx: int, ly: int, strip: int) -> tuple[int, int, int, int]:
    s = world.region("surface")
    x0 = world.origin_x + world.home_width + (lx - 1) * strip if lx > 0 else world.origin_x + lx * strip
    y0 = s.y0 + ly * strip
    return x0, y0, x0 + strip, min(y0 + strip, s.y1)


def land_rect(world: World, key: str) -> tuple[int, int, int, int]:
    """x0, y0, x1, y1 (half-open) of the land "lx,ly", where it lies now."""
    lx, ly = (int(v) for v in key.split(","))
    return _rect(world, lx, ly, _strip(world))


def land_at(world: World, x: int, y: int) -> str | None:
    """The key of the frontier land holding the surface tile (x, y); None in the home lands, off the surface or the
    map."""
    laid = (world.ext.get(PACK) or {}).get("lands")
    s = world.region("surface")
    if not laid or not s.y0 <= y < s.y1:
        return None
    strip, rel = _strip(world), x - world.origin_x
    if 0 <= rel < world.home_width:
        return None
    lx = (rel - world.home_width) // strip + 1 if rel >= 0 else -((-rel - 1) // strip + 1)
    key = f"{lx},{(y - s.y0) // strip}"
    return key if key in laid else None


# ------------------------------------------------------------------ laying a strip
_SHARED = ("catalog", "rng", "recall_hook", "frontier_settings")  # a growth changes none of these; others hold them


def _keep(world: World) -> dict:
    """A copy of the world's own state, to put back if a growth fails half-way."""
    return copy.deepcopy({k: v for k, v in vars(world).items() if k not in _SHARED})


def _put_back(world: World, kept: dict) -> None:
    """The world as it was when kept. Creatures and objects stay the same instances, with their fields as they were,
    in case something else holds one."""
    for name in ("creatures", "objects"):
        live = getattr(world, name)
        for key, was in kept[name].items():
            if key in live:
                vars(live[key]).update(vars(was))
                kept[name][key] = live[key]
    for k in [k for k in vars(world) if k not in kept and k not in _SHARED]:
        delattr(world, k)
    vars(world).update(kept)


def grow(world: World, side: str, by: Creature | None = None, theme: str | None = None,
         ignore_pace: bool = False) -> list[str]:
    """Lay a strip of new land to the east or west, if one may be laid now (why_not_grow; with ignore_pace, the pace
    doesn't hold it back). `by` is the creature whose exploring lays it; `theme` makes every land of it that theme.
    Returns the new lands' keys, north to south, or [] when none was laid. A growth that fails is taken back whole
    and logged."""
    why = why_not_grow(world, side)
    if why and not (ignore_pace and why == "pace"):
        return []
    kept = None
    try:
        kept = _keep(world)
        return _lay(world, side, by, theme)
    except Exception as exc:
        if kept is not None:
            _put_back(world, kept)
        at = traceback.extract_tb(exc.__traceback__)[-1]
        log.error("frontier: the strip to the %s failed and was taken back; nothing grew (%s: %s, at %s:%s in %s)",
                  side, type(exc).__name__, " ".join(str(exc).split()), at.filename.rsplit("/", 1)[-1], at.lineno,
                  at.name)
        world.frontier_record()["failed"] = world.tick  # after the put-back: no retry at every arrival
        return []


def _lay(world: World, side: str, by: Creature | None, theme: str | None) -> list[str]:
    s = world.region("surface")
    strip, seed = _strip(world), frontier_seed(world)
    k = ((world.ext.get(PACK) or {}).get("strips") or {}).get(side, 0) + 1
    lx = k if side == "east" else -k
    # the lands, from the edges as they are before the map widens: the seam column, and the land above
    seam = world.width - 1 if side == "east" else 0
    need = lands.need(world)
    made: list[tuple[str, lands.Land]] = []
    above = None
    for ly, y0 in enumerate(range(s.y0, s.y1, strip)):
        y1 = min(y0 + strip, s.y1)
        edges = {"west" if side == "east" else "east": lands.column_edge(world, seam, y0, y1)}
        if above is not None:
            edges["north"] = lands.row_edge(above, len(above.tiles) - 1)
        above = lands.generate_land(seed, lx, ly, (strip, y1 - y0), edges, need, theme)
        made.append((f"{lx},{ly}", above))
    width_before = world.width
    world.add_columns(side, strip)  # every row; on the west, the world moves east
    rects = [_rect(world, lx, ly, strip) for ly in range(len(made))]
    # the land itself, and nature's biome and flow rows (new lists, so nature's habitats are worked out again)
    nature = world.ext.get("nature") or {}
    rows = {key: list(nature[key]) for key in ("biomes", "flow") if nature.get(key)}
    for (_, land), (x0, y0, x1, y1) in zip(made, rects):
        for r, y in enumerate(range(y0, y1)):
            world.tiles[y][x0:x1] = list(land.tiles[r])
            for key, new in rows.items():
                code = getattr(land, key)[r]
                new[y] = new[y] + code if side == "east" else code + new[y]
    nature.update(rows)
    for (_, land), (x0, y0, _, _) in zip(made, rects):
        for kind, x, y, data in land.objects:
            if (x0 + x, y0 + y) not in world.grid:
                world.add_object(kind, x0 + x, y0 + y, **data)
    from . import underground  # inside the function: pack order and the golden hashes stay as they were
    mouths = [(x0 + land.mouth[0], y0 + land.mouth[1]) for (_, land), (x0, y0, _, _) in zip(made, rects) if land.mouth]
    underground.grow_under(world, rects[0][0], rects[0][2], random.Random(f"{seed}:{lx}:deep"), mouths)
    for ly, rect in enumerate(rects):
        run_populate_land(world, random.Random(f"{seed}:{lx}:{ly}:populate"), rect)
    rec = world.frontier_record()
    rec.setdefault("seed", seed)
    rec.setdefault("strip", strip)
    rec.setdefault("strips", {"east": 0, "west": 0})
    rec.setdefault("lands", {})
    for key, land in made:
        rec["lands"][key] = {"theme": land.theme, "side": side, "heart": list(land.heart), "name": None,
                             "found_by": None, "tick": None}
    rec["strips"][side] += 1
    rec["last_grow"] = world.tick
    world.tiles_version += 1
    x0, x1 = rects[0][0], rects[0][2]
    for p in [p for p in world.changed_tiles if x0 <= p[0] < x1]:  # viewers get the whole map anew
        del world.changed_tiles[p]
    world.growths.append({"side": side, "columns": strip, "width": world.width, "origin_x": world.origin_x})
    text = f"{by.name}'s exploring lays down new country to the {side}." if by else f"New country lies to the {side}."
    seam = width_before - 1 if side == "east" else strip  # the old edge column, where it lies now
    world.emit("frontier", by.id if by else None, seam, (s.y0 + s.y1) // 2, text)
    return [key for key, _ in made]


# ------------------------------------------------------------------ the edge, and exploring to it
def growable(world: World, side: str) -> bool:
    """New land may come to this side some day: the frontier is on and the map is under its cap (the pace aside)."""
    return world.frontier_settings.on and why_not_grow(world, side) != "cap"


def edge_distance(world: World, c: Creature, side: str) -> int:
    return world.width - 1 - c.x if side == "east" else c.x


def _on_surface(world: World, c: Creature) -> bool:
    r = world.region_at(c.x, c.y)
    return r is not None and r.name == "surface"


def _edge_line(world: World, c: Creature) -> str | None:
    """The unknown country, said when a growable edge comes into sight and again on waking."""
    mine = c.ext.get(PACK) or {}
    sight = sight_range(world, c) if _on_surface(world, c) else -1
    near = [(edge_distance(world, c, side), i, side) for i, side in enumerate(SIDES) if growable(world, side)]
    near = [n for n in near if n[0] <= sight]
    if not near:
        mine.pop("edge", None)
        return None
    side = min(near)[2]
    if mine.get("edge") == side and c.wake_reason != "woke":
        return None
    c.ext.setdefault(PACK, {})["edge"] = side
    return EDGE_LINE.format(side=side)


def _reach(world: World, c: Creature) -> int:
    """How far from an edge exploring toward it still heads there: an explorer goes from anywhere (the pull names the
    edge, and the camp is far from both), anyone else within EDGE_NEAR, so their explore stays the core one."""
    return world.width if (c.persona or {}).get("drive") == "explorer" else EDGE_NEAR


def _edge_explore(world: World, c: Creature, d: str) -> ActionResult | None:
    if not _on_surface(world, c):
        return None
    reach = _reach(world, c)
    side = next((s for s in SIDES if d in SIDE_DIRS[s] and growable(world, s)
                 and edge_distance(world, c, s) <= reach), None)
    if side is None:
        return None
    if edge_distance(world, c, side) > EDGE_REACH:
        cols = (world.width - 2, world.width - 1) if side == "east" else (0, 1)
        goals = {(x, y) for x in cols for y in range(c.y - 4, c.y + 5) if world.walkable(x, y)}
        path = bfs_path(world, (c.x, c.y), goals) if goals else None
        leg = False
        if path is None and goals and reach > EDGE_NEAR:  # an explorer far off: walk a leg toward it, then explore on
            path = bfs_path(world, (c.x, c.y), goals, closest=True)
            ahead = path and (path[-1][0] > c.x if side == "east" else path[-1][0] < c.x)
            path, leg = (path, True) if ahead else (None, False)  # a leg that gains no ground: the core explore it is
        if not path or len(path) > 2 * reach:  # a long way round: the core explore it is
            return None
        c.activity = {"type": "walk", "path": path, "label": f"exploring {d}",
                      "result": "" if leg else REACH_EDGE.format(side=side), "then": Intention("explore", target=side)}
        return ActionResult(True, HEAD_TO_EDGE.format(d=d), instant=False)
    if why_not_grow(world, side) == "pace":
        return ActionResult(False, ANOTHER_DAY)
    seam = world.width - 1  # the old edge column, in the world as it is before the strip
    if not grow(world, side, by=c):
        return ActionResult(False, ANOTHER_DAY)
    seam = seam if side == "east" else _strip(world)
    x = seam + WALK_ON if side == "east" else seam - WALK_ON
    goals = {(x, y) for y in range(c.y - 2, c.y + 3) if world.walkable(x, y)}
    if goals:
        res = start_walk(world, c, goals, f"exploring {d}", ON_INTO.format(side=side))
        if res.ok and c.activity:
            return ActionResult(True, NEW_COUNTRY.format(side=side), instant=False)
    return ActionResult(True, NEW_COUNTRY.format(side=side))


actions.explore_edge = _edge_explore
register_perception(_edge_line, priority=48)


# ------------------------------------------------------------------ first entry, names, places
ORDINALS = ("second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth")


def land_name(world: World, rec: dict, founder: str) -> str:
    """"the Eastern Hills" when no land has that name yet, else "{founder}'s Hills", then "{founder}'s second Hills"."""
    noun = lands.THEMES[rec["theme"]]["noun"]
    taken = {r.get("name") for r in ((world.ext.get(PACK) or {}).get("lands") or {}).values()}
    name = f"the {'Eastern' if rec['side'] == 'east' else 'Western'} {noun}"
    n = 1
    while name in taken:
        n += 1
        ordinal = "" if n == 2 else (ORDINALS[n - 3] + " ") if n - 3 < len(ORDINALS) else f"{n}th "
        name = f"{founder}'s {ordinal}{noun}"
    return name


def _discover(sim, t: int) -> None:
    """The first creature to stand in a new land finds it, and names it."""
    world = sim.world
    laid = (world.ext.get(PACK) or {}).get("lands")
    if not laid:
        return
    for c in list(world.creatures.values()):
        if c.asleep or c.collapsed:
            continue
        key = land_at(world, c.x, c.y)
        rec = laid.get(key) if key else None
        if rec is None or rec["found_by"] is not None:
            continue
        label = lands.THEMES[rec["theme"]]["label"]
        name = land_name(world, rec, c.name)
        rec.update(found_by=c.name, name=name, tick=t)
        sim.remember(c, FOUND.format(side=rec["side"], label=label, name=name), 3)
        world.emit("land", c.id, c.x, c.y, LAND_EVENT.format(who=c.name, side=rec["side"], label=label, name=name))


def _places(world: World) -> list[dict]:
    out: list[dict] = []
    for key, rec in ((world.ext.get(PACK) or {}).get("lands") or {}).items():
        if not rec.get("name"):
            continue
        x0, y0, x1, y1 = land_rect(world, key)
        out.append({"name": rec["name"], "x": x0 + rec["heart"][0], "y": y0 + rec["heart"][1], "kind": "land"})
        for o in world.objects.values():
            if o.kind == "terminal" and o.data.get("ruin") and x0 <= o.x < x1 and y0 <= o.y < y1:
                out.append({"name": f"the old terminal in {rec['name']}", "x": o.x, "y": o.y, "kind": "terminal"})
    return out


register_system("frontier discovery", 3, _discover)
register_landmarks(_places)


# ------------------------------------------------------------------ the explorers' pull
def _pull(sim, t: int) -> None:
    """Once a day, an idle explorer is reminded of the unknown country. Draws no dice."""
    world = sim.world
    for c in world.creatures.values():
        if (c.persona or {}).get("drive") != "explorer" or c.asleep or c.collapsed or c.activity is not None \
                or c.thinking or not _on_surface(world, c):
            continue
        if t - (c.ext.get(PACK) or {}).get("pulled", -DAY_TICKS) < DAY_TICKS:
            continue
        ways = [(edge_distance(world, c, side), i, side) for i, side in enumerate(SIDES) if why_not_grow(world, side) is None]
        if not ways:
            continue
        d, _, side = min(ways)
        sim.remember(c, PULL.format(side=side, d=max(5, 5 * round(d / 5))), 2)
        c.ext.setdefault(PACK, {})["pulled"] = t


register_system("frontier pull", 20, _pull)
