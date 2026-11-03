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

State: world.ext["underground"] = {"seed": int, "caves": [{"name", "x", "y"}], "portals": [{"id", "kind", "name",
"up": [x, y], "down": [x, y]}]}. Nothing here draws from world.rng or the generator's rng (the deep and its mouths
roll their own random.Random, seeded from the deep's seed), so the surface's weather, animals and placement roll as
before."""

from __future__ import annotations

import json
import random
import zlib
from collections import Counter
from typing import TYPE_CHECKING

from .. import perception
from ..caves import BORDER, carve_deep, carve_passage
from ..catalog import DATA
from ..model import SOLID_TILES, WATER_TILES
from ..perception import direction, dist
from ..registry import register_landmarks, register_populate

if TYPE_CHECKING:  # never at the top for real: simulation imports the packs (see registry.py)
    from ..model import Region, World

PACK = "underground"
CONFIG = json.loads((DATA / "packs" / PACK / "underground.json").read_text())
MOUTH_AWAY = 20  # cave mouths lie this far from the meadow's middle (a quarter of a smaller map): beyond its landmarks
MOUTH_APART = 12
MOUTH_CLEAR = 3  # steps kept between a cave mouth and anything a creature built or planted
ORDINALS = ("second", "third", "fourth", "fifth")
PORTAL_OBJECTS = {"cave": ("cave_mouth", "cave_exit"), "shaft": ("mine_shaft", "ladder"), "pit": (None, "ladder")}


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
    pid = f"p{max((int(p['id'][1:]) for p in have), default=0) + 1}"
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
    land = [(x, y) for y in rows for x in cols
            if world.tile(x, y) not in WATER_TILES + SOLID_TILES and (x, y) not in world.grid and (x, y) not in clear]
    want = rng.randint(3, 5)
    rocky = [p for p in land if world.tile(*p) == "r" and dist(*p, cx, cy) >= away]
    rest = [p for p in land if world.tile(*p) != "r" and dist(*p, cx, cy) >= away]
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


def _caves(deep: Region, caverns: list[tuple[int, int, int]], pool: tuple[int, int]) -> list[dict]:
    """The named caves: the largest caverns by CONFIG's cave_names, then the pool, at their middles."""
    named = [{"name": n, "x": x, "y": deep.y0 + y} for n, (x, y, _) in zip(CONFIG["cave_names"], caverns)]
    return named + [{"name": CONFIG["pool_name"], "x": pool[0], "y": deep.y0 + pool[1]}]


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
    mine["caves"] = _caves(deep, dm.caverns, dm.pool)
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
    world.changed_tiles.clear()
    world.changed_tiles.update(earlier)


def _populate(world: World, rng, fresh: bool) -> None:  # new worlds and old saves alike; never rolls the rng given
    grow_deep(world)


# ------------------------------------------------------------------ landmarks
def _places(world: World) -> list[dict]:
    mine = world.ext.get(PACK) or {}
    out = [{"name": c["name"], "x": c["x"], "y": c["y"], "kind": "cave"} for c in mine.get("caves", ())]
    for p in mine.get("portals", ()):
        out.append({"name": p["name"], "x": p["up"][0], "y": p["up"][1], "kind": "way down"})
        out.append({"name": f"the way up to {p['name']}", "x": p["down"][0], "y": p["down"][1], "kind": "way up"})
    return out


perception.REMEMBERED_KINDS.update({k for ends in PORTAL_OBJECTS.values() for k in ends if k})  # ways to find again
register_populate(PACK, _populate)
register_landmarks(_places)
