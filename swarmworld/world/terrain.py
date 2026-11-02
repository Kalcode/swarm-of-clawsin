"""Seeded world generation: terrain, water, hills, forests and resources."""

from __future__ import annotations

import math
import random

from .catalog import Catalog
from .model import World

TERMINAL_READY = (
    "THE TERMINAL HUMS. ITS SCREEN GLOWS GREEN.",
    "> READY: awaiting a Lua program",
    '> example:  say("hello")',
    "> example:  for _,t in ipairs(scan(5)) do print(t.name) end",
)

TABLET_TEXT = (
    "The stone is carved with careful letters: 'THE TERMINAL LISTENS TO LUA. "
    "Stand beside it and PROGRAM it with Lua code. It runs your program again every ten heartbeats. "
    "It knows: say(msg) speaks aloud; scan(r) returns the things within r steps, each with kind, name, dx, dy; "
    "time() returns tick, day and phase; print(x) writes to its screen (READ the terminal to see it); "
    "memory is a table it keeps between runs. "
    "Example: say(\"hello\")  or  for _,t in ipairs(scan(5)) do print(t.name..\" at \"..t.dx..\",\"..t.dy) end'"
)


def _value_noise(rng: random.Random, w: int, h: int, cell: int) -> list[list[float]]:
    gw, gh = w // cell + 2, h // cell + 2
    lattice = [[rng.random() for _ in range(gw)] for _ in range(gh)]

    def smooth(t: float) -> float:
        return t * t * (3 - 2 * t)

    out = []
    for y in range(h):
        row = []
        gy, fy = divmod(y / cell, 1)
        gy = int(gy)
        sy = smooth(fy)
        for x in range(w):
            gx, fx = divmod(x / cell, 1)
            gx = int(gx)
            sx = smooth(fx)
            a = lattice[gy][gx] + (lattice[gy][gx + 1] - lattice[gy][gx]) * sx
            b = lattice[gy + 1][gx] + (lattice[gy + 1][gx + 1] - lattice[gy + 1][gx]) * sx
            row.append(a + (b - a) * sy)
        out.append(row)
    return out


def _fractal(rng: random.Random, w: int, h: int) -> list[list[float]]:
    layers = [(_value_noise(rng, w, h, 16), 0.55), (_value_noise(rng, w, h, 8), 0.3), (_value_noise(rng, w, h, 4), 0.15)]
    return [[sum(l[y][x] * wgt for l, wgt in layers) for x in range(w)] for y in range(h)]


ANIMAL_POPULATION = {"chicken": 6, "sheep": 5, "cow": 4}


def spawn_animals(world: World, rng: random.Random, limit: int | None = None) -> int:
    """Top up wild animal numbers on open grassland away from the meadow. Returns how many were added."""
    cx, cy = world.center
    added = 0
    for kind, target in ANIMAL_POPULATION.items():
        have = sum(1 for o in world.objects.values() if o.kind == kind)
        tries = 0
        while have < target and tries < 4000 and (limit is None or added < limit):
            tries += 1
            x, y = rng.randrange(world.width), rng.randrange(world.height)
            if ((x, y) not in world.grid and world.tile(x, y) in "gd" and 8 < math.hypot(x - cx, y - cy) < 28
                    and not world.occupied(x, y)):
                world.add_object(kind, x, y)
                have += 1
                added += 1
    return added


def generate_world(seed: int = 7, width: int = 64, height: int = 64) -> World:
    rng = random.Random(seed)
    elev = _fractal(rng, width, height)
    moist = _fractal(rng, width, height)
    cx, cy = width // 2, height // 2

    def near_center(x: int, y: int, r: float) -> bool:
        return math.hypot(x - cx, y - cy) <= r

    tiles = [["g"] * width for _ in range(height)]
    for y in range(height):
        for x in range(width):
            e, m = elev[y][x], moist[y][x]
            if e > 0.64:
                tiles[y][x] = "r"
            elif m > 0.56:
                tiles[y][x] = "f"
            elif m < 0.33:
                tiles[y][x] = "d"

    # Lake in a random quadrant, away from the meadow.
    qx = rng.choice([width // 4, 3 * width // 4])
    qy = rng.choice([height // 4, 3 * height // 4])
    lake_r = rng.uniform(5.0, 7.5)
    for y in range(height):
        for x in range(width):
            d = math.hypot(x - qx, y - qy) + (elev[y][x] - 0.5) * 6
            if d < lake_r * 0.55:
                tiles[y][x] = "W"
            elif d < lake_r:
                tiles[y][x] = "w"

    # River: wander from the lake toward the farthest map edge, avoiding the meadow.
    x, y = float(qx), float(qy)
    tx = 0 if qx > cx else width - 1
    ty = rng.randint(4, height - 5)
    for _ in range(width * 3):
        ix, iy = int(round(x)), int(round(y))
        if not (0 <= ix < width and 0 <= iy < height):
            break
        for ox in (0, 1):
            px, py = ix + ox, iy
            if 0 <= px < width and 0 <= py < height and not near_center(px, py, 8) and tiles[py][px] != "W":
                tiles[py][px] = "w"
        ang = math.atan2(ty - y, tx - x) + rng.uniform(-0.9, 0.9)
        x += math.cos(ang)
        y += math.sin(ang)
        if abs(ix - tx) <= 1:
            break

    # Shores.
    for y in range(height):
        for x in range(width):
            if tiles[y][x] in "wW":
                continue
            if any(
                0 <= x + dx < width and 0 <= y + dy < height and tiles[y + dy][x + dx] in "wW"
                for dx in (-1, 0, 1) for dy in (-1, 0, 1)
            ) and rng.random() < 0.75:
                tiles[y][x] = "s"

    # Meadow at the center.
    for y in range(height):
        for x in range(width):
            if near_center(x, y, 5.5):
                tiles[y][x] = "g"

    world = World(width, height, tiles, Catalog.load(), seed)

    def free(x: int, y: int) -> bool:
        return world.in_bounds(x, y) and (x, y) not in world.grid and tiles[y][x] not in "wW" and not near_center(x, y, 4.5)

    for y in range(height):
        for x in range(width):
            if not free(x, y):
                continue
            t, r = tiles[y][x], rng.random()
            if t == "f":
                if r < 0.33:
                    world.add_object("pine" if elev[y][x] > 0.52 else "tree", x, y, wood=6)
                elif r < 0.39:
                    world.add_object("bush", x, y, berries=6)
            elif t == "g":
                if r < 0.04:
                    world.add_object("tree", x, y, wood=6)
                elif r < 0.07:
                    world.add_object("bush", x, y, berries=6)
            elif t == "d":
                if r < 0.015:
                    world.add_object("rock", x, y)
                elif r < 0.03:
                    world.add_object("bush", x, y, berries=6)
            elif t == "r":
                if r < 0.025:
                    world.add_object("copper_vein", x, y, ore=8)
                elif r < 0.04:
                    world.add_object("iron_vein", x, y, ore=8)
                elif r < 0.30:
                    world.add_object("rock", x, y)
            elif t == "s":
                if r < 0.07:
                    world.add_object("clay", x, y, clay=6)

    # Guarantee minimum counts (and something useful within reach of the meadow).
    def ensure(kind: str, n: int, tile_ok: str, near: float | None = None, **data) -> None:
        have = sum(1 for o in world.objects.values() if o.kind == kind)
        tries = 0
        while have < n and tries < 5000:
            tries += 1
            x, y = rng.randrange(width), rng.randrange(height)
            if near is not None and not (4.5 < math.hypot(x - cx, y - cy) <= near):
                continue
            if free(x, y) and tiles[y][x] in tile_ok:
                world.add_object(kind, x, y, **data)
                have += 1

    ensure("tree", 60, "gfd", wood=6)
    ensure("bush", 40, "gfd", berries=6)
    ensure("rock", 30, "rdg")
    ensure("copper_vein", 4, "r", ore=8)
    ensure("iron_vein", 3, "r", ore=8)
    ensure("clay", 6, "s", clay=6)
    # A starter kit of resources near the meadow.
    for kind, data in (("tree", {"wood": 6}), ("bush", {"berries": 4}), ("rock", {})):
        before = sum(1 for o in world.objects.values() if o.kind == kind and math.hypot(o.x - cx, o.y - cy) <= 10)
        ensure_near = before + 3
        tries = 0
        while before < ensure_near and tries < 3000:
            tries += 1
            x, y = cx + rng.randint(-10, 10), cy + rng.randint(-10, 10)
            if free(x, y) and tiles[y][x] in "gdf" and math.hypot(x - cx, y - cy) <= 10:
                world.add_object(kind, x, y, **data)
                before += 1

    spawn_animals(world, rng)

    # Two ancient terminals with tablets, far from the meadow.
    placed = 0
    tries = 0
    while placed < 2 and tries < 5000:
        tries += 1
        x, y = rng.randrange(2, width - 2), rng.randrange(2, height - 2)
        if math.hypot(x - cx, y - cy) < 15 or not free(x, y) or tiles[y][x] in "wW":
            continue
        if any(o.kind == "terminal" and math.hypot(o.x - x, o.y - y) < 20 for o in world.objects.values()):
            continue
        spots = [(x + dx, y + dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)) if free(x + dx, y + dy)]
        if not spots:
            continue
        world.add_object("terminal", x, y, code="", screen=list(TERMINAL_READY), memory={})
        tx, ty = spots[0]
        world.add_object("tablet", tx, ty, text=TABLET_TEXT)
        placed += 1

    world.changed_objects.clear()
    return world
