"""World -> text: a creature's first-person view of what it can sense right now."""

from __future__ import annotations

import math
from collections import defaultdict

from .model import ANIMALS, OBJECT_NAMES, TILE_NAMES, Creature, World, WorldObject

DAY_SIGHT = 6
NIGHT_SIGHT = 2
FIRE_SIGHT = 5
FIRE_RADIUS = 3
GLOW_SIGHT = 8  # how far a fire's glow can be seen at night
LANDMARK_RANGE = 14

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


# Things worth walking back to: a creature remembers where it last saw the nearest of each kind.
REMEMBERED_KINDS = {"tree", "pine", "bush", "rock", "clay", "copper_vein", "iron_vein", "campfire", "workbench",
                    "furnace", "terminal", "tablet", "sign", "chest", "basket", "millstone", "bed"}
MAX_SPOTS = 20
RECALL_SHOWN = 5


def spot_name(kind: str) -> str:
    return "water" if kind == "water" else OBJECT_NAMES.get(kind, kind)


def note_spots(world: World, c: Creature, tick: int) -> None:
    """Update the creature's map memory from what it sees: newest sighting wins, things found gone are forgotten."""
    r = sight_range(world, c)
    nearest: dict[str, tuple[int, int, int]] = {}
    for o, d, _ in visible_objects(world, c):
        if o.kind in REMEMBERED_KINDS and (o.kind not in nearest or d < nearest[o.kind][0]):
            nearest[o.kind] = (d, o.x, o.y)
    for y in range(c.y - r, c.y + r + 1):
        for x in range(c.x - r, c.x + r + 1):
            if world.in_bounds(x, y) and world.tile(x, y) in "wW":
                d = dist(c.x, c.y, x, y)
                if "water" not in nearest or d < nearest["water"][0]:
                    nearest["water"] = (d, x, y)
    for lm in getattr(world, "landmarks", []):
        if dist(c.x, c.y, lm["x"], lm["y"]) <= LANDMARK_RANGE:
            c.landmarks_seen.add(lm["name"])
    for kind, (x, y, _t) in list(c.spots.items()):
        if kind not in nearest and dist(c.x, c.y, x, y) <= r:  # should be in view, isn't: it's gone
            del c.spots[kind]
    for kind, (_d, x, y) in nearest.items():
        c.spots[kind] = (x, y, tick)
    if len(c.spots) > MAX_SPOTS:
        for kind, _ in sorted(c.spots.items(), key=lambda kv: kv[1][2])[:len(c.spots) - MAX_SPOTS]:
            del c.spots[kind]


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
    if rng is None and r < DAY_SIGHT:  # in the dark, fires and lights still glow from afar
        seen = {o.id for o, _, _ in out}
        for y in range(creature.y - GLOW_SIGHT, creature.y + GLOW_SIGHT + 1):
            for x in range(creature.x - GLOW_SIGHT, creature.x + GLOW_SIGHT + 1):
                o = world.object_at(x, y)
                if o and o.id not in seen and ((o.kind == "campfire" and o.data.get("lit"))
                                               or (o.kind == "creation" and "light" in o.data.get("effects", ()))):
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
    if c.energy < 15:
        bits.append("exhausted, your legs heavy (rest soon)")
    elif c.energy < 25:
        bits.append("very tired")
    elif c.energy < 50:
        bits.append("tired")
    if c.health < 40:
        bits.append("hurting badly")
    elif c.health < 80:
        bits.append("sore")
    return ", ".join(bits)


def _animal_doing(o: WorldObject) -> str:
    state = o.data["state"]
    if state == "follow":
        return f"following {o.data.get('tamed_by', 'its owner')}"
    return {"graze": "grazing", "rest": "resting", "wary": "edging away from you", "home": "heading home"}.get(state, "")


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
    weather = ""
    if getattr(world, "weather", "clear") == "rain":
        weather = "Rain is falling."
    if c.satiety < 15:  # the body's alarm comes before everything else
        lines.append("You are starving: eat now or you will collapse.")
    lines.append(f"{world.time_text()}. {weather} {light}".replace("  ", " ").strip())

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
            label = "campfire (burning)" if o.data.get("lit") else "campfire (cold ashes; feeding it sticks would bring it back to life)"
        if o.kind == "sign" and o.data.get("text"):
            label = "sign with writing"
        elif o.data.get("text") and o.kind in ("tree", "pine", "rock", "stump"):
            label = f"{o.name} with words carved into it"
        elif o.kind in ("basket", "chest"):
            held = o.data.get("items") or {}
            label = f"{o.name} (holding " + ", ".join(f"{n} {world.catalog.name(i)}" for i, n in held.items()) + ")" if held else f"empty {o.name}"
        if o.kind in ANIMALS and o.data.get("state"):
            label = f"{o.name} {_animal_doing(o)}".strip()
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
            elif (o.activity or {}).get("sleep"):
                desc += ", asleep for the night"
            else:
                act = (o.activity or {}).get("label")
                if act:
                    desc += f", {act}"
            tool = next((world.catalog.name(t) for t in ("copper_pickaxe", "stone_pickaxe", "stone_axe", "stone_knife") if o.inventory.get(t)), None)
            if tool:
                desc += f", carrying a {tool}"
            parts.append(desc)
        lines.append("Others: " + "; ".join(parts) + ".")

    marks = []
    for lm in getattr(world, "landmarks", []):
        d = dist(c.x, c.y, lm["x"], lm["y"])
        if d <= LANDMARK_RANGE:
            marks.append((d, "you are at " + lm["name"] if d <= 3 else f"{lm['name']} {_where(d, direction(lm['x'] - c.x, lm['y'] - c.y))}"))
    if marks:
        lines.append("Places you know: " + "; ".join(t for _, t in sorted(marks)[:4]) + ".")
    far = _far_features(world, c, r)
    if far:
        lines.append("Around you: " + far + ".")
    in_view = {o.kind for o, _, _ in visible_objects(world, c)} | ({"water"} if far and "water" in far else set())
    recalled = sorted((dist(c.x, c.y, x, y), kind, x, y) for kind, (x, y, _t) in c.spots.items() if kind not in in_view)
    if recalled:
        lines.append("You remember: " + ", ".join(f"{spot_name(k)} {_where(d, direction(x - c.x, y - c.y))}"
                                                  for d, k, x, y in recalled[:RECALL_SHOWN]) + ".")

    if heard:
        lines.append("You hear: " + " ".join(heard[-6:]))

    lines.append(f"You carry: {inventory_text(world, c)}.")
    placeable = [world.catalog.name(i) for i, n in c.inventory.items() if n > 0 and world.catalog.items[i].placeable]
    if placeable:
        lines.append(f"You could set up the {', '.join(placeable)} you carry right here, with place.")
    if sum(1 for n in c.inventory.values() if n > 0) >= 2:
        lines.append("Your hands itch to try combining some of what you carry.")
    lines.append(f"You feel {_feeling(c)}.")
    phase = world.clock()["phase"]
    if (phase == "night" or getattr(world, "weather", "clear") == "rain") and not near_lit_fire(world, c.x, c.y, 3):
        sheltered = any(o.kind in ("bed",) or (o.kind == "creation" and "shelter" in o.data.get("effects", ()))
                        for o, d, _ in visible_objects(world, c, 2))
        if not sheltered:
            lines.append("You are soaked and shivering; a fire or shelter would help." if getattr(world, "weather", "clear") == "rain"
                         else "The night air is cold; you'd be better off by a fire or under shelter.")
    foods = [(i, n) for i, n in c.inventory.items() if n > 0 and world.catalog.items[i].food > 0]
    foods = [(i, n) for i, n in foods if "seed" not in world.catalog.items[i].tags] or foods  # seeds only in a pinch
    if c.satiety < 40 and foods:
        lines.append("Your stomach growls. You carry food you could eat right now: "
                     + ", ".join(f"{n} {world.catalog.name(i)}" for i, n in foods) + ".")
    if c.activity:
        lines.append(f"You are {c.activity.get('label', 'busy')}.")
    return "\n".join(lines)
