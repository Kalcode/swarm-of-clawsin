"""The land generator: one deterministic LAND x LAND land that fits its neighbours' edges and carries a theme.

The frontier lays strips of lands at the map's east and west edges. A land is made from its coordinates alone: the
frontier seed and the land's place roll its own random.Random (nothing here touches a world's dice), its known
neighbours' edges are blended in over BLEND tiles and their rivers carried on, and a theme (stony hills, a lake...)
decides the rest. The themes are data (swarmworld/data/lands.json). The base generator (terrain.generate_world) is
left alone; this module borrows its noise and flow helpers."""

from __future__ import annotations

import json
import math
import random
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from . import terrain
from .catalog import DATA
from .model import World
from .perception import DIRS

LAND = 32  # a land's side, and the strip's width
BLEND = 4  # the seam blends over this many tiles from a known edge
BLEND_CHANCE = (0.8, 0.6, 0.4, 0.2)  # the chance a tile at depth 0..3 takes its neighbour's tile and biome
NEIGHBORS = terrain.NEIGHBORS
WET = "wW"

# Where each kind may stand (tile codes); a kind not listed stands on grass, dry earth or forest floor.
ON_TILES = {"rock": "rdg", "flint_outcrop": "r", "iron_vein": "r", "copper_vein": "r", "driftwood": "s",
            "clay": "sgd", "mushroom_patch": "f", "pine": "fg", "flower_patch": "gd", "herb_patch": "gd",
            "rabbit": "gd", "sheep": "gd", "cow": "gd", "reed_bed": "gds"}
DEFAULT_ON = "gdf"


@dataclass(frozen=True)
class Edge:
    """A neighbour's tile, biome and flow codes along the shared side: top to bottom for a column, left to right for
    a row."""
    tiles: str
    biomes: str
    flow: str


@dataclass
class Land:
    """One land. Coordinates are local to it. `mouth` is set only for stony hills."""
    theme: str
    tiles: list[str]
    biomes: list[str]
    flow: list[str]
    objects: list[tuple[str, int, int, dict]]
    heart: tuple[int, int]
    mouth: tuple[int, int] | None


@lru_cache(maxsize=1)
def _data() -> dict:
    return json.loads((DATA / "lands.json").read_text())


THEMES: dict[str, dict] = _data()["themes"]


# ------------------------------------------------------------------ reading a neighbour
def column_edge(world: World, x: int, y0: int, y1: int) -> Edge:
    """The tiles, biomes and flow of column x over rows y0..y1 (biome "m" and flow "." where there are none)."""
    nature = world.ext.get("nature") or {}
    biomes, flow = nature.get("biomes") or [], nature.get("flow") or []

    def code(rows: list[str], y: int, default: str) -> str:
        return rows[y][x] if y < len(rows) and x < len(rows[y]) else default

    ys = range(y0, y1)
    return Edge("".join(world.tiles[y][x] for y in ys), "".join(code(biomes, y, "m") for y in ys),
                "".join(code(flow, y, terrain.STILL) for y in ys))


def row_edge(land: Land, row: int) -> Edge:
    return Edge(land.tiles[row], land.biomes[row], land.flow[row])


def need(world: World) -> dict[str, float]:
    """How short the surface is of each resource, 0 (at or over the baseline) to 1 (none): the census of the sources'
    surface objects against the baseline per 128 x 128."""
    data = _data()
    rows = terrain.surface_rows(world)
    area = world.width * len(rows)
    counts: Counter = Counter()
    for o in world.objects.values():
        if o.y in rows:
            counts[o.kind] += 1 if o.kind != "bush" or o.data.get("berries", 0) > 0 else 0
    out = {}
    for res, kinds in data["sources"].items():
        have = sum(counts[k] for k in kinds)
        out[res] = max(0.0, 1 - have / (data["baseline"][res] * area / 16384))
    return out


# ------------------------------------------------------------------ choosing a theme
def _shares(edges: dict[str, Edge]) -> dict[str, float]:
    total = Counter()
    n = 0
    for e in edges.values():
        for t, b in zip(e.tiles, e.biomes):
            n += 1
            total["water"] += t in WET
            total["rock"] += t == "r" or b == "h"
            total["forest"] += t == "f"
            total["meadow"] += b == "m"
    return {k: v / n for k, v in total.items()} if n else {}


def choose_theme(rng: random.Random, edges: dict[str, Edge], need: dict[str, float]) -> str:
    shares = _shares(edges)
    weights = []
    for t in THEMES.values():
        fit = 1 + sum((m - 1) * shares.get(f, 0.0) for f, m in t["fit"].items())
        w = t["base"] * max(0.05, fit)
        if t["supplies"]:
            w *= 1 + 2 * need.get(t["supplies"], 0.0)
        weights.append(w)
    return rng.choices(list(THEMES), weights)[0]


# ------------------------------------------------------------------ the land
def generate_land(seed: int, lx: int, ly: int, size: tuple[int, int], edges: dict[str, Edge],
                  need: dict[str, float], theme: str | None = None) -> Land:
    """The land at (lx, ly) of the frontier seeded `seed`, of size (width, height), fitted to the known neighbours in
    `edges` ("west", "east", "north", "south"). Deterministic. A theme is chosen by fit and need unless given."""
    rng = random.Random(f"{seed}:{lx}:{ly}")
    w, h = size
    name = theme or choose_theme(rng, edges, need)
    th = THEMES[name]
    tiles = [list(r) for r in _ground(rng, th, w, h)]
    biomes = [[th["biome"]] * w for _ in range(h)]
    heart: tuple[int, int] | None = None
    if name == "lake":
        heart = _lake(rng, tiles, biomes, w, h)
    elif name == "marsh":
        heart = _marsh(rng, tiles, w, h)
    _blend(rng, tiles, biomes, edges, w, h)
    flow = _rivers(rng, tiles, edges, w, h, heart if name in ("lake", "marsh") else None)
    mouth = None
    if name == "stony_hills":
        spots = [(x, y) for y in range(4, h - 4) for x in range(4, w - 4) if tiles[y][x] == "r"]
        mouth = rng.choice(spots) if spots else None
        heart = _nearest(tiles, _centroid(tiles, "r", w, h), "r")
    elif heart is None:
        heart = _nearest(tiles, (w // 2, h // 2))
    objects: list[tuple[str, int, int, dict]] = []
    taken = {mouth} if mouth else set()
    if name == "ruins":
        _ruins(rng, tiles, heart, objects, taken)
    _scatter(rng, th, tiles, biomes, objects, taken, w, h)
    return Land(name, ["".join(r) for r in tiles], ["".join(r) for r in biomes], flow, objects, heart, mouth)


def _ground(rng: random.Random, th: dict, w: int, h: int) -> list[str]:
    """The theme's ground over smooth noise: each tile code takes its weight's share of the tiles, by noise rank."""
    noise = terrain._value_noise(rng, w, h, 4).ravel()
    order = np.argsort(noise, kind="stable")
    codes = np.empty(w * h, dtype="<U1")
    weights = th["ground"]
    total = sum(weights.values())
    start = 0
    acc = 0.0
    for i, (code, wt) in enumerate(weights.items()):
        acc += wt
        stop = w * h if i == len(weights) - 1 else round(acc / total * w * h)
        codes[order[start:stop]] = code
        start = stop
    return ["".join(r) for r in codes.reshape(h, w)]


def _lake(rng: random.Random, tiles: list[list[str]], biomes: list[list[str]], w: int, h: int) -> tuple[int, int]:
    """A blob of deep water round a nudged middle (at least 8 from every side), ringed with shallows and sand."""
    r = rng.uniform(4.0, 6.0)
    ring_w, ring_s = 2, rng.choice((1, 2))
    margin = max(8, math.ceil(r) + ring_w + ring_s)

    def middle(n: int) -> int:
        lo, hi = margin, n - 1 - margin
        return round(n / 2 + rng.uniform(-3, 3)) if hi < lo else min(max(round(n / 2 + rng.uniform(-3, 3)), lo), hi)

    cx, cy = middle(w), middle(h)
    nudge = terrain._value_noise(rng, w, h, 4)
    for y in range(h):
        for x in range(w):
            d = math.hypot(x - cx, y - cy) + (nudge[y, x] - 0.5) * 2
            if d < r:
                tiles[y][x] = "W"
            elif d < r + ring_w:
                tiles[y][x] = "w"
            elif d < r + ring_w + ring_s:
                tiles[y][x], biomes[y][x] = "s", "b"
    return cx, cy


def _marsh(rng: random.Random, tiles: list[list[str]], w: int, h: int) -> tuple[int, int]:
    """Still pools where detail noise runs high, and a pond in the middle for the rivers to end in."""
    detail = terrain._value_noise(rng, w, h, 3)
    cx = min(max(round(w / 2 + rng.uniform(-3, 3)), 8), max(8, w - 9))
    cy = min(max(round(h / 2 + rng.uniform(-3, 3)), min(8, h // 2)), max(min(8, h // 2), h - 9))
    r = rng.uniform(2.2, 3.0)
    for y in range(h):
        for x in range(w):
            if detail[y, x] > terrain.POOL or math.hypot(x - cx, y - cy) < r:
                tiles[y][x] = "w"
    return cx, cy


def _blend(rng: random.Random, tiles: list[list[str]], biomes: list[list[str]], edges: dict[str, Edge],
           w: int, h: int) -> None:
    """At depth k from a known edge a tile takes its neighbour's tile and biome (not water) with chance
    BLEND_CHANCE[k]."""
    for side, e in edges.items():
        along = h if side in ("west", "east") else w
        for k in range(BLEND):
            for i in range(along):
                roll = rng.random()
                j = min(i, len(e.tiles) - 1)
                if roll >= BLEND_CHANCE[k] or e.tiles[j] in WET:
                    continue
                x, y = {"west": (k, i), "east": (w - 1 - k, i), "north": (i, k), "south": (i, h - 1 - k)}[side]
                tiles[y][x], biomes[y][x] = e.tiles[j], e.biomes[j]


# ------------------------------------------------------------------ rivers
_ENTRY = {"west": (1, 0), "east": (-1, 0), "north": (0, 1)}  # the step across the seam that carries a river in


def _entries(side: str, e: Edge) -> list[tuple[int, int]]:
    """The runs (start, end) of shallow water along a neighbour's edge, at least one tile of which flows across."""
    runs, i = [], 0
    while i < len(e.tiles):
        if e.tiles[i] != "w":
            i += 1
            continue
        j = i
        while j + 1 < len(e.tiles) and e.tiles[j + 1] == "w":
            j += 1
        if any(e.flow[k] != terrain.STILL and terrain.FLOW_STEP[DIRS[int(e.flow[k])]] == _ENTRY[side]
               for k in range(i, j + 1)):
            runs.append((i, j))
        i = j + 1
    return runs


def _rivers(rng: random.Random, tiles: list[list[str]], edges: dict[str, Edge], w: int, h: int,
            water_at: tuple[int, int] | None) -> list[str]:
    """Carve the rivers that cross a known seam into this land; return the land's flow rows."""
    still = {(x, y) for y in range(h) for x in range(w) if tiles[y][x] in WET}
    flows: dict[tuple[int, int], str] = {}
    claimed: set[tuple[int, int]] = set()  # cells of the rivers carved so far
    for side in ("west", "east", "north"):
        if side not in edges:
            continue
        for lo, hi in _entries(side, edges[side]):
            width = rng.choice((1, 2))
            mid = (lo + hi) // 2 + rng.randint(-1, 1) - (width - 1) // 2
            along = h if side != "north" else w
            start = min(max(mid, 0), along - width)
            _carve(rng, tiles, edges, w, h, side, start, width, water_at, still, claimed, flows)
    grid = [[terrain.STILL] * w for _ in range(h)]
    for (x, y), ch in flows.items():
        grid[y][x] = ch
    return ["".join(r) for r in grid]


def _carve(rng: random.Random, tiles: list[list[str]], edges: dict[str, Edge], w: int, h: int, side: str,
           start: int, width: int, water_at: tuple[int, int] | None, still: set, claimed: set,
           flows: dict) -> None:
    """One river from the seam on `side`, `width` tiles wide at rows (or columns) start.., walking away from it."""
    far = {"west": "east", "east": "west", "north": "south"}[side]
    exits = [s for s in (far, "south") if s not in edges]
    ang = {"west": 0.0, "east": math.pi, "north": math.pi / 2}[side]
    if side == "north":
        x, y = start + (width - 1) / 2, 0.0
        entry = [(start + k, 0) for k in range(width)]
    else:
        x, y = (0.0 if side == "west" else w - 1.0), start + (width - 1) / 2
        entry = [(0 if side == "west" else w - 1, start + k) for k in range(width)]
    if water_at:
        tx, ty = water_at
    elif not exits:
        tx, ty = w / 2, h * 0.75
    elif exits[0] == "south":
        tx, ty = x + rng.uniform(-6, 6), h + 6
    else:
        tx, ty = (w + 6 if exits[0] == "east" else -6), min(max(y + rng.uniform(-6, 10), 3), h + 8)
    path: list[tuple[int, int]] = []
    heading: dict[tuple[int, int], tuple[float, float]] = {}

    def add(p: tuple[int, int]) -> None:
        if p not in still and p not in claimed and p not in heading and 0 <= p[0] < w and 0 <= p[1] < h:
            path.append(p)
            heading[p] = (math.cos(ang), math.sin(ang))

    def on_exit(p: tuple[int, int]) -> bool:
        return (("east" in exits and p[0] == w - 1) or ("west" in exits and p[0] == 0)
                or ("south" in exits and p[1] == h - 1))

    def touches(p: tuple[int, int]) -> bool:
        return any((p[0] + dx, p[1] + dy) in still or (p[0] + dx, p[1] + dy) in claimed for dx, dy in NEIGHBORS)

    for p in entry:
        add(p)
    done = False
    wob, last = 0.0, entry[0]
    for _ in range(4 * (w + h)):
        want = math.atan2(ty - y, tx - x)
        wob = 0.8 * wob + rng.uniform(-0.35, 0.35)
        ang += terrain._turn(want - ang) * 0.3 + wob * 0.3
        x = min(max(x + math.cos(ang), 0.0), w - 1.0)
        y = min(max(y + math.sin(ang), 0.0), h - 1.0)
        here = (round(x), round(y))
        if here == last:
            continue
        horizontal = abs(math.cos(ang)) > abs(math.sin(ang))
        cells = [here]
        if width == 2:
            cells.append((here[0], here[1] + 1) if horizontal else (here[0] + 1, here[1]))
        for p in cells:
            add(p)
        last = here
        if any(on_exit(p) or touches(p) for p in cells):
            done = True
            break
    cells = set(path)
    pond: set[tuple[int, int]] = set()
    if not done:  # nowhere to go: the river ends in a small pond
        pond = {(last[0] + dx, last[1] + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                if 0 <= last[0] + dx < w and 0 <= last[1] + dy < h} - set(entry)
        cells -= pond
    for px, py in pond | cells:
        tiles[py][px] = "w"
    ponds = still | pond
    mouths: dict[tuple[int, int], tuple[int, int]] = {}
    for p in sorted(cells):
        if "east" in exits and p[0] == w - 1:
            mouths[p] = (1, 0)
        elif "west" in exits and p[0] == 0:
            mouths[p] = (-1, 0)
        elif "south" in exits and p[1] == h - 1:
            mouths[p] = (0, 1)
        else:
            into = next(((dx, dy) for dx, dy in NEIGHBORS
                         if (p[0] + dx, p[1] + dy) in ponds or (p[0] + dx, p[1] + dy) in claimed), None)
            if into:
                mouths[p] = into
    if cells and mouths:
        flows.update(terrain._flow_from_mouths(cells, mouths, heading))
    claimed |= cells
    still |= pond


# ------------------------------------------------------------------ objects
def _nearest(tiles: list[list[str]], at: tuple[float, float], code: str | None = None) -> tuple[int, int]:
    """The dry tile (of tile code `code`, if given) nearest `at`."""
    best = min(((math.hypot(x - at[0], y - at[1]), y, x) for y, row in enumerate(tiles) for x, t in enumerate(row)
                if (t == code if code else t not in WET)), default=None)
    return (best[2], best[1]) if best else (round(at[0]), round(at[1]))


def _centroid(tiles: list[list[str]], code: str, w: int, h: int) -> tuple[float, float]:
    pts = [(x, y) for y in range(h) for x in range(w) if tiles[y][x] == code]
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)) if pts else (w / 2, h / 2)


def _ruins(rng: random.Random, tiles: list[list[str]], heart: tuple[int, int], objects: list, taken: set) -> None:
    """A tablet at the heart in a ring of rocks, and now and then a terminal beside it."""
    data = _data()
    hx, hy = heart
    objects.append(("tablet", hx, hy, {"text": rng.choice(data["ruins_texts"])}))
    taken.add(heart)
    h, w = len(tiles), len(tiles[0])

    def free(x: int, y: int) -> bool:
        return 0 <= x < w and 0 <= y < h and tiles[y][x] not in WET and (x, y) not in taken

    spots = [(hx + dx, hy + dy) for dy in range(-3, 4) for dx in range(-3, 4)
             if 0 < math.hypot(dx, dy) <= 3 and free(hx + dx, hy + dy)]
    for x, y in rng.sample(spots, min(rng.randint(6, 10), len(spots))):
        objects.append(("rock", x, y, {}))
        taken.add((x, y))
    beside = [(hx + dx, hy + dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)) if free(hx + dx, hy + dy)]
    if rng.random() < data["terminal_chance"] and beside:
        x, y = rng.choice(beside)
        objects.append(("terminal", x, y, {"code": "", "screen": list(terrain.TERMINAL_READY), "memory": {},
                                           "ruin": True}))
        taken.add((x, y))


def _scatter(rng: random.Random, th: dict, tiles: list[list[str]], biomes: list[list[str]], objects: list,
             taken: set, w: int, h: int) -> None:
    """The theme's objects by density on free dry tiles, then topped up to its minimum counts."""
    kinds = list(th["objects"].items())
    for y in range(h):
        for x in range(w):
            if tiles[y][x] in WET or (x, y) in taken:
                continue
            roll, acc = rng.random(), 0.0
            for kind, (density, data) in kinds:
                acc += density
                if roll < acc:
                    if tiles[y][x] in ON_TILES.get(kind, DEFAULT_ON):
                        objects.append((kind, x, y, dict(data)))
                        taken.add((x, y))
                    break
    have = Counter(o[0] for o in objects)
    for kind, n in th["min"].items():
        data = th["objects"].get(kind, [0, {}])[1]
        dry = [(x, y) for y in range(h) for x in range(w) if tiles[y][x] not in WET and (x, y) not in taken]
        ok = ON_TILES.get(kind, DEFAULT_ON)
        for pool in ([p for p in dry if tiles[p[1]][p[0]] in ok and biomes[p[1]][p[0]] == th["biome"]],
                     [p for p in dry if tiles[p[1]][p[0]] in ok], dry):
            missing = n - have[kind]
            if missing <= 0:
                break
            pool = [p for p in pool if p not in taken]
            for x, y in rng.sample(pool, min(missing, len(pool))):
                objects.append((kind, x, y, dict(data)))
                taken.add((x, y))
                have[kind] += 1
