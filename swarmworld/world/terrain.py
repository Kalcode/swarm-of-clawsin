"""Seeded world generation: biomes, a lake with its beach and marsh, rivers that flow, hills, forests and resources.

A fresh world's surface is SIZE x SIZE (the underground pack grows the deep below it, past a band of rock). Its land
is shaped by an elevation field: rocky hills rise on one side, ringed by pine forest; the lake lies low on the other,
with a sandy beach on one shore and a marsh where a stream comes in; oak forest grows where it's moist, and open
meadow (with the creatures' starting meadow at the center) fills the rest. Two streams run from the hills down to the
lake and one river leaves it for the edge of the map.

The generator leaves each tile's biome and each river tile's flow in world.land; the nature pack
(swarmworld/world/packs/nature.py) keeps them in world.ext["nature"], saved with the world: "biomes" is rows of BIOMES
codes, "flow" rows of flow codes ("0".."7" index perception.DIRS, "." where water is still or there is none), one row
per row of the surface (the top band of the map, from row 0; a deep below has neither). Following the flow always leads
into the lake, into another river, or off the surface. An older world gets both read from its tiles (derive_biomes,
derive_flow)."""

from __future__ import annotations

import math
import random
from collections import deque

import numpy as np

from .catalog import Catalog
from .model import World
from .perception import DIRS
from .registry import run_populate

POOL = 0.76  # marsh ground with detail noise above this is a still pool
SIZE = 128  # a fresh world's width and surface height (older saves keep theirs)
DEEP_POPULATE = "underground"  # the populate hook that grows the deep below (swarmworld/world/packs/underground.py)
BIOMES = {"m": "meadow", "o": "oak forest", "p": "pine forest", "k": "marsh", "h": "rocky hills", "b": "beach"}
STILL = "."
FLOW_STEP = {"east": (1, 0), "southeast": (1, 1), "south": (0, 1), "southwest": (-1, 1),
             "west": (-1, 0), "northwest": (-1, -1), "north": (0, -1), "northeast": (1, -1)}
NEIGHBORS = tuple(FLOW_STEP.values())
_CODE = {step: str(DIRS.index(d)) for d, step in FLOW_STEP.items()}

TERMINAL_READY = (
    "THE TERMINAL HUMS. ITS SCREEN GLOWS GREEN.",
    "> READY: awaiting a Lua program",
    '> example:  say("hello")',
    "> example:  for _,t in ipairs(scan(5)) do print(t.name) end",
)

TABLET_TEXT = (
    "Carved letters on the stone: 'THE TERMINAL BESIDE ME OBEYS LUA. "
    "Stand next to it and use program, with Lua code as your text. It runs your code every 20 heartbeats. "
    "It can say(\"words\") aloud, scan(10) to list what is near it, find(\"copper\") to learn where the nearest copper "
    "(or clay, or berries...) lies, time() to tell the day, print(x) on its screen, and keep things in memory. "
    "A program that is only a question, like find(\"clay\"), shows its answer on the screen. "
    "Try: say(\"hello\")'"
)


# ------------------------------------------------------------------ reading the land
def surface_rows(world: World) -> range:
    """The rows of the surface: what the land rows (biomes, flow) describe, and all a whole-map scan should cover."""
    _, y0, _, y1 = world.region_bounds("surface")
    return range(y0, y1)


def land_code(world: World, key: str, x: int, y: int) -> str | None:
    """A tile's code in the land rows world.ext["nature"][key] ("biomes" or "flow"), or None off the surface, beyond
    the rows, or in a world without them."""
    rows = (world.ext.get("nature") or {}).get(key)
    if not rows or not 0 <= x < world.width or y not in surface_rows(world) or y >= len(rows):
        return None
    return rows[y][x]


def biome_at(world: World, x: int, y: int) -> str | None:
    """The biome's name ("meadow", "oak forest"...) at a tile, or None off the surface or in a world without biomes."""
    return BIOMES.get(land_code(world, "biomes", x, y))


def flow_at(world: World, x: int, y: int) -> str | None:
    """Which way the water at a tile flows ("south"...), or None where it's still, dry, unknown or off the surface."""
    ch = land_code(world, "flow", x, y)
    return DIRS[int(ch)] if ch not in (None, STILL) else None


# ------------------------------------------------------------------ noise and masks
def _value_noise(rng: random.Random, w: int, h: int, cell: int) -> np.ndarray:
    """Smooth noise in [0, 1], an (h, w) array: a random lattice every `cell` tiles, eased between."""
    gw, gh = w // cell + 2, h // cell + 2
    lattice = np.array([[rng.random() for _ in range(gw)] for _ in range(gh)])

    def axis(n: int) -> tuple[np.ndarray, np.ndarray]:
        t = np.arange(n) / cell
        g = t.astype(int)
        f = t - g
        return g, f * f * (3 - 2 * f)

    gx, sx = axis(w)
    gy, sy = axis(h)
    top, bot = lattice[gy], lattice[gy + 1]
    a = top[:, gx] + (top[:, gx + 1] - top[:, gx]) * sx
    b = bot[:, gx] + (bot[:, gx + 1] - bot[:, gx]) * sx
    return a + (b - a) * sy[:, None]


def _fractal(rng: random.Random, w: int, h: int, cells: tuple[int, int, int] = (16, 8, 4)) -> np.ndarray:
    return sum(_value_noise(rng, w, h, c) * wgt for c, wgt in zip(cells, (0.55, 0.3, 0.15)))


def near(mask: np.ndarray, r: int = 1) -> np.ndarray:
    """Tiles with a True tile within r steps (in any of the 8 directions), not counting themselves."""
    h, w = mask.shape
    pad = np.pad(mask, r)
    out = np.zeros_like(mask)
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            if dx or dy:
                out |= pad[r + dy:r + dy + h, r + dx:r + dx + w]
    return out


def water_near(world: World, r: int = 1) -> np.ndarray:
    """An (h, w) mask of the surface's tiles (h its rows) with water (shallow or deep) within r steps."""
    rows = surface_rows(world)
    t = np.array(world.tiles[rows.start:rows.stop])
    return near((t == "w") | (t == "W"), r)


def _cells(mask: np.ndarray) -> list[tuple[int, int]]:
    ys, xs = np.nonzero(mask)
    return list(zip(xs.tolist(), ys.tolist()))


def _turn(a: float) -> float:
    """An angle folded into [-pi, pi]."""
    return (a + math.pi) % (2 * math.pi) - math.pi


# ------------------------------------------------------------------ flow
def _flow_from_mouths(cells: set[tuple[int, int]], mouths: dict[tuple[int, int], tuple[int, int]],
                      hint: dict[tuple[int, int], tuple[float, float]] | None = None) -> dict[tuple[int, int], str]:
    """Flow codes for one river: its mouths flow out (into the lake, another river or off the map, as given); every
    other cell flows to a neighbouring cell one step nearer a mouth, the one best along the river's course (hint),
    so following the flow never loops and always ends at a mouth."""
    dist = {m: 0 for m in mouths}
    q = deque(sorted(mouths))
    while q:
        cur = q.popleft()
        for dx, dy in NEIGHBORS:
            nxt = (cur[0] + dx, cur[1] + dy)
            if nxt in cells and nxt not in dist:
                dist[nxt] = dist[cur] + 1
                q.append(nxt)
    out = {m: _CODE[step] for m, step in mouths.items()}
    for (x, y), d in dist.items():
        if d == 0:
            continue
        hx, hy = (hint or {}).get((x, y), (0.0, 0.0))
        best = max(((dx, dy) for dx, dy in NEIGHBORS if dist.get((x + dx, y + dy)) == d - 1),
                   key=lambda s: (s[0] * hx + s[1] * hy) / math.hypot(*s) - 0.01 * (abs(s[0]) + abs(s[1])))
        out[(x, y)] = _CODE[best]
    return out


def _rows(width: int, height: int, cells: dict[tuple[int, int], str], fill: str = STILL) -> list[str]:
    grid = [[fill] * width for _ in range(height)]
    for (x, y), ch in cells.items():
        grid[y][x] = ch
    return ["".join(r) for r in grid]


def _lake_tiles(world: World) -> set[tuple[int, int]]:
    """Still water on the surface: deep water and the shallows within two steps of it."""
    rows = surface_rows(world)
    deep = {(x, y) for y in rows for x in range(world.width) if world.tile(x, y) == "W"}
    near = {(x + dx, y + dy) for x, y in deep for dx in range(-2, 3) for dy in range(-2, 3)}
    return deep | {p for p in near if p[1] in rows and world.in_bounds(*p) and world.tile(*p) == "w"}


def _at_edge(x: int, y: int, width: int, height: int, margin: int = 0) -> bool:
    return x <= margin or y <= margin or x >= width - 1 - margin or y >= height - 1 - margin


def _off_map_step(x: int, y: int, width: int, height: int) -> tuple[int, int]:
    """Toward the edge of the map from a tile at (or one step from) it."""
    return (-1 if x <= 1 else 1 if x >= width - 2 else 0, -1 if y <= 1 else 1 if y >= height - 2 else 0)


def derive_flow(world: World) -> list[str]:
    """Flow for a world made before rivers flowed: shallow water away from the lake is river; a river that reaches the
    edge of the map (or stops a step short of it, as they did) flows out there, one that doesn't flows into the lake.
    The meadow cut the old river in two: each part flows its own way. Only the surface is read: one row per row of
    it."""
    rows = surface_rows(world)
    height = rows.stop  # the surface is the top of the map: its edge is the map's, but for the rock below
    lake = _lake_tiles(world)
    river = {(x, y) for y in rows for x in range(world.width)
             if world.tile(x, y) == "w" and (x, y) not in lake}
    flows: dict[tuple[int, int], str] = {}
    seen: set[tuple[int, int]] = set()
    for start in sorted(river):
        if start in seen:
            continue
        comp, q = {start}, deque([start])
        while q:
            cx, cy = q.popleft()
            for dx, dy in NEIGHBORS:
                n = (cx + dx, cy + dy)
                if n in river and n not in comp:
                    comp.add(n)
                    q.append(n)
        seen |= comp
        edge = {p: _off_map_step(*p, world.width, height) for p in comp  # older rivers stop a step short
                if _at_edge(*p, world.width, height, margin=1)}
        mouths = edge or {p: next(s for s in NEIGHBORS if (p[0] + s[0], p[1] + s[1]) in lake) for p in comp
                          if any((p[0] + dx, p[1] + dy) in lake for dx, dy in NEIGHBORS)}
        if not mouths:
            continue  # a pond: still
        mx = sum(x for x, _ in mouths) / len(mouths)
        my = sum(y for _, y in mouths) / len(mouths)
        hint = {(x, y): (mx - x, my - y) for x, y in comp}
        flows.update(_flow_from_mouths(comp, mouths, hint))
    return _rows(world.width, height, flows)


def derive_biomes(world: World) -> list[str]:
    """Biomes for a world made before biomes, read from its tiles: rocky ground is hills, sand is beach, forest is oak
    or pine forest by which trees grow nearest, the rest is meadow. Only the surface is read: one row per row of it."""
    pines, oaks = [], []
    for o in world.objects.values():
        if o.kind in ("pine", "tree", "stump"):
            (pines if o.kind == "pine" else oaks).append((o.x, o.y))
    rows = []
    for y in surface_rows(world):
        row = []
        for x in range(world.width):
            t = world.tile(x, y)
            if t == "r":
                row.append("h")
            elif t == "s":
                row.append("b")
            elif t == "f":
                p = sum(1 for px, py in pines if abs(px - x) <= 4 and abs(py - y) <= 4)
                o = sum(1 for ox, oy in oaks if abs(ox - x) <= 4 and abs(oy - y) <= 4)
                row.append("p" if p > o else "o")
            else:
                row.append("m")
        rows.append("".join(row))
    return rows


# ------------------------------------------------------------------ placing things
ANIMAL_POPULATION = {"chicken": 6, "sheep": 5, "cow": 4}


WISHING_TEXT = "Worn letters on the stone: 'TELL ME WHAT YOU WISH FOR. THE SKY LISTENS.'"


def place_wishing_stone(world: World) -> None:
    """An old stone at the meadow's north edge where creatures can make wishes (the experimenters read them)."""
    cx, cy = world.center
    for r in range(4, 12):
        for dx in range(-r, r + 1):
            x, y = cx + dx, cy - r
            if world.in_bounds(x, y) and world.tile(x, y) in "gd" and (x, y) not in world.grid:
                world.add_object("wishing_stone", x, y, text=WISHING_TEXT)
                return


def spawn_animals(world: World, rng: random.Random, limit: int | None = None) -> int:
    """Top up wild animal numbers on open grassland away from the meadow, on the surface. Returns how many were
    added."""
    cx, cy = world.center
    x0, y0, x1, y1 = world.region_bounds("surface")
    added = 0
    for kind, target in ANIMAL_POPULATION.items():
        have = sum(1 for o in world.objects.values() if o.kind == kind and y0 <= o.y < y1)
        tries = 0
        while have < target and tries < 4000 and (limit is None or added < limit):
            tries += 1
            x, y = rng.randrange(x0, x1), rng.randrange(y0, y1)
            if ((x, y) not in world.grid and world.tile(x, y) in "gd" and 8 < math.hypot(x - cx, y - cy) < 28
                    and not world.occupied(x, y)):
                world.add_object(kind, x, y)
                have += 1
                added += 1
    return added


# ------------------------------------------------------------------ the generator
def generate_world(seed: int = 7, width: int = SIZE, height: int = SIZE, deep: bool = True) -> World:
    """A world of width x height land. With deep (the default) the underground pack grows the deep below it, past a
    band of rock; deep=False leaves the surface alone, as worlds were before the deep (to compare the two)."""
    rng = random.Random(seed)
    s = max(0.5, min(width, height) / SIZE)  # 1 on a fresh map: distances below are in tiles of a 128 map
    cells = (max(4, round(32 * s)), max(4, round(16 * s)), max(2, round(8 * s)))
    elev_n = _fractal(rng, width, height, cells)
    moist_n = _fractal(rng, width, height, cells)
    detail = _value_noise(rng, width, height, max(2, round(3 * s)))  # pools, mud and sandy patches
    cx, cy = width // 2, height // 2
    meadow_r = 11 * s

    # The lake low in one quarter, the hills high on the far side of the meadow.
    lx = round(width * (rng.choice((0.27, 0.73)) + rng.uniform(-0.04, 0.04)))
    ly = round(height * (rng.choice((0.27, 0.73)) + rng.uniform(-0.04, 0.04)))
    lake_r = rng.uniform(9.0, 12.0) * s
    hill_ang = math.atan2(ly - cy, lx - cx) + math.pi + rng.uniform(-1.0, 1.0)
    hill_d = rng.uniform(0.30, 0.36) * min(width, height)
    hx = min(max(cx + math.cos(hill_ang) * hill_d, 0.12 * width), 0.88 * width)
    hy = min(max(cy + math.sin(hill_ang) * hill_d, 0.12 * height), 0.88 * height)

    yy, xx = np.mgrid[0:height, 0:width]

    def bump(px: float, py: float, r: float) -> np.ndarray:
        return np.exp(-((xx - px) ** 2 + (yy - py) ** 2) / (r * r))

    hill_w, lake_w, mid_w, wet_w = 0.2 * width, 0.18 * width, 0.12 * width, 0.3 * width
    elev = elev_n + 0.45 * bump(hx, hy, hill_w) - 0.35 * bump(lx, ly, lake_w) - 0.25 * bump(cx, cy, mid_w)
    moist = moist_n + 0.2 * bump(lx, ly, wet_w)

    def quantile(a: np.ndarray, q: float) -> float:
        flat = np.sort(a, axis=None)
        return float(flat[min(flat.size - 1, int(q * flat.size))])

    e_hill, e_pine = quantile(elev, 0.90), quantile(elev, 0.785)
    m_oak, m_dry = quantile(moist, 0.60), quantile(moist, 0.10)
    center_d = np.hypot(xx - cx, yy - cy)

    biome = np.full((height, width), "m", dtype="<U1")
    biome[moist >= m_oak] = "o"
    biome[elev >= e_pine] = "p"
    biome[elev >= e_hill] = "h"
    biome[center_d <= meadow_r] = "m"
    forest = (biome == "p") | (biome == "o")
    tiles = np.where(biome == "h", "r", np.where(forest, "f", np.where(moist < m_dry, "d", "g")))

    # The lake.
    lake_d = np.hypot(xx - lx, yy - ly) + (elev_n - 0.5) * 8 * s
    lake_m = lake_d < lake_r
    tiles[lake_m] = "w"
    tiles[lake_d < lake_r * 0.55] = "W"
    lake = set(_cells(lake_m))

    # Rivers: two streams from the hills down to the lake, and one river from the lake to the edge of the map.
    river_of: dict[tuple[int, int], int] = {}  # tile -> which river carved it
    flows: dict[tuple[int, int], str] = {}
    mouths_at_lake: list[tuple[int, int]] = []

    def walk(sx: float, sy: float, tx: float, ty: float, number: int, to_lake: bool) -> None:
        """Carve one river from (sx, sy) toward (tx, ty), meandering and bending round the meadow. A stream ends where
        it reaches the lake or joins an earlier river; the outflow (to_lake False) runs on to the edge of the map."""
        x, y = sx, sy
        ang = math.atan2(ty - y, tx - x)
        wob = 0.0
        path: list[tuple[int, int]] = []
        heading: dict[tuple[int, int], tuple[float, float]] = {}
        prev: tuple[int, int] | None = None
        keep_out = meadow_r + 2
        for _ in range(width * 4):
            ix, iy = round(x), round(y)
            if not (0 <= ix < width and 0 <= iy < height):
                break
            if to_lake and ((ix, iy) in lake or (ix, iy) in river_of):
                break  # into the lake, or into the first stream
            steps = [(ix, iy)]
            if prev is not None and max(abs(ix - prev[0]), abs(iy - prev[1])) > 1:  # no gaps in a river
                n = max(abs(ix - prev[0]), abs(iy - prev[1]))
                steps = [(round(prev[0] + (ix - prev[0]) * k / n), round(prev[1] + (iy - prev[1]) * k / n))
                         for k in range(1, n + 1)]
            for here in steps:
                if here in lake or here in river_of or math.hypot(here[0] - cx, here[1] - cy) <= meadow_r + 1:
                    continue
                path.append(here)
                heading[here] = (math.cos(ang), math.sin(ang))
                side = (0, 1) if abs(math.cos(ang)) > abs(math.sin(ang)) else (1, 0)
                wide = (here[0] + side[0], here[1] + side[1])
                if (0 <= wide[0] < width and 0 <= wide[1] < height and wide not in lake and wide not in river_of
                        and math.hypot(wide[0] - cx, wide[1] - cy) > meadow_r + 1):
                    path.append(wide)
                    heading.setdefault(wide, heading[here])
            prev = (ix, iy)
            want = math.atan2(ty - y, tx - x)
            dc = math.hypot(x - cx, y - cy)
            reach = meadow_r + 12 * s
            if dc < reach:  # bend around the meadow rather than through it
                away = math.atan2(y - cy, x - cx)
                off = _turn(want - away)
                if abs(off) > math.pi / 2:
                    tangent = away + math.copysign(math.pi / 2, off)
                    want += _turn(tangent - want) * min(1.0, (reach - dc) / (6 * s))
            wob = 0.8 * wob + rng.uniform(-0.35, 0.35)
            ang += _turn(want - ang) * 0.3 + wob * 0.3
            x += math.cos(ang)
            y += math.sin(ang)
            dc = math.hypot(x - cx, y - cy)
            if dc < keep_out:  # never into the meadow: slide along its edge
                away = math.atan2(y - cy, x - cx)
                x, y = cx + math.cos(away) * keep_out, cy + math.sin(away) * keep_out
        cells = set(path)
        for p in cells:
            tiles[p[1], p[0]] = "w"

        def outlet(p: tuple[int, int], own: bool) -> tuple[int, int] | None:
            """Where the water at p leaves the river: a stream into the lake or the river it joins, the outflow off the
            edge of the map; a stretch cut off from its own mouth (own False) into whatever water it touches."""
            edge = _at_edge(*p, width, height)
            if edge and not (own and to_lake):
                return _off_map_step(*p, width, height)
            if own and not to_lake:
                return None
            for dx, dy in NEIGHBORS:
                n = (p[0] + dx, p[1] + dy)
                if n in lake or n in flows:
                    return (dx, dy)
            return None

        mouths = {p: d for p in sorted(cells) if (d := outlet(p, True))}
        mine = _flow_from_mouths(cells, mouths, heading) if mouths else {}
        rest = cells - mine.keys()
        while rest:  # a stretch cut off from the river's own mouth flows into whatever water it touches
            more = {p: d for p in sorted(rest) if (d := outlet(p, False))}
            if not more:
                break  # a still backwater
            part = _flow_from_mouths(rest, more, heading)
            mine.update(part)
            rest -= part.keys()
        for p in cells:
            river_of[p] = number
        flows.update(mine)
        if to_lake:
            mouths_at_lake.extend(m for m in sorted(mouths)
                                  if any((m[0] + dx, m[1] + dy) in lake for dx, dy in NEIGHBORS))

    for number in (1, 2):
        a = rng.uniform(0, 2 * math.pi)
        r = rng.uniform(3, 9) * s
        sx = min(max(hx + math.cos(a) * r, 2), width - 3)
        sy = min(max(hy + math.sin(a) * r, 2), height - 3)
        walk(sx, sy, lx, ly, number, to_lake=True)
    if rng.random() < 0.5:  # the outflow leaves by the nearer side or the nearer top/bottom edge
        tx, ty = (0 if lx < cx else width - 1), ly + rng.uniform(-0.15, 0.15) * height
    else:
        tx, ty = lx + rng.uniform(-0.15, 0.15) * width, (0 if ly < cy else height - 1)
    walk(lx, ly, tx + (tx - lx) * 0.2, ty + (ty - ly) * 0.2, 3, to_lake=False)
    river = set(river_of)

    # The marsh where the first stream meets the lake; the beach on the far shore.
    if mouths_at_lake:
        mx0, my0 = mouths_at_lake[0]
    else:
        mx0, my0 = lx - (lx - cx) * 0.5, ly - (ly - cy) * 0.5
    marsh_ang = math.atan2(my0 - ly, mx0 - lx)
    mcx, mcy = lx + math.cos(marsh_ang) * (lake_r + 7 * s), ly + math.sin(marsh_ang) * (lake_r + 7 * s)
    marsh_r = rng.uniform(9.5, 12.5) * s
    beach_ang = marsh_ang + math.pi + rng.uniform(-0.5, 0.5)
    beach_w = rng.uniform(3.0, 5.0) * s
    river_m = np.zeros((height, width), dtype=bool)
    for x, y in river:
        river_m[y, x] = True
    off = (np.arctan2(yy - ly, xx - lx) - beach_ang + math.pi) % (2 * math.pi) - math.pi
    beach_m = (lake_d < lake_r + beach_w) & (np.abs(off) < 1.35) & (center_d > meadow_r + 1)
    wet_d = np.hypot(xx - mcx, yy - mcy) + (moist_n - 0.5) * 10 * s
    room = ~beach_m & (center_d > meadow_r + 1)
    dry = room & ~lake_m & ~river_m & (detail <= POOL)
    while np.count_nonzero(dry & (wet_d < marsh_r)) < 160 * s * s and marsh_r <= 18 * s:
        marsh_r += 1.5 * s  # a marsh worth the name: grow it if the lake and the rivers took most of it
    marsh_m = room & (wet_d < marsh_r)
    biome[beach_m] = "b"
    tiles[beach_m & ~lake_m & ~river_m] = "s"
    biome[marsh_m] = "k"
    ground = marsh_m & ~lake_m & ~river_m
    tiles[ground] = np.where(detail[ground] > POOL, "w", np.where(detail[ground] < 0.3, "d", "g"))

    # Shores: sandy edges round the rest of the lake, now and then along the rivers.
    by_lake, by_river = near(lake_m), near(river_m)
    shore = (tiles != "w") & (tiles != "W") & (biome != "b") & (biome != "k") & (by_lake | by_river)
    for x, y in _cells(shore):
        if rng.random() < (0.6 if by_lake[y, x] else 0.1):
            tiles[y, x] = "s"

    water = (tiles == "w") | (tiles == "W")
    wet = near(water)
    biome_rows = biome.tolist()
    tiles = tiles.tolist()
    world = World(width, height, tiles, Catalog.load(), seed)
    world.land = {"biomes": ["".join(r) for r in biome_rows], "flow": _rows(width, height, flows)}  # nature keeps it

    def near_center(x: int, y: int, r: float) -> bool:
        return math.hypot(x - cx, y - cy) <= r

    def free(x: int, y: int) -> bool:
        return world.in_bounds(x, y) and (x, y) not in world.grid and tiles[y][x] not in "wW" and not near_center(x, y, 4.5)

    for x, y in _cells(~water & (center_d > 4.5)):
        t, b, r = tiles[y][x], biome_rows[y][x], rng.random()
        if b == "o":
            if r < 0.28:
                world.add_object("tree", x, y, wood=6)
            elif r < 0.33:
                world.add_object("bush", x, y, berries=6)
        elif b == "p":
            if r < 0.30:
                world.add_object("pine", x, y, wood=6)
            elif r < 0.315:
                world.add_object("bush", x, y, berries=6)
            elif r < 0.325:
                world.add_object("rock", x, y)
        elif b == "h":
            if r < 0.02:
                world.add_object("copper_vein", x, y, ore=8)
            elif r < 0.034:
                world.add_object("iron_vein", x, y, ore=8)
            elif r < 0.23:
                world.add_object("rock", x, y)
        elif b == "k":
            if r < 0.04:
                world.add_object("clay", x, y, clay=6)
            elif r < 0.05:
                world.add_object("bush", x, y, berries=6)
        elif b == "b":
            if r < 0.025:
                world.add_object("clay", x, y, clay=6)
        elif t == "s" and wet[y, x]:
            if r < 0.08:
                world.add_object("clay", x, y, clay=6)
        elif t == "g":
            if r < 0.02:
                world.add_object("tree", x, y, wood=6)
            elif r < 0.05:
                world.add_object("bush", x, y, berries=6)
        elif t == "d":
            if r < 0.02:
                world.add_object("rock", x, y)
            elif r < 0.035:
                world.add_object("bush", x, y, berries=6)

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

    # Two ancient terminals with tablets, away from the meadow but within a long walk of it.
    placed = 0
    tries = 0
    far = max(24.0, 0.32 * max(width, height))
    while placed < 2 and tries < 5000:
        tries += 1
        x, y = rng.randrange(2, width - 2), rng.randrange(2, height - 2)
        if not 15 <= math.hypot(x - cx, y - cy) <= far or not free(x, y) or tiles[y][x] in "wW":
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

    place_wishing_stone(world)
    run_populate(world, rng, fresh=True, skip=() if deep else (DEEP_POPULATE,))  # the packs' own things
    world.changed_objects.clear()
    return world
