"""The deep's map: caves grown from noise, joined by tunnels, with a stream and a pool; and the chambers and passages
that later digging carves into its rock.

Tiles: "R" rock, "c" cave floor, "u" cave water. Connectivity here is 4-way (orthogonal), as walking is.
carve_deep draws only from the rng it is given (never world.rng), so the same rng gives the same deep."""

from __future__ import annotations

import random
from collections import deque
from dataclasses import dataclass

import numpy as np

from .model import World

BORDER = 2  # rows and columns of rock along every edge of the deep
ROCK_CHANCE = 0.48
PASSES = 5
MIN_POCKET = 16
POCKET_ROCK = 0.56  # the rock chance for a strip's pockets: sparse, so few groups survive
STREAM_STEP = 0.7  # chance a stream step goes toward its target
_ORTHO = ((1, 0), (-1, 0), (0, 1), (0, -1))


@dataclass
class DeepMap:
    rows: list[str]
    caverns: list[tuple[int, int, int]]  # (x, y, size) of each cave's middle, largest first
    pool: tuple[int, int]  # the pool's middle


def _border(rock: np.ndarray) -> None:
    rock[:BORDER, :] = True
    rock[-BORDER:, :] = True
    rock[:, :BORDER] = True
    rock[:, -BORDER:] = True


def _smooth(rock: np.ndarray) -> np.ndarray:
    h, w = rock.shape
    p = np.pad(rock.astype(np.int8), 1, constant_values=1)
    n = sum(p[1 + dy:1 + dy + h, 1 + dx:1 + dx + w] for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dx or dy)
    out = rock.copy()
    out[n >= 5] = True
    out[n <= 3] = False
    return out


def tile_codes(world: World, y0: int, y1: int) -> np.ndarray:
    """The tiles of rows y0 <= y < y1 as an array of character codes (compare with ord("c"))."""
    return np.frombuffer("".join(map("".join, world.tiles[y0:y1])).encode(), dtype=np.uint8).reshape(y1 - y0, -1)


def _components(open_: np.ndarray) -> list[np.ndarray]:
    """4-way connected groups of open tiles as (n, 2) arrays of (x, y) in breadth-first order from each group's first
    tile in reading order, largest first (equal sizes keep reading order)."""
    h, w = open_.shape
    W = w + 2  # walked on a copy framed by a closed border, so no step needs a bounds check
    framed = np.zeros((h + 2, W), dtype=bool)
    framed[1:-1, 1:-1] = open_
    free = framed.ravel().tolist()  # flat lists: far quicker to walk than numpy scalars
    out = []
    for start in np.flatnonzero(framed.ravel()).tolist():
        if not free[start]:
            continue
        free[start] = False
        group, i = [start], 0
        while i < len(group):
            p = group[i]
            i += 1
            for n in (p + 1, p - 1, p + W, p - W):  # the order of _ORTHO: right, left, down, up
                if free[n]:
                    free[n] = False
                    group.append(n)
        g = np.array(group)
        out.append(np.stack((g % W - 1, g // W - 1), axis=1))
    out.sort(key=len, reverse=True)
    return out


def _edge(group: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    """The group's tiles with a side not in the group, in the group's order. Nearest to any outside tile is always one."""
    m = np.zeros((shape[0] + 2, shape[1] + 2), dtype=bool)
    xs, ys = group[:, 0] + 1, group[:, 1] + 1
    m[ys, xs] = True
    inner = m[ys, xs + 1] & m[ys, xs - 1] & m[ys + 1, xs] & m[ys - 1, xs]
    return group[~inner]


def _middle(a: np.ndarray) -> tuple[int, int]:
    """The tile of a group nearest its centroid."""
    c = a.mean(axis=0)
    return tuple(int(v) for v in a[((a - c) ** 2).sum(axis=1).argmin()])


def _join(rng: random.Random, open_: np.ndarray) -> None:
    """Join every pocket to the largest by an L-shaped 1-wide tunnel between their nearest tiles."""
    groups = _components(open_)
    if len(groups) < 2:
        return
    main = _edge(groups[0], open_.shape)
    for a in groups[1:]:
        a = _edge(a, open_.shape)
        d = ((a[:, 0, None] - main[None, :, 0]) ** 2 + (a[:, 1, None] - main[None, :, 1]) ** 2).astype(np.int32)
        i, j = np.unravel_index(d.argmin(), d.shape)
        (x0, y0), (x1, y1) = a[i], main[j]
        if rng.random() < 0.5:
            corner = (int(x1), int(y0))
        else:
            corner = (int(x0), int(y1))
        for (ax, ay), (bx, by) in (((int(x0), int(y0)), corner), (corner, (int(x1), int(y1)))):
            open_[min(ay, by):max(ay, by) + 1, min(ax, bx):max(ax, bx) + 1] = True


FLOOR_SHARE = (0.30, 0.55)  # the share of the deep that is cave floor or water
FREE_TRIES = 5  # re-rolls at the standard rock chance before it is nudged
MAX_TRIES = 40


def carve_deep(rng: random.Random, width: int, height: int) -> DeepMap:
    """A deep whose floor share lies within FLOOR_SHARE: a map that falls outside is re-rolled from the same rng (so
    the result is still fixed by the seed), and after FREE_TRIES the rock chance is nudged toward the bound missed."""
    chance = ROCK_CHANCE
    for attempt in range(MAX_TRIES):
        deep = _carve(rng, width, height, chance)
        share = sum(r.count("c") + r.count("u") for r in deep.rows) / (width * height)
        if FLOOR_SHARE[0] <= share <= FLOOR_SHARE[1]:
            break
        if attempt >= FREE_TRIES - 1:
            chance += 0.01 if share > FLOOR_SHARE[1] else -0.01
    return deep


def _carve(rng: random.Random, width: int, height: int, chance: float) -> DeepMap:
    rock = np.array([[rng.random() < chance for _ in range(width)] for _ in range(height)])
    _border(rock)
    for _ in range(PASSES):
        rock = _smooth(rock)
        _border(rock)
    open_ = ~rock
    caverns = []  # sizes as grown, before the tunnels and the stream and pool add to them
    for g in _components(open_):
        if len(g) < MIN_POCKET:
            open_[g[:, 1], g[:, 0]] = False
        else:
            caverns.append((*_middle(g), len(g)))
    if not caverns:  # a hopeless seed or a tiny deep: open the middle
        cx, cy = width // 2, height // 2
        open_[max(BORDER, cy - 3):cy + 4, max(BORDER, cx - 3):cx + 4] = True
        open_[:BORDER, :] = open_[-BORDER:, :] = open_[:, :BORDER] = open_[:, -BORDER:] = False
        caverns = [(cx, cy, int(open_.sum()))]
    _join(rng, open_)
    water = np.zeros_like(open_)
    mx, my, _ = caverns[0]
    far = max(caverns, key=lambda c: (c[0] - mx) ** 2 + (c[1] - my) ** 2)
    tx, ty = far[0], far[1]
    if len(caverns) == 1:  # a lone cave: the stream runs to the floor tile farthest from its middle
        ys, xs = np.nonzero(open_)
        k = ((xs - mx) ** 2 + (ys - my) ** 2).argmax()
        tx, ty = int(xs[k]), int(ys[k])
    x, y = mx, my
    lo_x, hi_x, lo_y, hi_y = BORDER, width - BORDER - 1, BORDER, height - BORDER - 1
    for _ in range(4 * (width + height)):
        water[y, x] = True
        if (x, y) == (tx, ty):
            break
        dx, dy = tx - x, ty - y
        along_x = abs(dx) >= abs(dy)
        if rng.random() < STREAM_STEP:
            sx, sy = (int(np.sign(dx)), 0) if along_x else (0, int(np.sign(dy)))
        else:
            side = rng.choice((-1, 1))
            sx, sy = (0, side) if along_x else (side, 0)
        x, y = min(max(x + sx, lo_x), hi_x), min(max(y + sy, lo_y), hi_y)
    r = max(2, width // 32)
    px = min(max(mx, BORDER + r), width - BORDER - 1 - r)
    py = min(max(my, BORDER + r), height - BORDER - 1 - r)
    for yy in range(py - r, py + r + 1):
        for xx in range(px - r, px + r + 1):
            if (xx - px) ** 2 + (yy - py) ** 2 <= r * r:
                water[yy, xx] = True
    open_ |= water
    if (px, py) != (mx, my):
        _join(rng, open_)  # a clamped pool may sit apart from the caves
    grid = np.where(water, "u", np.where(open_, "c", "R"))
    rows = ["".join(r) for r in grid.tolist()]
    return DeepMap(rows, caverns, (px, py))


def carve_pockets(rng: random.Random, width: int, height: int, pockets: int) -> DeepMap:
    """A rock rectangle holding the `pockets` largest groups of at least MIN_POCKET floor tiles that the automaton
    (POCKET_ROCK, PASSES, a BORDER of rock) leaves; the rest are filled in. No tunnels, stream or pool. caverns: the
    kept pockets, largest first; pool: the largest's middle. With no group big enough, a 5x5 room at the middle."""
    rock = np.array([[rng.random() < POCKET_ROCK for _ in range(width)] for _ in range(height)])
    _border(rock)
    for _ in range(PASSES):
        rock = _smooth(rock)
        _border(rock)
    open_ = ~rock
    caverns = []
    for g in _components(open_):
        if len(g) < MIN_POCKET or len(caverns) >= pockets:
            open_[g[:, 1], g[:, 0]] = False
        else:
            caverns.append((*_middle(g), len(g)))
    if not caverns:
        cx, cy = width // 2, height // 2
        open_[cy - 2:cy + 3, cx - 2:cx + 3] = True
        caverns = [(cx, cy, 25)]
    grid = np.where(open_, "c", "R")
    return DeepMap(["".join(r) for r in grid.tolist()], caverns, caverns[0][:2])


# ------------------------------------------------------------------ digging into the rock
def _interior(world: World, x: int, y: int) -> tuple[int, int, int, int] | None:
    reg = world.region_at(x, y)
    if reg is None:
        return None
    return BORDER, reg.y0 + BORDER, world.width - BORDER, reg.y1 - BORDER  # half-open


def chamber_tiles(world: World, x: int, y: int, r: int = 2) -> list[tuple[int, int]]:
    """The tiles carve_chamber(world, x, y, r) would leave open, changing nothing: the rock, cave floor and cave water
    within r (a rounded disc) of (x, y), inside BORDER tiles of rock at the region's edges."""
    box = _interior(world, x, y)
    if box is None:
        return []
    x0, y0, x1, y1 = box
    return [(xx, yy) for yy in range(max(y - r, y0), min(y + r + 1, y1))
            for xx in range(max(x - r, x0), min(x + r + 1, x1))
            if (xx - x) ** 2 + (yy - y) ** 2 <= r * r + r and world.tile(xx, yy) in ("R", "c", "u")]


def carve_chamber(world: World, x: int, y: int, r: int = 2) -> list[tuple[int, int]]:
    """Open the rock within r (a rounded disc) of (x, y), keeping BORDER tiles of rock at the region's edges.
    Returns every open tile of the chamber."""
    out = chamber_tiles(world, x, y, r)
    for xx, yy in out:
        if world.tile(xx, yy) == "R":
            world.set_tile(xx, yy, "c")
    return out


def carve_passage(world: World, start: tuple[int, int], avoid: set[tuple[int, int]] = frozenset(),
                  goals: set[tuple[int, int]] | None = None) -> list[tuple[int, int]]:
    """Dig the shortest orthogonal path through the region's interior from `start` to the main cave system: the
    largest connected group of cave floor and water outside `avoid`. Its rock tiles become cave floor; returns them.
    With `goals`, the path ends at the nearest of those tiles instead (same search, same interior limits).
    Nothing changes when start is already in the main system or there is none to reach, or lies off the map."""
    if not 0 <= start[0] < world.width:  # the flat index below needs start's column on the map
        return []
    box = _interior(world, *start)
    if box is None:
        return []
    x0, y0, x1, y1 = box
    reg = world.region_at(*start)
    w = world.width
    codes = tile_codes(world, reg.y0, reg.y1)
    open_ = (codes == ord("c")) | (codes == ord("u"))
    for ax, ay in avoid:
        if reg.y0 <= ay < reg.y1 and 0 <= ax < w:
            open_[ay - reg.y0, ax] = False
    main = np.zeros(open_.shape, dtype=bool)
    if goals is not None:
        for gx, gy in goals:
            if reg.y0 <= gy < reg.y1 and 0 <= gx < w:
                main[gy - reg.y0, gx] = True
    else:
        groups = _components(open_)
        if not groups:
            return []
        main[groups[0][:, 1], groups[0][:, 0]] = True
    main = main.ravel().tolist()
    s0 = (start[1] - reg.y0) * w + start[0]  # tiles as flat indices into the region's rows
    if main[s0]:
        return []
    prev = {s0: None}
    q = deque([s0])
    goal = None
    while q:
        cur = q.popleft()
        if main[cur]:
            goal = cur
            break
        cx, cy = cur % w, cur // w + reg.y0
        for dx, dy in _ORTHO:
            nx, ny = cx + dx, cy + dy
            if x0 <= nx < x1 and y0 <= ny < y1:
                n = cur + dx + dy * w
                if n not in prev:
                    prev[n] = cur
                    q.append(n)
    if goal is None:
        return []
    changed = []
    cur = goal
    while cur is not None:
        x, y = cur % w, cur // w + reg.y0
        if world.tile(x, y) == "R":
            world.set_tile(x, y, "c")
            changed.append((x, y))
        cur = prev[cur]
    return changed[::-1]
