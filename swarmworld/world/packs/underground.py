"""The underground: a deep under every world, the ways down to it and back up, and its named caves (data:
swarmworld/data/packs/underground/).

- The deep: on a new world, and on an older save the first time it loads, the deep is carved (swarmworld/world/caves.py)
  below the surface, past a band of solid rock: a region of the surface's size, level -1, with no sky and no weather.
  Its seed is the world's, or for a save from before seeds were kept, one read off its land, so it is the same deep
  every time the save loads until it is saved with it.
- Cave mouths: 3-5 open on the surface, on rocky ground first, away from the meadow and from what creatures made. Below
  each the rock is cut through to the cave system, to a cave exit.
- Portals: a way down and its way up, each end an object ("up" is the end on the surface, "down" the end in the deep):
  a cave mouth and its exit, and later a mine shaft or an open pit with a ladder below.
- Landmarks: the four largest caverns and the pool by name, each way down by its name and its way up as "the way up to
  <name>". Creatures hear of a place only in its own region.
- What lies in the deep: iron and copper veins, coal seams, crystal clusters, cave mushrooms and loose rock on the cave
  floor, placed once (`_stock_deep`).

- Torches: a torch (stick, plant fiber, charcoal) is lit at a burning campfire or from someone's lit torch, burns
  TORCH_TICKS carried (c.ext["underground"]["torch_until"]) and lights the dark; then it is a stick.
- Climbing: the verb `climb` takes a creature from beside one end of a way to the other end (or the nearest free tile
  beside it), and a creature that doesn't know where a way is walks to the nearest it saw, remembers or climbed.
  Climbing down into a shaft's or a pit's chamber that is still sealed in the rock, it is told so.

State: c.ext["underground"] = {"ways": [portal ids climbed or seen], "told": last way line}.
State: world.ext["underground"] = {"seed": int, "next_portal": int, "placed": bool, "caves": [{"name", "x", "y"}], "portals": [{"id", "kind", "name",
"up": [x, y], "down": [x, y], and for a shaft or pit "chamber": [[x, y], ...], the chamber dug below it}]}. Nothing here draws from world.rng or the generator's rng (the deep and its mouths
roll their own random.Random, seeded from the deep's seed), so the surface's weather, animals and placement roll as
before."""

from __future__ import annotations

import json
import random
import zlib
from collections import Counter
from typing import TYPE_CHECKING

import numpy as np

from .. import actions, perception
from ..caves import BORDER, carve_deep, carve_passage, tile_codes
from ..catalog import DATA
from ..model import LIGHT_ITEMS, SOLID_TILES, WATER_TILES
from ..perception import DARK_SIGHT, direction, dist
from ..registry import (ANIMALS, BLOCKING, KINDS, STORES, Technique, register_handoff, register_landmarks, register_perception,
                        register_populate, register_system, register_technique, register_verb)

if TYPE_CHECKING:  # never at the top for real: simulation imports the packs (see registry.py)
    from ..actions import ActionResult, Intention
    from ..model import Creature, Region, World

PACK = "underground"
CONFIG = json.loads((DATA / "packs" / PACK / "underground.json").read_text())
MOUTH_AWAY = 20  # cave mouths lie this far from the meadow's middle (a quarter of a smaller map): beyond its landmarks
MOUTH_APART = 12
MOUTH_CLEAR = 3  # steps kept between a cave mouth and anything a creature built or planted
ORDINALS = ("second", "third", "fourth", "fifth")
PORTAL_OBJECTS = {"cave": ("cave_mouth", "cave_exit"), "shaft": ("mine_shaft", "ladder"), "pit": ("open_pit", "ladder")}


def _mine(world: World) -> dict:
    return world.ext.setdefault(PACK, {})


# ------------------------------------------------------------------ portals
def portals(world: World) -> list[dict]:
    """Every way down and its way up: {"id", "kind" (cave, shaft or pit), "name", "up": [x, y], "down": [x, y]}."""
    return (world.ext.get(PACK) or {}).get("portals", [])


def add_portal(world: World, kind: str, name: str, up: tuple[int, int], down: tuple[int, int]) -> dict:
    """A new way down at `up` (on the surface) and its way up at `down` (in the deep), with its end objects
    (PORTAL_OBJECTS[kind]; each carries data["portal"] = the portal's id). Both ends must be free of objects."""
    ends = [(end, k) for end, k in zip((tuple(up), tuple(down)), PORTAL_OBJECTS[kind]) if k]
    if any(end in world.grid for end, _ in ends):
        raise ValueError(f"a {kind} portal needs its ends free of objects: {up}, {down}")
    have = _mine(world).setdefault("portals", [])
    mine = _mine(world)  # ids count up and are never reused, even when the highest portal is gone
    n = mine.get("next_portal") or max((int(p["id"][1:]) for p in have), default=0) + 1
    mine["next_portal"] = n + 1
    pid = f"p{n}"
    for end, k in ends:
        world.add_object(k, *end, portal=pid)
    portal = {"id": pid, "kind": kind, "name": name, "up": list(up), "down": list(down)}
    have.append(portal)
    return portal


def remove_portal(world: World, pid: str) -> None:
    """The portal and its end objects are gone."""
    have = portals(world)
    have[:] = [p for p in have if p["id"] != pid]
    for o in [o for o in world.objects.values() if o.data.get("portal") == pid]:
        world.remove_object(o.id)


def portal_near(world: World, x: int, y: int, reach: int = 1) -> tuple[dict, str] | None:
    """The portal with an end within reach of (x, y) in its region, the nearest, and which end it is: "up" or "down"."""
    best = None
    for p in portals(world):
        for end in ("up", "down"):
            ex, ey = p[end]
            d = dist(x, y, ex, ey)
            if d <= reach and world.same_region((x, y), (ex, ey)) and (best is None or d < best[0]):
                best = (d, p, end)
    return (best[1], best[2]) if best else None


# ------------------------------------------------------------------ growing the deep
def deep_seed(world: World) -> int:
    """The deep's seed: the world's, or for an old save without one, a checksum of its surface; kept once worked out."""
    mine = _mine(world)
    if "seed" not in mine:
        if world.seed is not None:
            mine["seed"] = world.seed
        else:
            _, y0, _, y1 = world.region_bounds("surface")
            mine["seed"] = zlib.crc32("\n".join("".join(world.tiles[y]) for y in range(y0, y1)).encode())
    return mine["seed"]


def _kept_clear(world: World) -> set[tuple[int, int]]:
    """Tiles no cave mouth opens on: within MOUTH_CLEAR of what a creature built or planted, and building footprints
    (the building pack's sites and buildings: rectangles x0, y0, x1, y1, inclusive)."""
    made = [(o.x, o.y) for o in world.objects.values() if o.data.get("builder") or o.data.get("planter")]
    r = range(-MOUTH_CLEAR, MOUTH_CLEAR + 1)
    out = {(x + dx, y + dy) for x, y in made for dx in r for dy in r}
    building = world.ext.get("building") or {}
    for b in [*(building.get("sites") or {}).values(), *(building.get("built") or {}).values()]:
        out.update((x, y) for y in range(b["y0"], b["y1"] + 1) for x in range(b["x0"], b["x1"] + 1))
    return out


def _mouth_sites(world: World, rng: random.Random) -> list[tuple[int, int]]:
    """Where cave mouths open: rng.randint(3, 5) free tiles of dry land, rocky ground first, MOUTH_APART apart, away
    from the meadow, clear of what creatures made, each over the deep's interior with a step to spare. Fewer only when
    a small map has no room; at least one while it has any dry land over the deep."""
    x0, y0, x1, y1 = world.region_bounds("surface")
    deep = world.region("deep")
    cx, cy = world.center
    away = min(MOUTH_AWAY, min(x1 - x0, y1 - y0) // 4)
    m = BORDER + 1
    clear = _kept_clear(world)
    rows, cols = range(y0 + m, min(y1, y0 + deep.height - m)), range(max(x0, m), min(x1, world.width - m))
    land, rocky, rest = [], [], []
    if rows and cols:
        block = tile_codes(world, rows.start, rows.stop)[:, cols.start:cols.stop]
        dry = ~np.isin(block, [ord(c) for c in WATER_TILES + SOLID_TILES])
        for x, y in [*world.grid, *clear]:  # taken or kept clear
            if x in cols and y in rows:
                dry[y - rows.start, x - cols.start] = False
        iy, ix = np.nonzero(dry)
        xs, ys = ix + cols.start, iy + rows.start
        land = list(zip(xs.tolist(), ys.tolist()))
        far = np.maximum(np.abs(xs - cx), np.abs(ys - cy)) >= away
        stone = block[iy, ix] == ord("r")
    want = rng.randint(3, 5)
    if land:
        rocky = [p for p, f in zip(land, far & stone) if f]
        rest = [p for p, f in zip(land, far & ~stone) if f]
    rng.shuffle(rocky)
    rng.shuffle(rest)
    sites: list[tuple[int, int]] = []
    for p in rocky + rest:
        if len(sites) == want:
            break
        if all(dist(*p, *q) >= MOUTH_APART for q in sites):
            sites.append(p)
    if not sites and land:  # no room so far out: the dry land farthest from the meadow
        sites.append(max(land, key=lambda p: (dist(*p, cx, cy), p[1], p[0])))
    return sites


def _deep_tiles(world: World, deep: Region) -> np.ndarray:
    return tile_codes(world, deep.y0, deep.y1)


def _caves(world: World, deep: Region, caverns: list[tuple[int, int, int]], pool: tuple[int, int]) -> list[dict]:
    """The named caves: the largest caverns by CONFIG's cave_names, then the pool. Each landmark stands on the dry cave
    floor nearest the middle (the pool's middle is often water), never on the way up from a cave mouth or on another
    landmark."""
    middles = [(n, x, deep.y0 + y) for n, (x, y, _) in zip(CONFIG["cave_names"], caverns)]
    middles.append((CONFIG["pool_name"], pool[0], deep.y0 + pool[1]))
    taken = {tuple(p["down"]) for p in portals(world)}
    ys, xs = np.nonzero(_deep_tiles(world, deep) == ord("c"))  # in reading order, so the first nearest is the one wanted
    ys = ys + deep.y0
    free = np.ones(len(xs), dtype=bool)
    for tx, ty in taken:
        free &= (xs != tx) | (ys != ty)
    named = []
    for name, mx, my in middles:
        x, y = mx, my
        if free.any():
            k = np.where(free, np.maximum(np.abs(xs - mx), np.abs(ys - my)), np.iinfo(np.int64).max).argmin()
            x, y = int(xs[k]), int(ys[k])
            free[k] = False
        named.append({"name": name, "x": x, "y": y})
    return named


def grow_deep(world: World) -> None:
    """Give the world its deep, once: carve it from the deep's seed, add it below a band of rock, name its caves and
    open the cave mouths, each cut through to the cave system below. The land it carves is left out of the tile
    changes sent to viewers: they get the whole map when they connect."""
    if world.region("deep") is not None:
        return
    earlier = dict(world.changed_tiles)
    rng = random.Random(deep_seed(world))
    mine = _mine(world)
    dm = carve_deep(rng, world.width, world.region("surface").height)
    deep = world.add_region("deep", -1, dm.rows, sky=False, weather=False)
    cx, cy = world.center
    seen: Counter = Counter()
    for up in _mouth_sites(world, rng):
        way = direction(up[0] - cx, up[1] - cy)
        seen[way] += 1
        name = f"the {way} cave" if seen[way] == 1 else f"the {ORDINALS[seen[way] - 2]} {way} cave"
        down = world.below(*up)
        world.set_tile(*down, "c")
        carve_passage(world, down)
        add_portal(world, "cave", name, up, down)
    mine["caves"] = _caves(world, deep, dm.caverns, dm.pool)
    world.changed_tiles.clear()
    world.changed_tiles.update(earlier)


# ------------------------------------------------------------------ what lies in the deep
ORE_DATA = {"iron_vein": {"ore": 8}, "copper_vein": {"ore": 8}}  # data a placed kind starts with
ON_ROCK = {"iron_vein", "copper_vein", "coal_seam", "crystal_cluster"}  # these go on floor that touches rock
CLUSTERS = {"crystal_cluster": "the crystal cave", "coal_seam": "the black seam"}  # a third lie near this cave
CLUSTER_REACH = 6
PORTAL_CLEAR = 2
STEPS = ((1, 0), (-1, 0), (0, 1), (0, -1))


def _walker(world: World):
    """world.walkable(x, y) for a stretch of land that is not being changed, quicker: tiles are looked up directly."""
    tiles, grid, objects, w, h = world.tiles, world.grid, world.objects, world.width, world.height
    over_water = {k for k, spec in KINDS.items() if spec.get("over_water")}

    def walkable(x: int, y: int) -> bool:
        if not (0 <= x < w and 0 <= y < h):
            return False
        t = tiles[y][x]
        if t in SOLID_TILES:
            return False
        oid = grid.get((x, y))
        obj = objects.get(oid) if oid else None
        if t == "W" and not (obj and obj.kind in over_water):
            return False
        return not (obj and (obj.kind in BLOCKING or obj.kind in ANIMALS))
    return walkable


def _blocks_nothing(walkable, x: int, y: int) -> bool:
    """True when a blocking object on (x, y) cuts no walk: its open neighbours still join around it, within the ring of
    eight tiles that surrounds it. `walkable` is _walker(world)."""
    ring = [(x + dx, y + dy) for dx, dy in ((-1, -1), (0, -1), (1, -1), (1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0))]
    free = [p for p in ring if walkable(*p)]
    open_sides = [p for p in free if abs(p[0] - x) + abs(p[1] - y) == 1]
    if len(open_sides) < 2:
        return True
    seen, todo = {open_sides[0]}, [open_sides[0]]
    while todo:
        px, py = todo.pop()
        for dx, dy in STEPS:
            n = (px + dx, py + dy)
            if n in free and n not in seen:
                seen.add(n)
                todo.append(n)
    return all(p in seen for p in open_sides)


def _stock_deep(world: World) -> None:
    """Scatter the deep's ore, coal, crystal, mushrooms and rock over its cave floor, once (ext "placed"): CONFIG's
    counts per 128x128 of deep, scaled by area, at least 2 of each. Veins, seams and crystals stand on floor touching
    rock; a third of the crystals lie near the crystal cave and a third of the coal near the black seam, where there
    is room. Blocking things never cut a walk, and none lies within PORTAL_CLEAR of a way up. Rolled from the deep's
    own seed + 1."""
    mine = _mine(world)
    deep = world.region("deep")
    if mine.get("placed") or deep is None:
        return
    mine["placed"] = True
    rng = random.Random(deep_seed(world) + 1)
    blocked = {tuple(p["down"]) for p in portals(world)} | {(c["x"], c["y"]) for c in mine.get("caves", ())}
    exits = [tuple(p["down"]) for p in portals(world)]
    area = world.width * (deep.y1 - deep.y0)
    tiles = _deep_tiles(world, deep)
    ok = tiles == ord("c")
    for bx, by in blocked:
        if deep.y0 <= by < deep.y1 and 0 <= bx < world.width:
            ok[by - deep.y0, bx] = False
    for ex, ey in exits:  # within PORTAL_CLEAR (1 step: the 3x3 around)
        ok[max(0, ey - deep.y0 - PORTAL_CLEAR + 1):ey - deep.y0 + PORTAL_CLEAR, max(0, ex - PORTAL_CLEAR + 1):ex + PORTAL_CLEAR] = False
    solid = np.isin(tiles, [ord(c) for c in SOLID_TILES])
    touches = np.zeros_like(solid)  # floor with rock on a side (off the deep's edge counts as none)
    touches[1:] |= solid[:-1]
    touches[:-1] |= solid[1:]
    touches[:, 1:] |= solid[:, :-1]
    touches[:, :-1] |= solid[:, 1:]
    walkable = _walker(world)
    caves = {c["name"]: (c["x"], c["y"]) for c in mine.get("caves", ())}
    for kind, per in CONFIG["counts"].items():
        want = max(2, round(per * area / (128 * 128)))
        blocking = KINDS[kind].get("blocking")
        ys, xs = np.nonzero(ok & touches if kind in ON_ROCK else ok)
        spots = list(zip(xs.tolist(), (ys + deep.y0).tolist()))
        rng.shuffle(spots)
        if kind in CLUSTERS and CLUSTERS[kind] in caves:  # a third near their cave first, the rest anywhere
            home = caves[CLUSTERS[kind]]
            spots.sort(key=lambda p: dist(*p, *home) > CLUSTER_REACH)  # stable: near ones keep their shuffled order
            near = [p for p in spots if dist(*p, *home) <= CLUSTER_REACH]
            rest = spots[len(near):]
            spots = near[:want // 3] + rest + near[want // 3:]
        placed = 0
        for p in spots:
            if placed == want:
                break
            if p in world.grid or (blocking and not _blocks_nothing(walkable, *p)):
                continue
            world.add_object(kind, *p, **ORE_DATA.get(kind, {}))
            placed += 1


def _populate(world: World, rng, fresh: bool) -> None:  # new worlds and old saves alike; never rolls the rng given
    grow_deep(world)
    _stock_deep(world)


# ------------------------------------------------------------------ landmarks
def _places(world: World) -> list[dict]:
    mine = world.ext.get(PACK) or {}
    out = [{"name": c["name"], "x": c["x"], "y": c["y"], "kind": "cave"} for c in mine.get("caves", ())]
    for p in mine.get("portals", ()):
        out.append({"name": p["name"], "x": p["up"][0], "y": p["up"][1], "kind": "way down"})
        out.append({"name": f"the way up to {p['name']}", "x": p["down"][0], "y": p["down"][1], "kind": "way up"})
    return out


perception.REMEMBERED_KINDS.update({"coal_seam", "crystal_cluster"})  # the deep's finds, to come back to
perception.REMEMBERED_KINDS.update({k for ends in PORTAL_OBJECTS.values() for k in ends if k})  # ways to find again
register_populate(PACK, _populate)
register_landmarks(_places)


# ------------------------------------------------------------------ climbing
DOWN_WORDS = {"down", "deep", "underground", "below", "descend"}
UP_WORDS = {"up", "surface", "daylight", "outside", "above", "ascend"}
CLIMB_LINE = ('climb (target "down" or "up"): climb down into the deep at a cave mouth, shaft or open pit beside you, '
              'or back up at a cave exit or ladder.')
DEEP_PHRASES = {"deep", "underground", "caves below", "the deep below", "deep below", "the deep"}
CROWDED_REACH = 2  # how far from a crowded end a creature may arrive


def _words(text: str) -> set[str]:
    return set(text.lower().replace("_", " ").split())


def _level(world: World, x: int, y: int) -> int:
    r = world.region_at(x, y)
    return r.level if r else 0


def _ways(c: Creature) -> list[str]:
    return c.ext.setdefault(PACK, {}).setdefault("ways", [])


def _ends_here(world: World, c: Creature) -> list[tuple[dict, str, tuple[int, int]]]:
    """Every way end in the creature's own region: (portal, "up" or "down", (x, y))."""
    return [(p, end, (p[end][0], p[end][1])) for p in portals(world) for end in ("up", "down")
            if world.same_region((c.x, c.y), tuple(p[end]))]


def _end_name(p: dict, end: str) -> str:
    return p["name"] if end == "up" else f"the way up to {p['name']}"


def _known_ends(world: World, c: Creature, sight_only: bool = False) -> list[tuple[int, dict, str, tuple[int, int]]]:
    """The ends here the creature has in sight (and with sight_only False, also remembers or has climbed), nearest
    first: (distance, portal, end, (x, y)). Ends in sight join its known ways."""
    r = perception.sight_range(world, c)
    spots = {(x, y) for x, y, _t in c.spots.values()}
    climbed = set((c.ext.get(PACK) or {}).get("ways", ()))
    seen, known = [], []
    for p, end, pos in _ends_here(world, c):
        d = dist(c.x, c.y, *pos)
        if d <= r and pos in world.grid:
            seen.append((d, p, end, pos))
        elif pos in spots or p["id"] in climbed:
            known.append((d, p, end, pos))
    for _, p, _e, _pos in seen:
        if p["id"] not in _ways(c):
            _ways(c).append(p["id"])
    if sight_only:
        return sorted(seen, key=lambda t: t[0])
    return sorted(seen or known, key=lambda t: t[0])


def _arrival(world: World, c: Creature, pos: tuple[int, int]) -> tuple[int, int] | None:
    """The tile to arrive on: the end itself if walkable and free, else the nearest free walkable tile within reach."""
    best = None
    for dy in range(-CROWDED_REACH, CROWDED_REACH + 1):
        for dx in range(-CROWDED_REACH, CROWDED_REACH + 1):
            x, y = pos[0] + dx, pos[1] + dy
            if world.walkable(x, y) and world.same_region(pos, (x, y)) and not world.occupied(x, y, ignore=c.id):
                key = (max(abs(dx), abs(dy)), abs(dx) + abs(dy), y, x)
                if best is None or key < best[0]:
                    best = (key, (x, y))
    return best[1] if best else None


def _sealed(world: World, p: dict, pos: tuple[int, int]) -> bool:
    """The chamber dug below a shaft or a pit (the portal's "chamber") is still shut in by rock: the open ground
    reached from pos (orthogonal steps, in its region) is the chamber's own tiles, nothing more."""
    chamber = {tuple(t) for t in p.get("chamber") or ()}
    if pos not in chamber:
        return False
    seen, todo = {pos}, [pos]
    while todo:
        x, y = todo.pop()
        for dx, dy in STEPS:
            n = (x + dx, y + dy)
            if n in seen or world.tile(*n) in SOLID_TILES or not world.same_region(pos, n):
                continue
            if n not in chamber:
                return False
            seen.add(n)
            todo.append(n)
    return seen == chamber


def _climb(world: World, c: Creature, it: Intention) -> ActionResult:
    from ..actions import ActionResult, Intention, _adjacent_goals, _busy, start_walk
    words = _words(it.target)
    level = _level(world, c.x, c.y)
    want = "down" if words & DOWN_WORDS else "up" if words & UP_WORDS else None
    near = portal_near(world, c.x, c.y, 1)
    if near:
        p, end = near  # "up" is the end on the surface, which leads down
        goes = "down" if end == "up" else "up"
        if want and want != goes:
            return ActionResult(False, "You're on the surface already; this is the way down." if goes == "down"
                                else "This is the way up; there is nothing deeper.")
        there = _arrival(world, c, tuple(p["down" if goes == "down" else "up"]))
        if there is None:
            return ActionResult(False, "Someone is in the way at the other end; you wait.")
        c.x, c.y = there
        c.energy = max(0.0, c.energy - 1)
        if p["id"] not in _ways(c):
            _ways(c).append(p["id"])
        if goes == "down":
            text = f"You climb down into the deep at {p['name']}."
            if perception.light_range(world, c) == DARK_SIGHT:
                text += " It is pitch dark."
            if _sealed(world, p, there):
                text += " Solid stone all around: dig your way out."
        else:
            text = f"You climb back up to the surface at {p['name']}."
        world.emit("climb", c.id, c.x, c.y, f"{c.name} climbed {goes} at {p['name']}.")
        return _busy(c, 4, f"climbing {goes}", text)
    want = want or ("down" if level >= 0 else "up")
    if want == "down" and level < 0:
        return ActionResult(False, "There is nothing deeper to climb down to.")
    if want == "up" and level >= 0:
        return ActionResult(False, "You're on the surface already.")
    for d, p, end, pos in _known_ends(world, c):
        goals = _adjacent_goals(world, *pos, include_self=world.walkable(*pos))
        res = start_walk(world, c, goals, f"heading to {_end_name(p, end)}", f"You reach {_end_name(p, end)}.")
        if c.activity:
            c.activity["then"] = Intention("climb", target=want)
        return res
    if want == "down":
        return ActionResult(False, "You don't know a way down. Cave mouths open in the rocky hills; with a pickaxe you could dig down.")
    return ActionResult(False, "You don't know a way up from here. Look for a cave exit or a ladder, or dig your way.")


def _way_to_region(world: World, c: Creature, region: Region) -> str:
    below = region.level < _level(world, c.x, c.y)
    text = ("The deep is below; climb down at a cave mouth or a mine shaft." if below
            else "The surface is above; climb up at a cave exit or a ladder.")
    known = _known_ends(world, c)
    if known:
        d, p, end, pos = known[0]
        text += f" The nearest way you know: {_end_name(p, end)}, about {d} steps {direction(pos[0] - c.x, pos[1] - c.y)}."
    return text


def _handoff_climb(world: World, c: Creature, it: Intention) -> bool:
    words = _words(it.target)
    if words in ({"down"}, {"up"}):
        return True
    below = _level(world, c.x, c.y) < 0
    if below:
        return bool(words & {"surface", "daylight", "outside"})
    phrase = " ".join(w for w in it.target.lower().replace("_", " ").split() if w != "the")
    return phrase in DEEP_PHRASES  # "deep water" and the like stay plain walks


def _climb_fits(world: World, c: Creature) -> float | None:
    return 6.4 if portal_near(world, c.x, c.y, 1) else None


def _way_line(world: World, c: Creature) -> str | None:
    """The way down or up near you, said when it changes and when you wake."""
    _known_ends(world, c, sight_only=True)  # notes the ends in sight as known ways
    surface = _level(world, c.x, c.y) >= 0
    near = sorted(((dist(c.x, c.y, *pos), p, end, pos) for p, end, pos in _ends_here(world, c)
                   if dist(c.x, c.y, *pos) <= 3), key=lambda t: t[0])
    line = None
    if surface:
        for d, p, end, pos in near:
            if end != "up":
                continue
            where = perception._where(d, direction(pos[0] - c.x, pos[1] - c.y))
            if p["kind"] == "cave":
                line = f"A dark cave mouth opens {where}; cool air breathes out of it."
                if not perception.carried_light(c)[0]:
                    line += " Inside it is pitch dark: a torch (a stick, plant fiber and charcoal) would light the way."
            elif p["kind"] == "shaft":
                line = f"A mine shaft drops into the dark {where}; a ladder leads down."
            elif d <= 1:
                line = "You stand at the edge of an open pit; far below, the dark of the deep."
            else:
                line = f"An open pit gapes {where}; far below, the dark of the deep."
            break
    else:
        for d, p, end, pos in near:
            if end != "down":
                continue
            where = perception._where(d, direction(pos[0] - c.x, pos[1] - c.y))
            line = (f"Grey daylight glimmers {where}: the way up to {p['name']}." if p["kind"] == "cave"
                    else f"A ladder {where} leads up to {p['name']}.")
            break
        else:
            known = [t for t in _known_ends(world, c) if t[2] == "down"]
            if known:
                d, p, end, pos = known[0]
                line = (f"The nearest way up you know: {_end_name(p, end)}, about {max(5, 5 * round(d / 5))} steps "
                        f"{direction(pos[0] - c.x, pos[1] - c.y)}.")
            else:
                line = "You don't know a way up from here."
    mine = c.ext.get(PACK) or {}
    if line is None or (line == mine.get("told") and c.wake_reason != "woke"):
        if line is None:
            mine.pop("told", None)
        return None
    c.ext.setdefault(PACK, {})["told"] = line
    return line


actions.way_to_region = _way_to_region
register_verb("climb", _climb, aliases=("climb_down", "climb_up", "descend", "ascend", "go_down", "go_up"))
register_handoff("walk_to", "climb", _handoff_climb)
register_technique(Technique("climb", CLIMB_LINE, _climb_fits))
register_perception(_way_line, priority=40)


# ------------------------------------------------------------------ light: torches
TORCH_TICKS = 800
TORCH_EVERY = 10
TORCH_LOW, TORCH_GUTTERING = 200, 60
LIGHT_ITEMS["lit_torch"] = 4
LIGHT_LINE = ("light (target): light the torch you carry at a burning campfire beside you, or from someone's lit torch; "
              "it burns a while and lights the dark.")
FIRE_WORDS = {"fire", "campfire"}


def _lit_friend(world: World, c: Creature, reach: int) -> bool:
    return any(o is not c and not o.collapsed and o.inventory.get("lit_torch") and dist(c.x, c.y, o.x, o.y) <= reach
               and world.same_region((c.x, c.y), (o.x, o.y)) for o in world.creatures.values())


def _light(world: World, c: Creature, it: Intention) -> ActionResult:
    from ..actions import ActionResult, _busy
    if c.inventory.get("lit_torch"):
        return ActionResult(False, "Your torch is already burning.")
    if not c.inventory.get("torch"):
        return ActionResult(False, "You have no torch to light. (A torch is a stick, plant fiber and charcoal.)")
    at_fire = actions.station_near(world, c, "campfire", 1)
    if not (at_fire or _lit_friend(world, c, 1)):
        return ActionResult(False, "There's no fire beside you to light it from: a burning campfire, or someone's lit torch.")
    c.inventory["torch"] -= 1
    if c.inventory["torch"] <= 0:
        del c.inventory["torch"]
    c.inventory["lit_torch"] += 1
    mine = c.ext.setdefault(PACK, {})
    mine["torch_until"] = world.tick + TORCH_TICKS
    mine["torch_said"] = 0
    text = "You light your torch at the campfire." if at_fire else "You light your torch from a friend's."
    return _busy(c, 2, "lighting a torch", text + " It burns a good while and lights the dark around you.")


def _handoff_light(world: World, c: Creature, it: Intention) -> bool:
    """"Light the campfire" feeds it when there is no torch to light."""
    return bool(_words(it.target) & FIRE_WORDS) and not c.inventory.get("torch")


def _torch_out(sim, c: Creature) -> None:
    w = sim.world
    c.inventory["lit_torch"] -= 1
    if c.inventory["lit_torch"] <= 0:
        del c.inventory["lit_torch"]
    c.inventory["stick"] += 1
    mine = c.ext[PACK]
    mine.pop("torch_until", None)
    text = "Your torch burned out, leaving a charred stick."
    if not w.under_sky(c.x, c.y) and perception.light_range(w, c) == DARK_SIGHT:
        text += " It is pitch dark."
    sim.remember(c, text, 2)


def _torches(sim, t: int) -> None:
    w = sim.world
    for c in w.creatures.values():
        mine = c.ext.get(PACK) or {}
        if c.collapsed or c.asleep:  # a body in stasis or collapsed burns nothing: the torch waits
            if "torch_until" in mine:
                mine["torch_until"] += TORCH_EVERY
            continue
        if not c.inventory.get("lit_torch"):
            mine.pop("torch_until", None)
        elif "torch_until" not in mine:  # lit when it came to this holder: a fresh burn
            m = c.ext.setdefault(PACK, {})
            m["torch_until"], m["torch_said"] = t + TORCH_TICKS, 0
        elif t >= mine["torch_until"]:
            _torch_out(sim, c)
    for (x, y), pile in list(w.ground.items()):  # a lit torch not carried gutters out
        n = pile.get("lit_torch", 0)
        if n:
            w.take_items(x, y, "lit_torch", n)
            w.drop_items(x, y, Counter(stick=n))
    for o in w.objects.values():
        if o.kind in STORES and o.data.get("items", {}).get("lit_torch"):
            items = o.data["items"]
            items["stick"] = items.get("stick", 0) + items.pop("lit_torch")
            w.changed_objects.add(o.id)


def _torch_line(world: World, c: Creature) -> str | None:
    mine = c.ext.get(PACK) or {}
    if not c.inventory.get("lit_torch") or "torch_until" not in mine:
        return None
    left, said = mine["torch_until"] - world.tick, mine.get("torch_said", 0)
    if left < TORCH_GUTTERING and said < 2:
        mine["torch_said"] = 2
        return "Your torch is guttering; it will go out any moment."
    if left < TORCH_LOW and said < 1:
        mine["torch_said"] = 1
        return "Your torch is burning low."
    return None


def _light_fits(world: World, c: Creature) -> float | None:
    if c.inventory.get("torch") and not c.inventory.get("lit_torch") and (
            actions.station_near(world, c, "campfire", 3) or _lit_friend(world, c, 3)):
        return 5.6
    return None


register_verb("light", _light, aliases=("light_torch", "kindle", "ignite"))
register_handoff("light", "give", _handoff_light)
register_system("underground torches", TORCH_EVERY, _torches)
register_perception(_torch_line, priority=35)
register_technique(Technique("light", LIGHT_LINE, _light_fits))
