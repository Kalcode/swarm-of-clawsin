"""The frontier: new land laid down at the map's east and west edges, a strip at a time
(docs/superpowers/specs/2026-11-03-frontier-design.md).

A strip is `strip` columns wide (32) and as tall as the surface, cut into lands strip x strip (the last one shorter
when the surface's height isn't a multiple of it). Each land comes from swarmworld/world/lands.py, fitted to the old
edge and to the land above it, and the packs' land hooks then fill it. The rock band and the deep get rock. At most
one strip every `pace` ticks, world-wide, and never wider than `cap` (World.frontier_settings, which the server sets
at every start: --frontier on|off). A strip to the west moves the whole world east by its width (World.shift_x).

State, world.ext["frontier"] (saved), made at the first growth:
  {"origin_x", "home_width" (World.frontier_record), "seed", "strip", "strips": {"east": n, "west": n},
   "last_grow": tick or None,
   "lands": {"lx,ly": {"theme", "side", "heart": [hx, hy] (inside the land), "name", "found_by", "tick"}}}
lx counts strips out from the home lands (east 1, 2...; west -1, -2...), ly lands down from the surface's top row.
They count from the home lands, so a shift never moves them. `strip` is the one the first growth used, from then on.

Nothing here rolls the world's dice: each land, and the filling of it, has a random.Random of its own, seeded from the
frontier seed and the land's place. A growth that fails half-way is taken back whole, and nothing grows."""

from __future__ import annotations

import copy
import logging
import random
import zlib
from typing import TYPE_CHECKING

from .. import lands
from ..registry import run_populate_land

if TYPE_CHECKING:
    from ..model import Creature, World

PACK = "frontier"
SIDES = ("east", "west")
log = logging.getLogger("swarmworld.packs")


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
    last = (world.ext.get(PACK) or {}).get("last_grow")
    if last is not None and world.tick - last < settings.pace:
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
    kept = _keep(world)
    try:
        return _lay(world, side, by, theme)
    except Exception as exc:
        _put_back(world, kept)
        log.error("frontier: the strip to the %s failed and was taken back; nothing grew (%s: %s)", side,
                  type(exc).__name__, " ".join(str(exc).split()))
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
    # the deep under the strip stays solid rock for now
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
