"""Nature: what grows and lives in the biomes. swarmworld/world/terrain.py shapes the land (biomes, the lake, rivers
that flow); this pack keeps that in world.ext["nature"] and fills it (data: swarmworld/data/packs/nature/):

- flowers, reeds, mushrooms, shells, driftwood and flint to gather, placed by biome (data-only kinds with yields);
  mushrooms, shells and driftwood are used up and new ones turn up out of sight now and then;
- bees by the flowers and butterflies by day, fireflies at dusk and night (a soft glow: see perception.near_glow);
  none in the rain;
- things dropped in a river drift downstream; at the edge of the map the river carries them off;
- two short perception lines: the biome you're in (when it changes, or when you wake) and which way the river beside
  you flows (when you come to it).

A world from before this pack gets biomes and flow read from its tiles, and a lighter scattering of plants away from
what its creatures built, once."""

from __future__ import annotations

import math
import random
from collections import Counter
from typing import TYPE_CHECKING
from weakref import WeakKeyDictionary

from .. import model
from ..perception import DAY_SIGHT, DIRS
from ..registry import register_perception, register_populate, register_system
from ..terrain import FLOW_STEP, NEIGHBORS, SIZE, STILL, derive_biomes, derive_flow, flow_at, water_near

if TYPE_CHECKING:  # never at the top for real: simulation imports the packs (see registry.py)
    from ..model import Creature, World
    from ..simulation import Simulation

PLANTS = ("flower_patch", "picked_flowers", "reed_bed", "cut_reeds", "mushroom_patch", "shell_bed", "driftwood",
          "flint_outcrop")
INSECTS = ("honeybee", "butterfly", "firefly")
RENEWING = ("mushroom_patch", "shell_bed", "driftwood")  # used up and gone; new ones turn up (renew_step)

BIOME_LINES = {
    "m": "You're in open meadow: grass, wildflowers and berry bushes.",
    "o": "You're in an oak forest: tall oaks, berry bushes, mushrooms in the shade.",
    "p": "You're in a pine forest: dark pines on rising ground, mushrooms underfoot.",
    "k": "You're in a marsh: soft wet ground, still pools, reed beds and clay.",
    "h": "You're in the rocky hills: boulders, flint and streaked ore rock.",
    "b": "You're on a sandy beach by the lake: shells and driftwood wash up here.",
}
RIVER_RETELL = 12  # steps along a river before it's worth saying again which way it flows
BIOME_REACH, BIOME_KEEP = 2, 1 / 3  # the land within 2 steps decides where you are; a third of it keeps you there

INSECTS_EVERY = 10
DRIFT_EVERY = 4  # a tile downstream every few ticks
RENEW_EVERY = 300
INSECT_CAP = {"honeybee": 24, "butterfly": 18, "firefly": 40}  # on a fresh map; smaller maps get fewer
FLOWERS_PER_BEE = 6
ARRIVE, LEAVE = 3, 5  # insects that come or go per evaluation, for a gentle change at dawn and dusk
FLIT = {"honeybee": 0.4, "butterfly": 0.5, "firefly": 0.25}  # chance an insect moves a tile per evaluation
OLD_WORLD_DENSITY = 0.5  # plants in a world from before this pack, which its creatures have already shaped


# ------------------------------------------------------------------------------------------- reading the land
def _free(world: World, x: int, y: int) -> bool:
    return (world.in_bounds(x, y) and (x, y) not in world.grid and world.tile(x, y) not in "wW"
            and not world.occupied(x, y))


_CACHE: WeakKeyDictionary = WeakKeyDictionary()  # world -> its habitats and its ambient randomness (not saved)


def _ambient(world: World) -> dict:
    """Per world: tiles each kind of thing lives on, and a random source of its own (so ambience never shifts the
    world's own rolls). Recomputed when the world's biome rows change (a restore)."""
    rows = (world.ext.get("nature") or {}).get("biomes")
    got = _CACHE.get(world)
    if got is None or got["rows"] is not rows:
        tiles: dict[str, list[tuple[int, int]]] = {"forest": [], "beach": [], "meadow": [], "firefly": []}
        damp = water_near(world, 2)
        for y in range(world.height if rows else 0):
            row, trow = rows[y], world.tiles[y]
            for x in range(world.width):
                t, b = trow[x], row[x]
                if t in "wW":
                    continue
                if b in "op" and t == "f":
                    tiles["forest"].append((x, y))
                elif b == "b" and t == "s":
                    tiles["beach"].append((x, y))
                elif b == "m":
                    tiles["meadow"].append((x, y))
                if b in "ko" or damp[y, x]:
                    tiles["firefly"].append((x, y))
        rng = got["rng"] if got else random.Random(world.width * 7919 + world.height)
        got = {"rows": rows, "tiles": tiles, "firefly": set(tiles["firefly"]), "rng": rng}
        _CACHE[world] = got
    return got


HABITAT = {"mushroom_patch": "forest", "shell_bed": "beach", "driftwood": "beach"}


# ------------------------------------------------------------------------------------------- placing plants
def _near_built(world: World) -> set[tuple[int, int]]:
    """Tiles within 3 steps of what creatures made or planted, and of the old landmarks: kept clear in old worlds."""
    spots = [(o.x, o.y) for o in world.objects.values()
             if o.data.get("builder") or o.data.get("planter") or o.kind in ("crop", "sapling", "campfire", "terminal",
                                                                             "tablet", "wishing_stone")]
    spots += [(c.x, c.y) for c in world.creatures.values()]
    return {(x + dx, y + dy) for x, y in spots for dx in range(-3, 4) for dy in range(-3, 4)}


def _plant_for(b: str, t: str, wet: bool, r: float) -> str | None:
    """What grows on a free tile of biome b and tile t (wet: beside water), for a roll r in [0, 1)."""
    if b == "k":
        if r < (0.30 if wet else 0.07):
            return "reed_bed"
        return "flower_patch" if r < (0.31 if wet else 0.08) else None
    if b == "b":
        return ("shell_bed" if r < 0.08 else "driftwood" if r < 0.12 else None) if t == "s" else None
    if b == "h":
        return "flint_outcrop" if t == "r" and r < 0.025 else None
    if wet and r < 0.08:
        return "reed_bed"
    if b == "o" and t == "f":
        return "mushroom_patch" if r < 0.025 else "flower_patch" if r < 0.03 else None
    if b == "p" and t == "f":
        return "mushroom_patch" if r < 0.02 else None
    if b == "m":
        return "flower_patch" if r < (0.045 if t == "g" else 0.01) else None
    return None


def _place_plants(world: World, rng, fresh: bool) -> dict[str, int]:
    rows = world.ext["nature"]["biomes"]
    density = 1.0 if fresh else OLD_WORLD_DENSITY
    clear = set() if fresh else _near_built(world)
    cx, cy = world.center
    wet = water_near(world)
    placed: Counter = Counter()
    for y in range(world.height):
        row, trow = rows[y], world.tiles[y]
        for x in range(world.width):
            t = trow[x]
            if t in "wW" or (x, y) in world.grid or (x, y) in clear or math.hypot(x - cx, y - cy) <= 4.5:
                continue
            kind = _plant_for(row[x], t, bool(wet[y, x]), rng.random() / density)
            if kind and not world.occupied(x, y):
                world.add_object(kind, x, y)
                placed[kind] += 1
    return {kind: placed[kind] for kind in RENEWING}


def populate(world: World, rng, fresh: bool) -> None:
    """Keep the land the generator shaped (world.land), or read it from an older world's tiles; plant once."""
    mine = world.ext.setdefault("nature", {})
    land = getattr(world, "land", None) or {}
    if "biomes" not in mine:
        mine["biomes"] = land.get("biomes") or derive_biomes(world)
    if "flow" not in mine:
        mine["flow"] = land.get("flow") or derive_flow(world)
    if not mine.get("planted"):
        mine["targets"] = _place_plants(world, rng, fresh)
        mine["planted"] = True


# ------------------------------------------------------------------------------------------- systems
def _spot_near(world: World, rng: random.Random, x: int, y: int, r: int) -> tuple[int, int] | None:
    opts = [(x + dx, y + dy) for dx in range(-r, r + 1) for dy in range(-r, r + 1) if dx or dy]
    rng.shuffle(opts)
    return next((p for p in opts if _free(world, *p)), None)


def _near_flowers(world: World, x: int, y: int) -> bool:
    for dy in range(-2, 3):
        for dx in range(-2, 3):
            o = world.object_at(x + dx, y + dy)
            if o and o.kind in ("flower_patch", "picked_flowers"):
                return True
    return False


def _insect_spot(world: World, kind: str, flowers: list, amb: dict) -> tuple[int, int] | None:
    rng = amb["rng"]
    if kind == "honeybee" or (kind == "butterfly" and flowers and rng.random() < 0.6):
        if not flowers:
            return None
        f = rng.choice(flowers)
        return _spot_near(world, rng, f.x, f.y, 1 if kind == "honeybee" else 2)
    pool = amb["tiles"]["meadow" if kind == "butterfly" else "firefly"]
    for _ in range(12):
        if pool:
            p = rng.choice(pool)
            if _free(world, *p):
                return p
    return None


def _flit(world: World, o, amb: dict) -> None:
    rng = amb["rng"]
    opts = [(o.x + dx, o.y + dy) for dx, dy in NEIGHBORS]
    rng.shuffle(opts)
    for x, y in opts:
        if not _free(world, x, y):
            continue
        if o.kind == "honeybee" and not _near_flowers(world, x, y):
            continue
        if o.kind == "firefly" and (x, y) not in amb["firefly"]:
            continue
        world.move_object(o, x, y)
        return


def insects_step(sim: Simulation, t: int) -> None:
    """Bees and butterflies by day, fireflies at dusk and night, none in the rain: a few arrive or leave each time,
    the rest flit about. Ambience only; they never do anything to anyone."""
    w = sim.world
    if not (w.ext.get("nature") or {}).get("biomes"):
        return
    amb = _ambient(w)
    phase = w.clock()["phase"]
    rainy = model.wet(w, drizzle=True)  # the insects shelter from it
    scale = w.width * w.height / (SIZE * SIZE)
    flowers, have = [], {k: [] for k in INSECTS}
    for o in w.objects.values():
        if o.kind == "flower_patch":
            flowers.append(o)
        elif o.kind in have:
            have[o.kind].append(o)
    day = phase == "day" and not rainy
    want = {"honeybee": min(round(INSECT_CAP["honeybee"] * scale), len(flowers) // FLOWERS_PER_BEE) if day else 0,
            "butterfly": round(INSECT_CAP["butterfly"] * scale) if day else 0,
            "firefly": round(INSECT_CAP["firefly"] * scale) if phase in ("dusk", "night") and not rainy else 0}
    rng = amb["rng"]
    for kind, objs in have.items():
        extra = len(objs) - want[kind]
        if extra > 0:
            for o in rng.sample(objs, min(extra, LEAVE)):
                w.remove_object(o.id)
                objs.remove(o)
        else:
            for _ in range(min(-extra, ARRIVE)):
                spot = _insect_spot(w, kind, flowers, amb)
                if spot:
                    w.add_object(kind, *spot)
        for o in objs:
            if rng.random() < FLIT[kind]:
                _flit(w, o, amb)


def _move_pile(w: World, src: tuple[int, int], dst: tuple[int, int] | None) -> None:
    pile = w.ground.pop(src)
    key = f"pile:{src[0]}:{src[1]}"
    w.changed_objects.discard(key)
    w.removed_objects.add(key)
    if dst is not None:
        w.removed_objects.discard(f"pile:{dst[0]}:{dst[1]}")
        w.drop_items(*dst, pile)


def drift_step(sim: Simulation, t: int) -> None:
    """Whatever lies in flowing water moves a tile downstream; into shallow still water it settles, against deep water
    it snags; off the edge of the map the river carries it away."""
    w = sim.world
    flow = (w.ext.get("nature") or {}).get("flow")
    if not flow or not w.ground:
        return
    moves = []
    for x, y in w.ground:
        if w.in_bounds(x, y) and flow[y][x] != STILL:
            dx, dy = FLOW_STEP[DIRS[int(flow[y][x])]]
            moves.append(((x, y), (x + dx, y + dy)))
    for src, (nx, ny) in moves:
        if not w.in_bounds(nx, ny):
            _move_pile(w, src, None)
        elif w.tile(nx, ny) == "w":
            _move_pile(w, src, (nx, ny))


def renew_step(sim: Simulation, t: int) -> None:
    """New mushrooms come up in the forests (more after rain), shells and driftwood wash up on the beach: out of sight
    of everyone, a few at a time, never more than the world started with."""
    w = sim.world
    mine = w.ext.get("nature") or {}
    targets = mine.get("targets")
    if not targets:
        return
    amb = _ambient(w)
    rng = amb["rng"]
    have = Counter(o.kind for o in w.objects.values() if o.kind in RENEWING)
    watchers = [(c.x, c.y) for c in w.creatures.values() if not c.collapsed]
    rainy = model.wet(w, drizzle=True)  # mushrooms come up faster in the wet
    for kind in RENEWING:
        target = targets.get(kind, 0)
        n = min(target - have[kind], max(1, target // 10) * (2 if rainy and kind == "mushroom_patch" else 1))
        pool = amb["tiles"][HABITAT[kind]]
        for _ in range(max(0, n)):
            for _try in range(20):
                x, y = rng.choice(pool) if pool else (0, 0)
                if pool and _free(w, x, y) and all(max(abs(x - cx), abs(y - cy)) > DAY_SIGHT for cx, cy in watchers):
                    w.add_object(kind, x, y)
                    break


# ------------------------------------------------------------------------------------------- perception
def biome_around(world: World, x: int, y: int, was: str | None = None) -> str | None:
    """The biome code of the land around (x, y): what most of it within BIOME_REACH steps is, except that you're still
    in the biome you were in while at least BIOME_KEEP of the ground around is that (so a ragged edge doesn't flap)."""
    rows = (world.ext.get("nature") or {}).get("biomes")
    if not rows:
        return None
    seen: Counter = Counter()
    for yy in range(y - BIOME_REACH, y + BIOME_REACH + 1):
        for xx in range(x - BIOME_REACH, x + BIOME_REACH + 1):
            if world.in_bounds(xx, yy) and world.tile(xx, yy) not in "wW":
                seen[rows[yy][xx]] += 1
    if not seen:
        return None
    if was in seen and seen[was] >= BIOME_KEEP * sum(seen.values()):
        return was
    return max(seen, key=lambda b: (seen[b], b))


def biome_line(world: World, c: Creature) -> str | None:
    """The biome you're in, said when it changes and when you wake."""
    told = (c.ext.get("nature") or {}).get("biome")
    code = biome_around(world, c.x, c.y, told)
    if code is None or (code == told and c.wake_reason != "woke"):
        return None
    c.ext.setdefault("nature", {})["biome"] = code
    return BIOME_LINES.get(code)


def river_line(world: World, c: Creature) -> str | None:
    """Which way the river beside you flows: when you come to it, when you wake, and again farther along."""
    if not (world.ext.get("nature") or {}).get("flow"):
        return None
    ways = Counter(f for dx in (-1, 0, 1) for dy in (-1, 0, 1) if (f := flow_at(world, c.x + dx, c.y + dy)))
    mine = c.ext.get("nature") or {}
    if not ways:
        mine.pop("river", None)
        return None
    told = mine.get("river")
    if told and max(abs(told[0] - c.x), abs(told[1] - c.y)) <= RIVER_RETELL and c.wake_reason != "woke":
        return None
    c.ext.setdefault("nature", {})["river"] = [c.x, c.y]
    way = max(ways, key=lambda d: (ways[d], -DIRS.index(d)))
    return f"The river beside you flows {way}."


register_populate("nature", populate)
register_system("nature insects", INSECTS_EVERY, insects_step)
register_system("nature drift", DRIFT_EVERY, drift_step)
register_system("nature renewal", RENEW_EVERY, renew_step)
register_perception(biome_line, priority=55)  # where you are: above ambience, below anything urgent
register_perception(river_line, priority=56)
