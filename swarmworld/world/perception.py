"""World -> text: a creature's first-person view of what it can sense right now."""

from __future__ import annotations

import math
from collections import defaultdict

from .model import OBJECT_NAMES, TILE_NAMES, Creature, World, WorldObject

DAY_SIGHT = 6
NIGHT_SIGHT = 2
FIRE_SIGHT = 5
FIRE_RADIUS = 3

DIRS = ["east", "southeast", "south", "southwest", "west", "northwest", "north", "northeast"]


def direction(dx: int, dy: int) -> str:
    if dx == 0 and dy == 0:
        return "here"
    ang = math.degrees(math.atan2(dy, dx)) % 360
    return DIRS[int((ang + 22.5) // 45) % 8]


def dist(ax: int, ay: int, bx: int, by: int) -> int:
    return max(abs(ax - bx), abs(ay - by))


def near_lit_fire(world: World, x: int, y: int, radius: int = FIRE_RADIUS) -> bool:
    for yy in range(y - radius, y + radius + 1):
        for xx in range(x - radius, x + radius + 1):
            o = world.object_at(xx, yy)
            if o and o.kind == "campfire" and o.data.get("lit"):
                return True
            if o and o.kind == "creation" and "light" in o.data.get("effects", ()):
                return True
    return False


def sight_range(world: World, creature: Creature) -> int:
    if world.clock()["phase"] != "night":
        return DAY_SIGHT
    return FIRE_SIGHT if near_lit_fire(world, creature.x, creature.y) else NIGHT_SIGHT


def visible_objects(world: World, creature: Creature, rng: int | None = None) -> list[tuple[WorldObject, int, str]]:
    r = sight_range(world, creature) if rng is None else rng
    out = []
    for y in range(creature.y - r, creature.y + r + 1):
        for x in range(creature.x - r, creature.x + r + 1):
            o = world.object_at(x, y)
            if o:
                dx, dy = o.x - creature.x, o.y - creature.y
                out.append((o, dist(0, 0, dx, dy), direction(dx, dy)))
    out.sort(key=lambda t: t[1])
    return out


def visible_creatures(world: World, creature: Creature, rng: int | None = None) -> list[tuple[Creature, int, str]]:
    r = sight_range(world, creature) if rng is None else rng
    out = []
    for c in world.creatures.values():
        if c.id == creature.id:
            continue
        d = dist(creature.x, creature.y, c.x, c.y)
        if d <= r:
            out.append((c, d, direction(c.x - creature.x, c.y - creature.y)))
    out.sort(key=lambda t: t[1])
    return out


def visible_piles(world: World, creature: Creature) -> list[tuple[int, int, int, str]]:
    r = sight_range(world, creature)
    out = []
    for (x, y), pile in world.ground.items():
        d = dist(creature.x, creature.y, x, y)
        if d <= r and pile:
            out.append((x, y, d, direction(x - creature.x, y - creature.y)))
    return sorted(out, key=lambda t: t[2])


def _steps(d: int) -> str:
    return "1 step" if d == 1 else f"{d} steps"


def _where(d: int, dirn: str) -> str:
    if d == 0:
        return "right here"
    if d == 1:
        return f"right beside you to the {dirn}"
    return f"{_steps(d)} {dirn}"


def article(word: str) -> str:
    return "an" if word[:1].lower() in "aeiou" else "a"


def plural(label: str) -> str:
    head, _, tail = label.partition(" (")
    if head.endswith(("sh", "ch", "s", "x")):
        head += "es"
    elif head.endswith("y") and not head.endswith(("ay", "ey", "oy")):
        head = head[:-1] + "ies"
    else:
        head += "s"
    return head + (f" ({tail}" if tail else "")


def _feeling(c: Creature) -> str:
    bits = []
    if c.satiety < 15:
        bits.append("starving")
    elif c.satiety < 35:
        bits.append("very hungry")
    elif c.satiety < 60:
        bits.append("a bit hungry")
    else:
        bits.append("fed")
    if c.energy < 20:
        bits.append("exhausted")
    elif c.energy < 50:
        bits.append("tired")
    if c.health < 40:
        bits.append("hurting badly")
    elif c.health < 80:
        bits.append("sore")
    return ", ".join(bits)


def inventory_text(world: World, c: Creature) -> str:
    items = [(world.catalog.name(i), n) for i, n in sorted(c.inventory.items()) if n > 0]
    if not items:
        return "nothing"
    return ", ".join(f"{n} {name}" if n > 1 else f"1 {name}" for name, n in items)


def _far_features(world: World, c: Creature, r: int) -> str:
    seen: dict[str, tuple[int, str]] = {}
    for y in range(c.y - r, c.y + r + 1):
        for x in range(c.x - r, c.x + r + 1):
            if not world.in_bounds(x, y) or (x == c.x and y == c.y):
                continue
            t = world.tile(x, y)
            key = {"w": "water", "W": "water", "r": "rocky ground", "f": "forest", "s": "sand"}.get(t)
            if not key:
                continue
            d = dist(c.x, c.y, x, y)
            if key not in seen or d < seen[key][0]:
                seen[key] = (d, direction(x - c.x, y - c.y))
    return "; ".join(f"{k} {_where(d, dirn)}" for k, (d, dirn) in sorted(seen.items(), key=lambda kv: kv[1][0]))


def perceive(world: World, creature: Creature, heard: list[str] | None = None) -> str:
    c = creature
    r = sight_range(world, c)
    lines: list[str] = []
    phase = world.clock()["phase"]
    light = "It is dark; you can only see a couple of steps." if r == NIGHT_SIGHT else (
        "It is night, but firelight lets you see around you." if phase == "night" else "")
    lines.append(f"{world.time_text()}. {light}".strip())

    under = TILE_NAMES[world.tile(c.x, c.y)]
    here_obj = world.object_at(c.x, c.y)
    here = f"You stand on {under}"
    if here_obj:
        here += f", by a {here_obj.name}"
    pile = world.ground.get((c.x, c.y))
    if pile:
        here += ". On the ground here: " + ", ".join(f"{n} {world.catalog.name(i)}" for i, n in pile.items())
    lines.append(here + ".")
    near = {world.tile(c.x + dx, c.y + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)}
    if near & {"g", "f"}:
        lines.append("Tall grass grows all around you; its tough stems could be gathered as plant fiber.")

    groups: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for o, d, dirn in visible_objects(world, c):
        if o is here_obj:
            continue
        label = o.name
        if o.kind == "campfire":
            label = "campfire (burning)" if o.data.get("lit") else "campfire (cold ashes)"
        if o.kind == "sign" and o.data.get("text"):
            label = "sign with writing"
        if o.kind == "terminal":
            label = "strange terminal (running a program)" if o.data.get("code") else "strange terminal (its screen glows, waiting)"
        groups[label].append((d, dirn))
    if groups:
        parts = []
        for label, hits in sorted(groups.items(), key=lambda kv: kv[1][0][0])[:9]:
            d, dirn = hits[0]
            if len(hits) == 1:
                parts.append(f"{article(label)} {label} {_where(d, dirn)}")
            else:
                parts.append(f"{len(hits)} {plural(label)}, the nearest {_where(d, dirn)}")
        lines.append("You see: " + "; ".join(parts) + ".")
    else:
        lines.append("You see nothing notable nearby.")

    piles = [(x, y, d, dirn) for x, y, d, dirn in visible_piles(world, c) if d > 0]
    if piles:
        lines.append("Items lying on the ground: " + "; ".join(
            ", ".join(f"{n} {world.catalog.name(i)}" for i, n in world.ground[(x, y)].items()) + f" {_where(d, dirn)}"
            for x, y, d, dirn in piles[:3]) + ".")

    others = visible_creatures(world, c)
    if others:
        parts = []
        for o, d, dirn in others[:6]:
            desc = f"{o.name} {_where(d, dirn)}"
            if o.collapsed:
                desc += ", collapsed on the ground"
            elif o.asleep:
                desc += ", curled up on the ground fast asleep (they won't stir for a long while)"
            else:
                act = (o.activity or {}).get("label")
                if act:
                    desc += f", {act}"
            tool = next((world.catalog.name(t) for t in ("copper_pickaxe", "stone_pickaxe", "stone_axe", "stone_knife") if o.inventory.get(t)), None)
            if tool:
                desc += f", carrying a {tool}"
            parts.append(desc)
        lines.append("Others: " + "; ".join(parts) + ".")

    far = _far_features(world, c, r)
    if far:
        lines.append("Around you: " + far + ".")

    if heard:
        lines.append("You hear: " + " ".join(heard[-6:]))

    lines.append(f"You carry: {inventory_text(world, c)}.")
    placeable = [world.catalog.name(i) for i, n in c.inventory.items() if n > 0 and world.catalog.items[i].placeable]
    if placeable:
        lines.append(f"You could set up the {', '.join(placeable)} you carry right here, with place.")
    if sum(1 for n in c.inventory.values() if n > 0) >= 2:
        lines.append("Your hands itch to try combining some of what you carry.")
    lines.append(f"You feel {_feeling(c)}.")
    foods = [(i, n) for i, n in c.inventory.items() if n > 0 and world.catalog.items[i].food > 0]
    if c.satiety < 40 and foods:
        lines.append("Your stomach growls. You carry food you could eat right now: "
                     + ", ".join(f"{n} {world.catalog.name(i)}" for i, n in foods) + ".")
    if c.activity:
        lines.append(f"You are {c.activity.get('label', 'busy')}.")
    return "\n".join(lines)
