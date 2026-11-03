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


def _components(open_: np.ndarray) -> list[list[tuple[int, int]]]:
    """4-way connected groups of open tiles as (x, y) lists, largest first."""
    h, w = open_.shape
    seen = np.zeros_like(open_)
    out = []
    for sy, sx in zip(*np.nonzero(open_)):
        if seen[sy, sx]:
            continue
        seen[sy, sx] = True
        group, q = [], deque([(int(sx), int(sy))])
        while q:
            x, y = q.popleft()
            group.append((x, y))
            for dx, dy in _ORTHO:
                nx, ny = x + dx, y + dy
                if 0 <= nx < w and 0 <= ny < h and open_[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    q.append((nx, ny))
        out.append(group)
    out.sort(key=len, reverse=True)
    return out


def _middle(group: list[tuple[int, int]]) -> tuple[int, int]:
    """The tile of a group nearest its centroid."""
    a = np.array(group)
    c = a.mean(axis=0)
    return tuple(int(v) for v in a[((a - c) ** 2).sum(axis=1).argmin()])


def _join(rng: random.Random, open_: np.ndarray) -> None:
    """Join every pocket to the largest by an L-shaped 1-wide tunnel between their nearest tiles."""
    groups = _components(open_)
    if len(groups) < 2:
        return
    main = np.array(groups[0])
    for g in groups[1:]:
        a = np.array(g)
        d = ((a[:, None, :] - main[None, :, :]) ** 2).sum(axis=2)
        i, j = np.unravel_index(d.argmin(), d.shape)
        (x0, y0), (x1, y1) = a[i], main[j]
        if rng.random() < 0.5:
            corner = (int(x1), int(y0))
        else:
            corner = (int(x0), int(y1))
        for (ax, ay), (bx, by) in (((int(x0), int(y0)), corner), (corner, (int(x1), int(y1)))):
            open_[min(ay, by):max(ay, by) + 1, min(ax, bx):max(ax, bx) + 1] = True


def carve_deep(rng: random.Random, width: int, height: int) -> DeepMap:
    rock = np.array([[rng.random() < ROCK_CHANCE for _ in range(width)] for _ in range(height)])
    _border(rock)
    for _ in range(PASSES):
        rock = _smooth(rock)
        _border(rock)
    open_ = ~rock
    caverns = []
    for g in _components(open_):
        if len(g) < MIN_POCKET:
            for x, y in g:
                open_[y, x] = False
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
    rows = ["".join("u" if water[yy, xx] else "c" if open_[yy, xx] else "R" for xx in range(width))
            for yy in range(height)]
    return DeepMap(rows, caverns, (px, py))


# ------------------------------------------------------------------ digging into the rock
def _interior(world: World, x: int, y: int) -> tuple[int, int, int, int] | None:
    reg = world.region_at(x, y)
    if reg is None:
        return None
    return BORDER, reg.y0 + BORDER, world.width - BORDER, reg.y1 - BORDER  # half-open


def carve_chamber(world: World, x: int, y: int, r: int = 2) -> list[tuple[int, int]]:
    """Open the rock within r (a rounded disc) of (x, y), keeping BORDER tiles of rock at the region's edges.
    Returns every open tile of the chamber."""
    box = _interior(world, x, y)
    if box is None:
        return []
    x0, y0, x1, y1 = box
    out = []
    for yy in range(max(y - r, y0), min(y + r + 1, y1)):
        for xx in range(max(x - r, x0), min(x + r + 1, x1)):
            if (xx - x) ** 2 + (yy - y) ** 2 <= r * r + r:
                if world.tile(xx, yy) == "R":
                    world.set_tile(xx, yy, "c")
                if world.tile(xx, yy) in ("c", "u"):
                    out.append((xx, yy))
    return out


def carve_passage(world: World, start: tuple[int, int],
                  avoid: set[tuple[int, int]] = frozenset()) -> list[tuple[int, int]]:
    """Dig the shortest orthogonal path through the region's interior from `start` to the main cave system: the
    largest connected group of cave floor and water outside `avoid`. Its rock tiles become cave floor; returns them.
    Nothing changes when start is already in the main system or there is none to reach."""
    box = _interior(world, *start)
    if box is None:
        return []
    x0, y0, x1, y1 = box
    reg = world.region_at(*start)
    open_ = np.array([[world.tile(x, y) in ("c", "u") and (x, y) not in avoid for x in range(world.width)]
                      for y in range(reg.y0, reg.y1)])
    groups = _components(open_)
    if not groups:
        return []
    main = {(x, y + reg.y0) for x, y in groups[0]}
    if start in main:
        return []
    prev = {start: None}
    q = deque([start])
    goal = None
    while q:
        cur = q.popleft()
        if cur in main:
            goal = cur
            break
        for dx, dy in _ORTHO:
            n = (cur[0] + dx, cur[1] + dy)
            if x0 <= n[0] < x1 and y0 <= n[1] < y1 and n not in prev:
                prev[n] = cur
                q.append(n)
    if goal is None:
        return []
    changed = []
    cur = goal
    while cur is not None:
        if world.tile(*cur) == "R":
            world.set_tile(*cur, "c")
            changed.append(cur)
        cur = prev[cur]
    return changed[::-1]
