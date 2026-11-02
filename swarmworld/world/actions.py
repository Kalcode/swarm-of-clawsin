"""Text -> world: parse a creature's stated intention, validate it against what it can
perceive and hold, then carry it out (or refuse with an in-world reason)."""

from __future__ import annotations

import json
import re
from collections import Counter, deque
from dataclasses import dataclass, field

from .catalog import Recipe
from .events import HEARING
from .model import ANIMALS, BLOCKING, OBJECT_ALIASES, Creature, World, WorldObject
from .perception import DIRS, dist, direction, sight_range, visible_creatures, visible_objects

VERBS = [
    "walk_to", "explore", "gather", "combine", "craft", "eat", "drink", "say", "give",
    "pick_up", "drop", "place", "write", "read", "program", "rest", "wait", "plant", "invent",
]
VERB_ALIASES = {
    "walk": "walk_to", "go": "walk_to", "go_to": "walk_to", "goto": "walk_to", "move": "walk_to",
    "move_to": "walk_to", "approach": "walk_to", "head_to": "walk_to", "walkto": "walk_to",
    "wander": "explore", "search": "explore", "scout": "explore",
    "collect": "gather", "harvest": "gather", "chop": "gather", "mine": "gather", "pick": "gather",
    "forage": "gather", "dig": "gather",
    "make": "craft", "build": "craft", "create": "craft",
    "mix": "combine", "experiment": "combine",
    "speak": "say", "talk": "say", "tell": "say", "shout": "say", "ask": "say", "reply": "say",
    "pickup": "pick_up", "take": "pick_up", "grab": "pick_up",
    "sleep": "rest", "idle": "wait", "look": "wait", "observe": "wait",
    "inspect": "read", "examine": "read", "consume": "eat", "trade": "give", "hand": "give",
    "put": "place", "set_up": "place", "code": "program", "write_code": "program",
    "sow": "plant", "farm": "plant", "seed": "plant", "harvest_crop": "gather",
    "design": "invent", "innovate": "invent", "devise": "invent",
}
FILLER = {"the", "a", "an", "nearest", "closest", "nearby", "near", "some", "to", "that", "this", "over", "there", "my"}
VECTORS = {"east": (1, 0), "southeast": (1, 1), "south": (0, 1), "southwest": (-1, 1),
           "west": (-1, 0), "northwest": (-1, -1), "north": (0, -1), "northeast": (1, -1)}
TOOLS_AXE = ("stone_axe",)
GATHERABLE = {"tree", "pine", "bush", "rock", "copper_vein", "iron_vein", "clay", "crop", "chicken", "sheep", "cow"}
ITEM_SOURCES = {
    "stick": {"tree", "pine"}, "log": {"tree", "pine"}, "stone": {"rock"}, "flint": {"rock"},
    "berries": {"bush"}, "clay": {"clay"}, "copper_ore": {"copper_vein"}, "iron_ore": {"iron_vein"},
    "wheat": {"crop"}, "carrot": {"crop"}, "egg": {"chicken"}, "milk": {"cow"}, "wool": {"sheep"},
}
ANIMAL_FOOD = {"wheat", "wheat_seeds", "carrot_seeds", "berries", "carrot", "plant_fiber"}
EMPTY_KINDS = {"bush_empty", "stump"}
CARVABLE = {"tree", "pine", "rock", "stump"}
TOOLS_PICK = ("stone_pickaxe", "copper_pickaxe")


@dataclass
class Intention:
    action: str
    target: str = ""
    items: list[str] = field(default_factory=list)
    text: str = ""
    count: int = 1
    goal: str = ""
    thought: str = ""

    def summary(self) -> str:
        bits = [self.action]
        if self.target:
            bits.append(self.target)
        if self.items:
            bits.append("[" + ", ".join(self.items) + "]")
        if self.count > 1:
            bits.append(f"x{self.count}")
        if self.text:
            bits.append(f'"{self.text[:80]}"')
        return " ".join(bits)


@dataclass
class ActionResult:
    ok: bool
    message: str
    instant: bool = True


# --------------------------------------------------------------------- parsing
def _first_json_object(s: str) -> dict | None:
    s = re.sub(r"```(?:json)?", "", s)
    start = s.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(s)):
            ch = s[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(s[start:i + 1])
                        return obj if isinstance(obj, dict) else None
                    except json.JSONDecodeError:
                        break
        start = s.find("{", start + 1)
    return None


def parse_intention(raw: dict | str | None) -> Intention | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        raw = _first_json_object(raw)
        if raw is None:
            return None
    if not isinstance(raw, dict):
        return None
    action = str(raw.get("action") or "").strip().lower().replace(" ", "_").replace("-", "_")
    action = VERB_ALIASES.get(action, action)
    if action not in VERBS:
        return None
    items = raw.get("items") or []
    if isinstance(items, str):
        items = [p for p in re.split(r",|\+| and ", items) if p.strip()]
    items = [str(i).strip() for i in items if str(i).strip()][:6]
    try:
        count = int(raw.get("count") or 1)
    except (TypeError, ValueError):
        count = 1
    return Intention(
        action=action,
        target=str(raw.get("target") or "").strip()[:80],
        items=items,
        text=str(raw.get("text") or "").strip()[:2000],
        count=max(1, min(5, count)),
        goal=str(raw.get("goal") or "").strip()[:160],
        thought=str(raw.get("thought") or "").strip()[:300],
    )


# ------------------------------------------------------------------- targeting
def _words(s: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9']+", s.lower()) if w not in FILLER]


def _dir_hint(words: list[str]) -> tuple[str | None, list[str]]:
    for w in words:
        if w in DIRS:
            return w, [x for x in words if x != w]
    return None, words


def _object_matches(o: WorldObject, phrase: str, words: list[str]) -> bool:
    names = [o.name.lower()] + OBJECT_ALIASES.get(o.kind, [])
    if phrase in names:
        return True
    return any(n in phrase for n in names if len(n) > 2) or any(w in names for w in words)


def find_creature(world: World, c: Creature, target: str, max_dist: int | None = None) -> Creature | None:
    words = set(_words(target))
    best = None
    for other, d, _ in visible_creatures(world, c):
        if other.name.lower() in words or other.name.lower() == target.strip().lower():
            if max_dist is None or d <= max_dist:
                if best is None or d < best[1]:
                    best = (other, d)
    return best[0] if best else None


def find_landmark(world: World, c: Creature, target: str) -> dict | None:
    """A named place the creature would know: within a long walk, matched by its name."""
    t = " ".join(_words(target.replace("'", "'")))
    if not t:
        return None
    best = None
    for lm in getattr(world, "landmarks", []):
        name = " ".join(_words(lm["name"]))
        if name and (name == t or name in t or (t in name and len(t) > 3)):
            d = dist(c.x, c.y, lm["x"], lm["y"])
            if d <= 30 and (best is None or d < best[0]):
                best = (d, lm)
    return best[1] if best else None


def find_object(world: World, c: Creature, target: str, max_dist: int | None = None,
                kinds: set[str] | None = None) -> WorldObject | None:
    words = _words(target)
    hint, words = _dir_hint(words)
    phrase = " ".join(words)
    if not phrase and not kinds:
        return None
    cands = []
    for o, d, dirn in visible_objects(world, c):
        if kinds and o.kind not in kinds:
            continue
        if phrase and not _object_matches(o, phrase, words):
            continue
        if max_dist is not None and d > max_dist:
            continue
        cands.append((0 if (hint and hint == dirn) else 1, d, o))
    if not cands:
        return None
    cands.sort(key=lambda t: (t[0], t[1]))
    return cands[0][2]


def _nearest_tile(world: World, c: Creature, tiles: str, r: int) -> tuple[int, int, int] | None:
    best = None
    for y in range(c.y - r, c.y + r + 1):
        for x in range(c.x - r, c.x + r + 1):
            if world.in_bounds(x, y) and world.tile(x, y) in tiles:
                d = dist(c.x, c.y, x, y)
                if best is None or d < best[2]:
                    best = (x, y, d)
    return best


TILE_TARGETS = {
    "water": "wW", "lake": "wW", "river": "wW", "pond": "wW", "stream": "wW",
    "sand": "s", "beach": "s", "shore": "s", "grass": "g", "meadow": "g",
    "forest": "f", "woods": "f", "hills": "r", "hill": "r", "rocky": "r", "dirt": "d",
}


# ------------------------------------------------------------------- movement
def bfs_path(world: World, start: tuple[int, int], goals: set[tuple[int, int]], limit: int = 2500,
             avoid: set[tuple[int, int]] | None = None) -> list[tuple[int, int]] | None:
    if start in goals:
        return []
    avoid = avoid or set()
    prev: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
    q = deque([start])
    while q and len(prev) < limit:
        cur = q.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
            nx, ny = cur[0] + dx, cur[1] + dy
            nxt = (nx, ny)
            if nxt in prev or not world.walkable(nx, ny) or nxt in avoid:
                continue
            if dx and dy and not (world.walkable(cur[0] + dx, cur[1]) and world.walkable(cur[0], cur[1] + dy)):
                continue
            prev[nxt] = cur
            if nxt in goals:
                path = [nxt]
                while prev[path[-1]] != start:
                    path.append(prev[path[-1]])
                return list(reversed(path))
            q.append(nxt)
    return None


def _adjacent_goals(world: World, x: int, y: int, include_self: bool = False) -> set[tuple[int, int]]:
    goals = {(x + dx, y + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if (dx or dy) and world.walkable(x + dx, y + dy)}
    if include_self and world.walkable(x, y):
        goals.add((x, y))
    return goals


def occupied_tiles(world: World, ignore: str | None = None) -> set[tuple[int, int]]:
    return {(o.x, o.y) for o in world.creatures.values() if o.id != ignore and not o.collapsed}


def start_walk(world: World, c: Creature, goals: set[tuple[int, int]], label: str, arrive_msg: str) -> ActionResult:
    taken = occupied_tiles(world, c.id)
    free_goals = goals - taken
    if (c.x, c.y) in goals:
        return ActionResult(True, arrive_msg)
    path = bfs_path(world, (c.x, c.y), free_goals or goals, avoid=taken) if free_goals else None
    if path is None:
        path = bfs_path(world, (c.x, c.y), goals)  # crowded: head there anyway and stop when blocked
    if path is None:
        return ActionResult(False, f"You can't find a way to get there ({label}).")
    if not path:
        return ActionResult(True, arrive_msg)
    c.activity = {"type": "walk", "path": path, "label": label, "result": arrive_msg}
    return ActionResult(True, f"You set off, {label}.", instant=False)


# --------------------------------------------------------------------- helpers
def _has_tool(c: Creature, tools: tuple[str, ...]) -> str | None:
    return next((t for t in tools if c.inventory.get(t, 0) > 0), None)


def station_near(world: World, c: Creature, kind: str, r: int = 2) -> bool:
    for y in range(c.y - r, c.y + r + 1):
        for x in range(c.x - r, c.x + r + 1):
            o = world.object_at(x, y)
            if o and o.kind == kind and (kind != "campfire" or o.data.get("lit")):
                return True
            if o and o.kind == "creation" and kind == "bed" and "shelter" in o.data.get("effects", ()):
                return True
    return False


EFFECT_STEMS = {  # matched at the start of a word, so "glow" catches "glowstick" and "glowing"
    "shelter": ("hut", "shelter", "house", "home", "tent", "lean-to", "lean to", "cabin", "roof", "den", "bed", "hammock", "sleep"),
    "light": ("torch", "lamp", "lantern", "beacon", "candle", "light", "glow", "illumin", "shine", "shining", "bright"),
}


def invention_effects(text: str) -> list[str]:
    t = text.lower()
    return [eff for eff, stems in EFFECT_STEMS.items() if any(re.search(rf"\b{re.escape(w)}", t) for w in stems)]


def _resolve_held(world: World, c: Creature, name: str) -> tuple[str | None, str]:
    iid = world.catalog.resolve(name)
    if iid is None:
        return None, f"You don't know of anything called '{name}'."
    if c.inventory.get(iid, 0) <= 0:
        return None, f"You don't have any {world.catalog.name(iid)}."
    return iid, ""


def _busy(c: Creature, ticks: int, label: str, result: str, **extra) -> ActionResult:
    c.activity = {"type": "busy", "ticks": max(1, ticks), "label": label, "result": result, **extra}
    return ActionResult(True, result, instant=False)


def _items_text(world: World, items: Counter) -> str:
    return ", ".join(f"{n} {world.catalog.name(i)}" for i, n in items.items() if n > 0) or "nothing"


# --------------------------------------------------------------------- crafting
def _try_recipe(world: World, c: Creature, r: Recipe, count: int, via: str) -> ActionResult:
    cat = world.catalog
    count = max(1, count)
    for iid, n in r.inputs.items():
        have = c.inventory.get(iid, 0)
        if have < n:
            if via == "combine":
                return ActionResult(False, f"You sense these could become something, but you'd need {n} {cat.name(iid)} (you have {have}).")
            return ActionResult(False, f"To make {cat.name(r.output)} you need {n} {cat.name(iid)}, but you have {have}.")
        count = min(count, have // n)
    for t in r.tools:
        if c.inventory.get(t, 0) <= 0:
            return ActionResult(False, f"You'd need to be holding a {cat.name(t)} to work these.")
    if r.station and not station_near(world, c, r.station):
        extra = " (a burning one)" if r.station == "campfire" else ""
        return ActionResult(False, f"This seems to need a {cat.name(r.station)}{extra} within 2 steps.")
    for iid, n in r.inputs.items():
        c.inventory[iid] -= n * count
        if c.inventory[iid] <= 0:
            del c.inventory[iid]
    made = r.count * count
    c.inventory[r.output] += made
    first_time = r.output not in c.known_recipes
    c.known_recipes.add(r.output)
    c.stats["crafted"] += made
    recipe_text = cat.describe_recipe(r)
    item = cat.items[r.output]
    extra = ""
    if first_time and item.desc:
        extra += f" {item.desc}"
    if item.placeable:
        extra += f" (Use place to set the {item.name} down.)"
    if r.output not in world.discoveries and not r.known_at_start:
        world.discoveries[r.output] = {"item": r.output, "by": c.name, "by_id": c.id, "model": c.model, "tick": world.tick}
        world.emit("discover", c.id, c.x, c.y, f"{c.name} discovered how to make {cat.name(r.output)}! ({recipe_text})", item=r.output)
        c.stats["discoveries"] += 1
        msg = f"Eureka! You made {made} {cat.name(r.output)}. Nobody has ever made this before. Recipe: {recipe_text}.{extra}"
    else:
        world.emit("craft", c.id, c.x, c.y, f"{c.name} made {made} {cat.name(r.output)}.", item=r.output)
        msg = f"You made {made} {cat.name(r.output)}." + (f" You now know the recipe: {recipe_text}." if first_time else "") + extra
    return ActionResult(True, msg)


def _flee(world: World, c: Creature, obj: WorldObject) -> tuple[int, int]:
    dx = (obj.x > c.x) - (obj.x < c.x)
    dy = (obj.y > c.y) - (obj.y < c.y)
    return obj.x + dx, obj.y + dy


def _walk_then(world: World, c: Creature, obj: WorldObject, it: Intention) -> ActionResult:
    """Walk next to a visible object, then carry out the original intention on arrival."""
    goals = _adjacent_goals(world, obj.x, obj.y, include_self=obj.kind not in BLOCKING)
    res = start_walk(world, c, goals, f"walking to the {obj.name}", f"You arrive beside the {obj.name}.")
    if c.activity:
        c.activity["then"] = it
    return res


def _next_hint(obj: WorldObject) -> str:
    if obj.kind in ("tree", "pine", "bush", "rock", "clay", "copper_vein", "iron_vein"):
        return f"You can gather from it now."
    if obj.kind in ("sign", "tablet"):
        return "You can read it now."
    if obj.kind == "terminal":
        return "You can read or program it now."
    if obj.kind in ("bush_empty", "stump"):
        return "It has nothing to take right now."
    return ""


# --------------------------------------------------------------------- verbs
def _walk_to(world: World, c: Creature, it: Intention) -> ActionResult:
    if not it.target:
        return ActionResult(False, "Walk to what? Name something you can see.")
    other = find_creature(world, c, it.target)
    if other:
        d = dist(c.x, c.y, other.x, other.y)
        if it.text and d <= HEARING:  # they meant to talk, and they're within earshot already
            return _say(world, c, Intention("say", target=other.name, text=it.text))
        if d <= 1:
            return ActionResult(True, f"You are already beside {other.name}. You can talk (say) or give them something.")
        res = start_walk(world, c, _adjacent_goals(world, other.x, other.y), f"walking to {other.name}", f"You reach {other.name}.")
        if it.text and c.activity:
            c.activity["say"] = (other.name, it.text)
        return res
    for w_ in _words(it.target):
        seen = c.seen_pos.get(w_)
        if seen:
            x, y, _t = seen
            name = next((o.name for o in world.creatures.values() if o.name.lower() == w_), w_.capitalize())
            res = start_walk(world, c, _adjacent_goals(world, x, y, include_self=True), f"heading to where you last saw {name}",
                             f"You reach the spot where you last saw {name}.")
            if it.text and c.activity:
                c.activity["say"] = (name, it.text)
            return res
    lm = find_landmark(world, c, it.target)
    if lm:
        if dist(c.x, c.y, lm["x"], lm["y"]) <= 2:
            return ActionResult(True, f"You are at {lm['name']}.")
        goals = {(x, y) for x in range(lm["x"] - 2, lm["x"] + 3) for y in range(lm["y"] - 2, lm["y"] + 3) if world.walkable(x, y)}
        return start_walk(world, c, goals, f"heading to {lm['name']}", f"You arrive at {lm['name']}.")
    obj = find_object(world, c, it.target)
    if obj:
        if dist(c.x, c.y, obj.x, obj.y) <= 1:
            return ActionResult(True, f"You are already beside the {obj.name}. {_next_hint(obj)}".strip())
        return start_walk(world, c, _adjacent_goals(world, obj.x, obj.y, include_self=obj.kind not in ("tree", "pine", "rock")),
                          f"walking to the {obj.name}", f"You arrive beside the {obj.name}.")
    for w in _words(it.target):
        if w in TILE_TARGETS:
            hit = _nearest_tile(world, c, TILE_TARGETS[w], sight_range(world, c))
            if hit:
                x, y, d = hit
                goals = _adjacent_goals(world, x, y, include_self=True)
                return start_walk(world, c, goals, f"walking to the {w}", f"You reach the {w}.")
    iid = world.catalog.resolve(it.target)
    if iid:
        for (x, y), pile in world.ground.items():
            if pile.get(iid) and dist(c.x, c.y, x, y) <= sight_range(world, c):
                return start_walk(world, c, _adjacent_goals(world, x, y, include_self=True),
                                  f"walking to the {world.catalog.name(iid)}", f"You reach the {world.catalog.name(iid)} on the ground.")
    for d in DIRS:
        if d in _words(it.target):
            return _explore(world, c, Intention("explore", target=d))
    return ActionResult(False, f"You don't see any '{it.target}' around you.")


def _explore(world: World, c: Creature, it: Intention) -> ActionResult:
    words = _words(it.target)
    d = next((w for w in words if w in DIRS), None) or world.rng.choice(DIRS)

    order = sorted(DIRS, key=lambda o: min((DIRS.index(o) - DIRS.index(d)) % 8, (DIRS.index(d) - DIRS.index(o)) % 8))
    for alt in order:
        vx, vy = VECTORS[alt]
        for span in (9, 7, 5, 3):
            tx, ty = c.x + vx * span, c.y + vy * span
            goals = {(x, y) for x in range(tx - 1, tx + 2) for y in range(ty - 1, ty + 2) if world.walkable(x, y)}
            path = bfs_path(world, (c.x, c.y), goals) if goals else None
            if path:
                note = "" if alt == d else f"The land ends to the {d}, so you turn {alt} instead. "
                c.activity = {"type": "walk", "path": path, "label": f"exploring {alt}", "result": f"{note}You walked {alt} for a while."}
                return ActionResult(True, f"{note}You head off {alt}.", instant=False)
    return ActionResult(False, "There's nowhere to go from here.")


def _gather(world: World, c: Creature, it: Intention) -> ActionResult:
    cat = world.catalog
    target = it.target or (it.items[0] if it.items else "")
    words = _words(target)
    obj = None
    if target:
        obj = find_object(world, c, target, max_dist=1)
        source_kinds = ITEM_SOURCES.get(world.catalog.resolve(target) or "")
        if source_kinds and (obj is None or obj.kind not in source_kinds):
            # "gather stick" means: get sticks from the nearest thing that gives them
            near = find_object(world, c, "", max_dist=1, kinds=source_kinds)
            if near is None:
                far_src = find_object(world, c, "", kinds=source_kinds)
                if far_src is not None:
                    return _walk_then(world, c, far_src, Intention("gather", target=far_src.name, count=it.count))
            else:
                obj = near
        if obj is not None and obj.kind in EMPTY_KINDS:
            # Prefer something that still has something to give, if one is in sight.
            fresh = find_object(world, c, target, kinds=GATHERABLE)
            if fresh is not None:
                if dist(c.x, c.y, fresh.x, fresh.y) <= 1:
                    obj = fresh
                else:
                    return _walk_then(world, c, fresh, it)
        if obj is None:
            far = find_object(world, c, target, kinds=GATHERABLE) or find_object(world, c, target)
            if far:
                return _walk_then(world, c, far, it)
    else:
        for o, d, _ in visible_objects(world, c, 1):
            if o.kind in ("tree", "pine", "bush", "rock", "copper_vein", "iron_vein", "clay"):
                obj = o
                break
    want_item = cat.resolve(target) if target else None
    if obj is None:
        here = world.tile(c.x, c.y)
        near_tiles = {world.tile(c.x + dx, c.y + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)}
        if want_item == "plant_fiber" or any(w in ("grass", "fiber", "fibers", "fibre", "plant") for w in words):
            if near_tiles & {"g", "f"}:
                knife = _has_tool(c, ("stone_knife",))
                n = it.count * (2 if knife else 1)
                seeds = sum(1 for _ in range(it.count) if world.rng.random() < (0.3 if knife else 0.1))
                c.inventory["plant_fiber"] += n
                got_txt = f"{n} plant fiber"
                if seeds:
                    kind = "carrot_seeds" if world.rng.random() < 0.35 else "wheat_seeds"
                    c.inventory[kind] += seeds
                    got_txt += f" and {seeds} {world.catalog.name(kind)}"
                world.emit("gather", c.id, c.x, c.y, f"{c.name} gathered {got_txt}.")
                verb = "cut grass with your knife" if knife else "pull up grass"
                return _busy(c, 2 * it.count, "cutting grass" if knife else "pulling up grass", f"You {verb} and get {got_txt}.")
            return ActionResult(False, "There's no grass within reach here.")
        if want_item == "sand" or "sand" in words:
            if "s" in near_tiles:
                n = it.count
                c.inventory["sand"] += n
                return _busy(c, 2 * n, "scooping sand", f"You scoop up {n} sand.")
            return ActionResult(False, "There's no sand within reach.")
        if any(w in ("water", "lake", "river", "fish", "fishes", "fishing", "pond") for w in words) or want_item == "fish":
            if "w" not in near_tiles and "W" not in near_tiles:
                water = _nearest_tile(world, c, "wW", sight_range(world, c))
                if water:
                    x, y, _d = water
                    res = start_walk(world, c, _adjacent_goals(world, x, y, include_self=True), "walking to the water", "You reach the water.")
                    if c.activity:
                        c.activity["then"] = it
                    return res
                return ActionResult(False, "There's no water in sight.")
            if not _has_tool(c, ("fishing_rod",)):
                return ActionResult(False, "Fish dart about in the water, too quick to grab by hand. You'd need something to catch them with. (To drink, use drink.)")
            caught = sum(1 for _ in range(it.count) if world.rng.random() < 0.5)
            if caught:
                c.inventory["fish"] += caught
                c.stats["gathered"] += caught
                world.emit("gather", c.id, c.x, c.y, f"{c.name} caught {caught} fish.")
            msg = f"You cast your line and catch {caught} fish." if caught else "You fish patiently but catch nothing this time."
            return _busy(c, 4 * it.count, "fishing", msg)
        if not target:
            return ActionResult(False, "There's nothing to gather right beside you. Walk to a tree, bush or rock first.")
        return ActionResult(False, f"There's no '{target}' within reach to gather from.")

    got: Counter = Counter()
    label = f"gathering from the {obj.name}"
    count = 3 if it.count == 1 and obj.kind in ("tree", "pine", "bush", "rock", "clay") else it.count  # a handful
    for _ in range(count):
        if obj.kind in ("tree", "pine"):
            label = f"chopping the {obj.name}" if _has_tool(c, TOOLS_AXE) else f"breaking branches off the {obj.name}"
            if _has_tool(c, TOOLS_AXE):
                got["log"] += 1
                got["stick"] += 1
            else:
                got["stick"] += 1
            obj.data["wood"] = obj.data.get("wood", 6) - 1
            if obj.data["wood"] <= 0:
                world.change_kind(obj, "stump")
                obj.data["regrow_at"] = world.tick + 2400
                break
        elif obj.kind == "bush":
            label = "picking berries"
            got["berries"] += 1
            obj.data["berries"] = obj.data.get("berries", 6) - 1
            if obj.data["berries"] <= 0:
                world.change_kind(obj, "bush_empty")
                obj.data["regrow_at"] = world.tick + 400
                break
        elif obj.kind == "rock":
            label = "knocking stones off the boulder"
            got["stone"] += 1
            if world.rng.random() < 0.25:
                got["flint"] += 1
            obj.data["stone"] = obj.data.get("stone", 14) - 1
            if obj.data["stone"] <= 0:
                world.remove_object(obj.id)
                break
        elif obj.kind in ("copper_vein", "iron_vein"):
            if not _has_tool(c, TOOLS_PICK):
                if not got:
                    return ActionResult(False, f"The {obj.name} is too hard to break with your hands. You'd need a pickaxe.")
                break
            label = f"mining the {obj.name}"
            got["copper_ore" if obj.kind == "copper_vein" else "iron_ore"] += 1
            obj.data["ore"] = obj.data.get("ore", 8) - 1
            if obj.data["ore"] <= 0:
                world.change_kind(obj, "rock")
                break
        elif obj.kind == "clay":
            label = "digging clay"
            got["clay"] += 1
            obj.data["clay"] = obj.data.get("clay", 6) - 1
            if obj.data["clay"] <= 0:
                world.remove_object(obj.id)
                break
        elif obj.kind == "crop":
            if obj.data.get("stage", 0) < 2:
                return ActionResult(False, f"The {obj.name} isn't ripe yet. Wait a while.")
            crop = obj.data.get("crop", "wheat")
            label = f"harvesting {crop}"
            got[crop] += 3
            got[f"{crop}_seeds"] += world.rng.choice((1, 2))
            world.remove_object(obj.id)
            break
        elif obj.kind in ANIMALS:
            if not obj.data.get("tamed_by"):
                world.move_object(obj, *_flee(world, c, obj))
                return ActionResult(False, f"The wild {obj.kind} shies away from you. Animals might trust someone who feeds them.")
            if world.tick < obj.data.get("ready_at", 0):
                return ActionResult(False, f"The {obj.name} has nothing for you yet. Come back later.")
            if obj.kind == "chicken":
                got["egg"] += 1
                label = "collecting an egg"
            elif obj.kind == "cow":
                got["milk"] += 1
                label = "milking the cow"
            else:
                if not _has_tool(c, ("stone_knife",)):
                    return ActionResult(False, "You'd need something sharp to shear the sheep.")
                got["wool"] += 2
                label = "shearing the sheep"
            obj.data["ready_at"] = world.tick + 300
            break
        elif obj.kind == "sapling":
            return ActionResult(False, "The sapling is still growing; leave it be.")
        elif obj.kind in ("bush_empty", "stump"):
            return ActionResult(False, f"The {obj.name} has nothing left to take right now.")
        else:
            return ActionResult(False, f"You can't gather anything from the {obj.name}.")
    helper = next((i for i in c.inventory if c.inventory[i] > 0 and "tool" in world.catalog.items.get(i, None).tags
                   and "invention" in world.catalog.items[i].tags), None) if got else None
    if helper:
        best = max(got, key=lambda k: got[k])
        got[best] += 1
    c.inventory.update(got)
    c.stats["gathered"] += sum(got.values())
    c.energy = max(0.0, c.energy - 0.5 * sum(got.values()))  # gathering is work
    world.emit("gather", c.id, c.x, c.y, f"{c.name} gathered {_items_text(world, got)}.")
    bonus = f" Your {world.catalog.name(helper)} helps." if helper else ""
    return _busy(c, 2 * max(1, sum(got.values()) // 2 + 1), label, f"You gathered {_items_text(world, got)}.{bonus}")


def _recipe_ready(world: World, c: Creature, r: Recipe) -> bool:
    return (all(c.inventory.get(i, 0) >= n for i, n in r.inputs.items())
            and all(c.inventory.get(t, 0) > 0 for t in r.tools)
            and (not r.station or station_near(world, c, r.station)))


def choose_recipe(world: World, c: Creature, ids: set[str], hint: str = "") -> Recipe | None:
    """Pick what a combination becomes: what the creature says it wants, then what it can finish right now,
    then something it hasn't made before, then the simplest."""
    cat = world.catalog
    exact = [r for r in cat.recipes if set(r.inputs) == ids]
    if not exact:  # a tool named among the ingredients is just the tool being used
        exact = [r for r in cat.recipes if r.tools and set(r.tools) <= ids and set(r.inputs) == ids - set(r.tools)]
    cands = exact or [r for r in cat.recipes if set(r.inputs) <= ids and len(r.inputs) >= 2]
    if not cands:
        return None
    wanted = cat.resolve(hint) if hint else None
    cands.sort(key=lambda r: (r.output != wanted, not _recipe_ready(world, c, r), r.output in c.known_recipes,
                              -len(r.inputs), sum(r.inputs.values())))
    return cands[0]


def _combine(world: World, c: Creature, it: Intention) -> ActionResult:
    names = list(it.items)
    hint = it.text
    # The target may list ingredients ("stick, flint") or name what the creature hopes to make ("stone knife").
    parts = [p.strip() for p in re.split(r",|\+| and | with |&", it.target) if p.strip()]
    held_ids = {world.catalog.resolve(n) for n in names}
    if parts and all(world.catalog.resolve(p) and c.inventory.get(world.catalog.resolve(p), 0) > 0 for p in parts):
        names += [p for p in parts if world.catalog.resolve(p) not in held_ids]
    elif it.target:
        hint = it.target
    if not names:
        return ActionResult(False, "Combine what? List the items you want to put together.")
    ids, missing = set(), []
    for n in names:
        iid, err = _resolve_held(world, c, n)
        if iid:
            ids.add(iid)
        else:
            missing.append(err)
    if not ids:
        return ActionResult(False, missing[0] if missing else "You have none of those.")
    r = choose_recipe(world, c, ids, hint)
    if r is not None and missing:
        res = _try_recipe(world, c, r, it.count if it.count > 1 else 1, "combine")
        return ActionResult(res.ok, f"{missing[0]} So you try with what you have. {res.message}", res.instant)
    if r is None:
        c.stats["failed_combos"] += 1
        names_txt = ", ".join(world.catalog.name(i) for i in sorted(ids))
        wanted = world.catalog.resolve(hint) if hint else None
        known = world.catalog.recipe_for(wanted) if wanted and wanted in c.known_recipes else None
        if known:
            return ActionResult(False, f"You know how to make {world.catalog.name(wanted)}: {world.catalog.describe_recipe(known)}.")
        lacking = f" ({missing[0].rstrip('.')}.)" if missing else ""
        if world.catalog.near_miss(ids):
            return ActionResult(False, f"You turn the {names_txt} over in your hands. They feel like part of something, but one more ingredient seems to be missing.{lacking}")
        return ActionResult(False, f"You fiddle with the {names_txt}, but nothing comes of it.{lacking}")
    return _try_recipe(world, c, r, it.count if it.count > 1 else 1, "combine")


def _craft(world: World, c: Creature, it: Intention) -> ActionResult:
    name = it.target or (it.items[0] if it.items else "")
    iid = world.catalog.resolve(name)
    if not iid:
        return ActionResult(False, f"You've never heard of a '{name}'. Try combining materials to discover new things.")
    r = world.catalog.recipe_for(iid)
    if r is None:
        return ActionResult(False, f"{world.catalog.name(iid).capitalize()} isn't something you make; it's found or gathered.")
    if iid not in c.known_recipes:
        return ActionResult(False, f"You don't know how to make {world.catalog.name(iid)} yet. Try combining materials to discover it, or ask someone who knows.")
    return _try_recipe(world, c, r, it.count, "craft")


def _eat(world: World, c: Creature, it: Intention) -> ActionResult:
    name = it.target or (it.items[0] if it.items else "")
    if not name:
        foods = [i for i in c.inventory if world.catalog.items[i].food > 0]
        if not foods:
            return ActionResult(False, "You have nothing to eat.")
        name = foods[0]
    iid = world.catalog.resolve(name)
    if iid is None and any(w in ("chicken", "cow", "sheep", "hen", "lamb", "animal") for w in _words(name)):
        return ActionResult(False, "You can't eat a live animal. But an animal that trusts you (feed it twice) gives eggs, milk or wool.")
    if (iid in (None, "berries")) and c.inventory.get("berries", 0) <= 0 and any(w in _words(name) for w in ("berry", "berries", "bush")):
        bush = find_object(world, c, "berry bush", kinds={"bush"})
        if bush is None:
            return ActionResult(False, "You have no berries, and there's no berry bush with fruit in sight.")
        if dist(c.x, c.y, bush.x, bush.y) > 1:
            return _walk_then(world, c, bush, it)
        bush.data["berries"] = bush.data.get("berries", 6) - 1
        if bush.data["berries"] <= 0:
            world.change_kind(bush, "bush_empty")
            bush.data["regrow_at"] = world.tick + 400
        c.inventory["berries"] += 1
        iid = "berries"
    iid, err = _resolve_held(world, c, name if iid is None else world.catalog.name(iid))
    if not iid:
        return ActionResult(False, err)
    food = world.catalog.items[iid].food
    if food <= 0:
        return ActionResult(False, f"You can't eat {world.catalog.name(iid)}.")
    want = it.count if it.count > 1 else max(1, int((85 - c.satiety) // food) + 1)  # eat until satisfied
    n = max(1, min(want, c.inventory[iid], 6))
    c.inventory[iid] -= n
    if c.inventory[iid] <= 0:
        del c.inventory[iid]
    c.satiety = min(100.0, c.satiety + food * n)
    world.emit("eat", c.id, c.x, c.y, f"{c.name} ate {n} {world.catalog.name(iid)}.")
    feel = "You feel full." if c.satiety > 85 else ("You feel better." if c.satiety > 50 else "You are still hungry.")
    return ActionResult(True, f"You eat {n} {world.catalog.name(iid)}. {feel}")


def _drink(world: World, c: Creature, it: Intention) -> ActionResult:
    if _nearest_tile(world, c, "wW", 1) is None:
        return ActionResult(False, "There's no water within reach. Walk to the water first.")
    c.energy = min(100.0, c.energy + 10)
    return ActionResult(True, "You drink cool water and feel refreshed.")


def _say(world: World, c: Creature, it: Intention) -> ActionResult:
    text = it.text.strip().strip('"')[:300]
    if not text:
        return ActionResult(False, "You open your mouth but have nothing to say. (Put your words in text.)")
    to = find_creature(world, c, it.target) if it.target else None
    c.say = text
    c.say_until = world.tick + 10
    c.stats["speech"] += 1
    shown = f'{c.name} to {to.name}: "{text}"' if to else f'{c.name}: "{text}"'
    world.emit("say", c.id, c.x, c.y, shown, speaker=c.name, to=to.id if to else None, to_name=to.name if to else None, line=text)
    if to and to.asleep:
        return ActionResult(True, f'You say to {to.name}: "{text}" But {to.name} is fast asleep and doesn\'t hear you.')
    return ActionResult(True, f'You say{" to " + to.name if to else ""}: "{text}"')


def _feed_animal(world: World, c: Creature, animal: WorldObject, it: Intention) -> ActionResult:
    if dist(c.x, c.y, animal.x, animal.y) > 1:
        return _walk_then(world, c, animal, it)
    name = it.items[0] if it.items else it.text
    iid, err = _resolve_held(world, c, name) if name else (None, "Feed it what? Put the food in items.")
    if not iid:
        return ActionResult(False, err)
    if iid not in ANIMAL_FOOD:
        return ActionResult(False, f"The {animal.name} sniffs the {world.catalog.name(iid)} and turns away.")
    c.inventory[iid] -= 1
    if c.inventory[iid] <= 0:
        del c.inventory[iid]
    fed = animal.data.get("fed", 0) + 1
    animal.data["fed"] = fed
    if animal.data.get("tamed_by"):
        return ActionResult(True, f"The {animal.name} eats happily from your hand. It already belongs to {animal.data['tamed_by']}.")
    if fed >= 2:
        animal.data.update(tamed_by=c.name, home=[animal.x, animal.y], ready_at=world.tick + 120)
        animal.data["label"] = f"{c.name}'s {animal.kind}"
        world.changed_objects.add(animal.id)
        c.stats["tamed"] += 1
        world.emit("tame", c.id, animal.x, animal.y, f"{c.name} tamed a {animal.kind}!", animal=animal.kind)
        gift = {"chicken": "It will lay eggs you can gather.", "cow": "You can gather milk from it.",
                "sheep": "You can shear its wool with a knife."}[animal.kind]
        return ActionResult(True, f"The {animal.kind} trusts you now and stays near this spot. {gift}")
    return ActionResult(True, f"The {animal.name} eats warily from your hand. Maybe it will trust you if you feed it again.")


def _give(world: World, c: Creature, it: Intention) -> ActionResult:
    other = find_creature(world, c, it.target)
    if not other:
        animal = find_object(world, c, it.target, kinds=ANIMALS) if it.target else None
        if animal:
            return _feed_animal(world, c, animal, it)
        return ActionResult(False, f"You don't see '{it.target}' here to give anything to.")
    if dist(c.x, c.y, other.x, other.y) > 1:
        res = start_walk(world, c, _adjacent_goals(world, other.x, other.y), f"walking to {other.name}", f"You reach {other.name}.")
        if c.activity:
            c.activity["then"] = it
        return res
    name = it.items[0] if it.items else it.text
    if not name:
        return ActionResult(False, "Give what? Put the item in items.")
    iid, err = _resolve_held(world, c, name)
    if not iid:
        return ActionResult(False, err)
    n = min(it.count, c.inventory[iid])
    c.inventory[iid] -= n
    if c.inventory[iid] <= 0:
        del c.inventory[iid]
    other.inventory[iid] += n
    c.stats["gifts"] += 1
    world.emit("give", c.id, c.x, c.y, f"{c.name} gave {n} {world.catalog.name(iid)} to {other.name}.",
               to=other.id, giver=c.name, item=iid, n=n)
    return ActionResult(True, f"You give {n} {world.catalog.name(iid)} to {other.name}.")


def _pick_up(world: World, c: Creature, it: Intention) -> ActionResult:
    name = it.target or (it.items[0] if it.items else "")
    iid = world.catalog.resolve(name) if name else None
    for dx in (0, -1, 1):
        for dy in (0, -1, 1):
            pile = world.ground.get((c.x + dx, c.y + dy))
            if not pile:
                continue
            taken: Counter = Counter()
            for item in list(pile):
                if iid is None or item == iid:
                    got = world.take_items(c.x + dx, c.y + dy, item, 20)
                    taken[item] += got
            if taken:
                c.inventory.update(taken)
                return ActionResult(True, f"You pick up {_items_text(world, taken)}.")
    return ActionResult(False, "There's nothing like that on the ground within reach.")


def _drop(world: World, c: Creature, it: Intention) -> ActionResult:
    name = it.target or (it.items[0] if it.items else "")
    iid, err = _resolve_held(world, c, name)
    if not iid:
        return ActionResult(False, err)
    n = min(max(it.count, 1), c.inventory[iid])
    c.inventory[iid] -= n
    if c.inventory[iid] <= 0:
        del c.inventory[iid]
    world.drop_items(c.x, c.y, Counter({iid: n}))
    return ActionResult(True, f"You put down {n} {world.catalog.name(iid)}.")


def _place(world: World, c: Creature, it: Intention) -> ActionResult:
    name = it.target or (it.items[0] if it.items else "")
    words = _words(name + " " + it.text)
    hint, _ = _dir_hint(words)
    iid = None
    for cand in (name, " ".join(w for w in _words(name) if w not in DIRS)):
        iid = world.catalog.resolve(cand)
        if iid:
            break
    if not iid:
        return ActionResult(False, f"You don't know of anything called '{name}' to place.")
    if c.inventory.get(iid, 0) <= 0:
        return ActionResult(False, f"You don't have a {world.catalog.name(iid)} to place.")
    if not world.catalog.items[iid].placeable:
        return ActionResult(False, f"A {world.catalog.name(iid)} isn't something you can set down as a structure. Try drop.")
    spots = []
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            if not (dx or dy):
                continue
            x, y = c.x + dx, c.y + dy
            if world.walkable(x, y) and not world.object_at(x, y) and not world.occupied(x, y) and world.tile(x, y) not in "wW":
                spots.append((0 if hint and direction(dx, dy) == hint else 1, x, y))
    if not spots:
        return ActionResult(False, "There's no free spot beside you to place that.")
    spots.sort()
    _, x, y = spots[0]
    c.inventory[iid] -= 1
    if c.inventory[iid] <= 0:
        del c.inventory[iid]
    kind = {"wooden_wall": "wall"}.get(iid, iid)
    if "invention" in world.catalog.items[iid].tags:
        kind = "creation"
    data: dict = {"builder": c.name}
    if kind == "creation":
        inv = next((v for v in getattr(world.catalog, "inventions", []) if v["id"] == iid), {})
        data.update(label=world.catalog.name(iid), item=iid, desc=world.catalog.items[iid].desc,
                    effects=list(inv.get("effects", [])))
        if "light" in data["effects"]:
            data["lit"] = True
    if kind == "campfire":
        data.update(lit=True, lit_until=world.tick + 1200)
    elif kind == "sign":
        data.update(text="")
    elif kind == "chest":
        data.update(items={})
    elif kind == "terminal":
        data.update(code="", screen=[f"A new terminal built by {c.name}.", "> READY: awaiting a Lua program", '> example:  say("hello")'], memory={})
    obj = world.add_object(kind, x, y, **data)
    c.stats["built"] += 1
    world.emit("place", c.id, x, y, f"{c.name} placed a {obj.name}.", object_kind=kind)
    return ActionResult(True, f"You set down the {obj.name} {direction(x - c.x, y - c.y)} of you.")


def _write(world: World, c: Creature, it: Intention) -> ActionResult:
    text = it.text.strip()[:400]
    if not text:
        return ActionResult(False, "Write what? Put the words in text.")
    surface = (find_object(world, c, it.target or "sign", max_dist=1, kinds={"sign"})
               or find_object(world, c, it.target, max_dist=1, kinds=CARVABLE)
               or find_object(world, c, "", max_dist=1, kinds={"sign"} | CARVABLE))
    if not surface:
        return ActionResult(False, "There's nothing beside you to write on. A sign, a tree trunk or a boulder would do.")
    if surface.kind == "sign":
        text = text[:400]
    else:
        text = text[:160]  # carving is slow work; keep it short
    surface.data["text"] = text
    surface.data["author"] = c.name
    world.changed_objects.add(surface.id)
    c.stats["writing"] += 1
    verb = "wrote on a sign" if surface.kind == "sign" else f"carved words into a {surface.name}"
    world.emit("write", c.id, surface.x, surface.y, f'{c.name} {verb}: "{text[:120]}"')
    return ActionResult(True, f'You carve into the {surface.name}: "{text}"')


def _read(world: World, c: Creature, it: Intention) -> ActionResult:
    readable = {"sign", "tablet", "terminal"}
    obj = find_object(world, c, it.target or "sign", max_dist=1, kinds=readable)
    if not obj:  # carvings on trees and boulders
        obj = next((o for o, d, _ in visible_objects(world, c, 1) if o.kind in CARVABLE and o.data.get("text")), None)
    if not obj:
        far = find_object(world, c, it.target or "sign", kinds=readable)
        if far is None:
            far = next((o for o, d, _ in visible_objects(world, c) if o.data.get("text") and o.kind in CARVABLE), None)
        if far:
            return _walk_then(world, c, far, it)
        return ActionResult(False, "There's nothing to read within reach.")
    if obj.kind == "terminal":
        screen = obj.data.get("screen") or ["(blank)"]
        code = obj.data.get("code") or ""
        msg = "The terminal's screen shows:\n" + "\n".join(screen[-12:])
        if code:
            msg += f"\nIts current program (by {obj.data.get('programmer', 'someone')}):\n{code[:600]}"
        return ActionResult(True, msg)
    text = obj.data.get("text") or ""
    if not text:
        return ActionResult(True, f"The {obj.name} is blank.")
    author = obj.data.get("author")
    msg = f"The {obj.name} reads{' (written by ' + author + ')' if author else ''}: \"{text}\""
    learned = [r for r in world.catalog.recipes_in_words(text) if r.output not in c.known_recipes]
    for r in learned:
        c.known_recipes.add(r.output)
        c.stats["learned_by_reading"] += 1
        world.emit("learn", c.id, c.x, c.y, f"{c.name} learned to make {world.catalog.name(r.output)} by reading {author or 'old writing'}'s words.",
                   teacher=next((o.id for o in world.creatures.values() if o.name == author), None), how="reading", item=r.output)
    if learned:
        msg += " Now you understand how to make " + ", ".join(world.catalog.name(r.output) for r in learned) + "."
    return ActionResult(True, msg)


def _program(world: World, c: Creature, it: Intention) -> ActionResult:
    code = it.text.strip()
    term = find_object(world, c, it.target or "terminal", max_dist=1, kinds={"terminal"})
    if not term:
        far = find_object(world, c, it.target or "terminal", kinds={"terminal"})
        if far and code:
            return _walk_then(world, c, far, it)
        return ActionResult(False, "There's no terminal within reach to program.")
    if not code:
        return ActionResult(False, 'The terminal blinks, waiting. Its screen says it wants a Lua program, written in text. '
                                   'For example: say("hello")  or  for _,t in ipairs(scan(5)) do print(t.name) end')
    term.data["code"] = code[:2000]
    term.data["programmer"] = c.name
    term.data["programmer_id"] = c.id
    term.data["screen"] = [f"> program loaded by {c.name}"]
    term.data["next_run"] = world.tick + 1
    c.stats["programs"] += 1
    world.emit("program", c.id, term.x, term.y, f"{c.name} programmed a terminal:\n{code[:300]}")
    return ActionResult(True, "You enter your program into the terminal. It will run shortly; read the terminal to see its screen.")


def _plant(world: World, c: Creature, it: Intention) -> ActionResult:
    name = it.target or (it.items[0] if it.items else "seeds")
    if _words(name) and _words(name)[-1] in ("seeds", "seed") and world.catalog.resolve(name) is None:
        held = [i for i in ("wheat_seeds", "carrot_seeds") if c.inventory.get(i, 0) > 0]
        if held:
            name = held[0]
    iid, err = _resolve_held(world, c, name)
    if not iid:
        return ActionResult(False, err)
    if iid not in ("wheat_seeds", "carrot_seeds", "berries"):
        return ActionResult(False, f"{world.catalog.name(iid).capitalize()} won't grow if you plant it.")
    if not _has_tool(c, ("hoe",)):
        return ActionResult(False, "The ground is too hard to plant in with bare hands. You'd need a tool to break the soil.")
    planted = 0
    for _ in range(min(it.count, c.inventory[iid])):
        spot = next(((x, y) for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                     for x, y in [(c.x + dx, c.y + dy)]
                     if (dx or dy) and world.tile(x, y) in "gdf" and not world.object_at(x, y)
                     and not world.occupied(x, y)), None)
        if not spot:
            break
        if iid in ("wheat_seeds", "carrot_seeds"):
            crop = iid.replace("_seeds", "")
            world.add_object("crop", *spot, crop=crop, stage=0, grow_at=world.tick + 300, label=f"{crop} sprouts", planter=c.name)
        else:
            world.add_object("sapling", *spot, grow_at=world.tick + 900, label="berry sapling", planter=c.name)
        c.inventory[iid] -= 1
        planted += 1
    if c.inventory.get(iid, 0) <= 0:
        c.inventory.pop(iid, None)
    if not planted:
        return ActionResult(False, "There's no free soil beside you to plant in.")
    c.stats["planted"] += planted
    what = world.catalog.name(iid) if iid != "berries" else "berry seeds"
    world.emit("plant", c.id, c.x, c.y, f"{c.name} planted {planted} {what}.")
    grows = "In time they sprout, grow and ripen for harvest." if iid != "berries" else "In time a new berry bush will grow."
    return ActionResult(True, f"You plant {planted} {what} in the soil. {grows}")


INVENT_STATIONS = ("workbench", "campfire")
TOOL_WORDS = ("hammer", "tool", "axe", "knife", "spear", "saw", "shovel", "spade", "chisel", "pick", "club",
              "blade", "scraper", "drill", "needle", "hook", "trap", "sling", "bow", "net", "basket", "bag", "sickle", "rake")


TOOL_PURPOSE = re.compile(r"\b(for|to|helps?|used to|good for)\s+(gather|gathering|cut|cutting|chop|chopping|dig|digging|mine|mining|"
                          r"carry|carrying|catch|catching|hunt|hunting|fish|fishing|scrape|scraping|break|breaking|smash|smashing|"
                          r"split|splitting|harvest|harvesting|collect|collecting|pick|picking|crush|crushing|grind|grinding)\b")


def is_toolish(text: str) -> bool:
    t = text.lower()
    return any(re.search(rf"\b{w}s?\b", t) for w in TOOL_WORDS) or bool(TOOL_PURPOSE.search(t))
NAME_RE = re.compile(r"^[a-z][a-z \-']{2,29}$")


def _invent(world: World, c: Creature, it: Intention) -> ActionResult:
    """Rung 1 of world-building: a creature defines a brand-new item (data only, never code)."""
    cat = world.catalog
    station = next((s_ for s_ in INVENT_STATIONS if station_near(world, c, s_)), None)  # recorded if present
    name = " ".join(it.target.lower().split())
    if not NAME_RE.match(name or ""):
        return ActionResult(False, "Name your invention in target with a short plain name, like 'berry cake' or 'stone bench'.")
    if cat.resolve(name):
        return ActionResult(False, f"'{name}' already exists. Try combining things to make it, or invent something new.")
    used_today = c.stats.get(f"invented_day_{world.clock()['day']}", 0)
    if used_today >= 1:
        return ActionResult(False, "You've already invented something today. Let the idea rest until tomorrow.")
    inputs: Counter = Counter()
    for n in it.items:
        iid, err = _resolve_held(world, c, n)
        if not iid:
            return ActionResult(False, err)
        inputs[iid] += 1
    if not 2 <= len(inputs) <= 4:
        return ActionResult(False, "An invention needs 2 to 4 different things you carry, listed in items.")
    if cat.match_combination(set(inputs)):
        return ActionResult(False, "Those things already combine into something known. Try combine instead.")
    depth = 1 + max((next((v.get("depth", 1) for v in getattr(cat, "inventions", []) if v["id"] == i), 1)
                     for i in inputs if "invention" in cat.items[i].tags), default=0)
    if depth > 3:
        return ActionResult(False, "That idea builds on too many other inventions at once; it's beyond you for now.")
    for iid in inputs:  # use up to 2 of each, at least 3 items in total
        inputs[iid] = min(2, c.inventory[iid])
    if sum(inputs.values()) < 3:
        return ActionResult(False, "You'd need a bit more material for something new: at least 3 items in all.")
    if world.catalog.match_combination(set(inputs)):
        return ActionResult(False, "Those things already combine into something known. Try combine instead.")
    desc = it.text.strip()[:140] or f"Something {c.name} invented."
    edible_words = ("eat", "food", "meal", "snack", "cake", "pie", "stew", "soup", "bread", "tasty", "filling")
    food_in = sum(cat.items[i].food * n for i, n in inputs.items())
    food = int(food_in * 1.4) if food_in and any(w in (name + " " + desc).lower() for w in edible_words) else 0
    tool = not food and is_toolish(name + " " + desc)
    iid = "inv_" + re.sub(r"[^a-z]+", "_", name).strip("_")
    effects = invention_effects(name + " " + desc) if food == 0 else []
    if "light" in effects or "shelter" in effects:
        tool = False  # a torch or a tent is set down, not swung
    inv = {"id": iid, "name": name, "desc": desc, "food": food, "placeable": food == 0 and not tool, "tool": tool,
           "depth": depth, "effects": effects,
           "inputs": dict(inputs), "station": station, "by": c.name, "model": c.model, "tick": world.tick}
    cat.add_invention(inv)
    for i, n in inputs.items():
        c.inventory[i] -= n
        if c.inventory[i] <= 0:
            del c.inventory[i]
    c.inventory[iid] += 1
    c.known_recipes.add(iid)
    c.stats[f"invented_day_{world.clock()['day']}"] += 1
    c.stats["inventions"] += 1
    world.discoveries[iid] = {"item": iid, "by": c.name, "by_id": c.id, "model": c.model, "tick": world.tick, "invented": True}
    recipe = cat.describe_recipe(cat.recipe_for(iid))
    world.emit("invent", c.id, c.x, c.y, f'{c.name} invented the {name}! "{desc}" ({recipe})', item=iid)
    kind = "food" if food else ("a tool: carrying it makes your gathering more fruitful" if tool else "something you can place")
    if "shelter" in effects:
        kind += "; resting beside it restores you like a bed"
    if "light" in effects:
        kind += "; once placed it lights up the night"
    return ActionResult(True, f"You invent the {name}: {desc} It is {kind}. Recipe: {recipe}. Others can learn it if you share how.")


def _rest(world: World, c: Creature, it: Intention) -> ActionResult:
    if station_near(world, c, "bed"):
        return _busy(c, 10 * it.count, "resting in bed", "You rest in the bed and feel restored.", rest=True, bed=True)
    return _busy(c, 10 * it.count, "resting", "You rest for a while.", rest=True)


def _wait(world: World, c: Creature, it: Intention) -> ActionResult:
    return _busy(c, 6 * it.count, "waiting and watching", "You wait and watch for a while.")


HANDLERS = {
    "walk_to": _walk_to, "explore": _explore, "gather": _gather, "combine": _combine, "craft": _craft,
    "eat": _eat, "drink": _drink, "say": _say, "give": _give, "pick_up": _pick_up, "drop": _drop,
    "place": _place, "write": _write, "read": _read, "program": _program, "rest": _rest, "wait": _wait,
    "plant": _plant, "invent": _invent,
}


def apply_intention(world: World, c: Creature, it: Intention) -> ActionResult:
    if c.collapsed:
        return ActionResult(False, "You are lying on the ground, too weak to move.")
    c.activity = None
    try:
        res = HANDLERS[it.action](world, c, it)
    except Exception as exc:  # never let one bad intention break the world
        res = ActionResult(False, f"Something went wrong as you tried that ({type(exc).__name__}).")
    if not res.ok:
        world.emit("fail", c.id, c.x, c.y, f"{c.name} tried to {it.summary()}: {res.message}")
    return res


def step_activity(world: World, c: Creature) -> ActionResult | None:
    act = c.activity
    if not act or c.collapsed:
        return None
    if act["type"] == "walk":
        if not act["path"]:
            c.activity = None
            return ActionResult(True, act["result"])
        if c.energy < 15:  # exhausted: every other step is a stumble
            act["stumble"] = not act.get("stumble")
            if act["stumble"]:
                return None
        nx, ny = act["path"][0]
        if not world.walkable(nx, ny):
            c.activity = None
            return ActionResult(False, "Something blocks your way, so you stop.")
        if world.occupied(nx, ny, ignore=c.id):
            act["waits"] = act.get("waits", 0) + 1
            goal = act["path"][-1]
            if len(act["path"]) == 1:  # someone is standing where you meant to stop: this is close enough
                c.activity = None
                return ActionResult(True, f"{act['result']} (Someone was standing in your spot, so you stopped beside them.)")
            if act["waits"] >= 2:
                detour = bfs_path(world, (c.x, c.y), {goal}, avoid=occupied_tiles(world, c.id))
                if detour:
                    act["path"], act["waits"] = detour, 0
                elif act["waits"] >= 6:
                    c.activity = None
                    return ActionResult(False, "Others are crowding the way, so you stop.")
            return None
        act["path"].pop(0)
        c.x, c.y = nx, ny
        c.energy = max(0.0, c.energy - 0.05)
        if not act["path"]:
            c.activity = None
            if act.get("say"):
                to, text = act["say"]
                said = _say(world, c, Intention("say", target=to, text=text))
                return ActionResult(True, f"{act['result']} {said.message}")
            if act.get("then"):
                then = apply_intention(world, c, act["then"])
                if c.activity:  # e.g. gathering takes a few ticks; report when it's done
                    c.activity["result"] = f"{act['result']} {c.activity['result']}"
                    return None
                return ActionResult(then.ok, f"{act['result']} {then.message}")
            return ActionResult(True, act["result"])
        return None
    if act["type"] == "busy":
        act["ticks"] -= 1
        if act.get("rest"):
            c.energy = min(100.0, c.energy + (5 if act.get("bed") else 2))
        if act["ticks"] <= 0:
            c.activity = None
            return ActionResult(True, act["result"])
        return None
    c.activity = None
    return None
