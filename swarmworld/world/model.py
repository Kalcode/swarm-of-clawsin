"""Core world state: tiles, objects, creatures and the clock."""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass, field

from .catalog import Catalog
from .events import Event

TICK_SECONDS = 0.5
DAY_TICKS = 1200
START_TICK = int(DAY_TICKS * 0.12)

# Tiles: g grass, d dirt, s sand, w shallow water (wadeable), W deep water, r rocky ground, f forest floor
TILE_NAMES = {
    "g": "grass", "d": "dirt", "s": "sand", "w": "shallow water",
    "W": "deep water", "r": "rocky ground", "f": "forest floor",
}
BLOCKING = {
    "tree", "pine", "rock", "copper_vein", "iron_vein", "wall",
    "workbench", "furnace", "chest", "terminal", "campfire", "millstone", "bed",
}
OBJECT_NAMES = {
    "tree": "oak tree", "pine": "pine tree", "stump": "tree stump", "bush": "berry bush",
    "bush_empty": "picked-over bush", "rock": "boulder", "copper_vein": "green-streaked rock",
    "iron_vein": "rust-streaked rock", "clay": "clay bank", "campfire": "campfire",
    "workbench": "workbench", "furnace": "furnace", "wall": "wooden wall", "sign": "sign",
    "chest": "chest", "terminal": "strange terminal", "tablet": "stone tablet",
    "crop": "wheat", "sapling": "berry sapling", "millstone": "millstone", "bed": "bed", "door": "door",
    "chicken": "chicken", "sheep": "sheep", "cow": "cow", "creation": "creation",
}
ANIMALS = {"chicken", "sheep", "cow"}
# Words a creature might use for an object kind (besides its display name).
OBJECT_ALIASES = {
    "tree": ["tree", "oak", "oak tree", "trees"],
    "pine": ["tree", "pine", "pine tree", "trees"],
    "stump": ["stump", "tree stump"],
    "bush": ["bush", "berry bush", "berries", "berry", "bushes"],
    "bush_empty": ["bush", "empty bush"],
    "rock": ["rock", "boulder", "stone", "rocks", "boulders"],
    "copper_vein": ["copper", "copper vein", "green rock", "ore", "vein", "copper ore"],
    "iron_vein": ["iron", "iron vein", "rust rock", "ore", "vein", "iron ore"],
    "clay": ["clay", "clay bank", "mud"],
    "campfire": ["campfire", "fire", "camp fire"],
    "workbench": ["workbench", "bench", "work bench", "crafting table"],
    "furnace": ["furnace", "forge", "smelter"],
    "wall": ["wall", "wooden wall"],
    "sign": ["sign", "signpost"],
    "chest": ["chest", "box"],
    "terminal": ["terminal", "computer", "machine", "strange terminal"],
    "tablet": ["tablet", "stone tablet", "inscription"],
    "crop": ["wheat", "crop", "crops", "field", "wheat field", "ripe wheat", "wheat sprouts", "growing wheat",
             "carrot", "carrots", "ripe carrot", "carrot sprouts", "growing carrot", "carrot field"],
    "sapling": ["sapling", "berry sapling", "seedling"],
    "millstone": ["millstone", "mill", "quern"],
    "bed": ["bed"],
    "door": ["door", "gate"],
    "chicken": ["chicken", "chickens", "hen", "bird", "animal"],
    "sheep": ["sheep", "lamb", "animal"],
    "cow": ["cow", "cows", "cattle", "animal"],
}


@dataclass
class WorldObject:
    id: str
    kind: str
    x: int
    y: int
    data: dict = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.data.get("label") or OBJECT_NAMES.get(self.kind, self.kind.replace("_", " "))


@dataclass
class Creature:
    id: str
    name: str
    x: int
    y: int
    model: str = "unknown"
    color: str = "#e0c068"
    persona: dict = field(default_factory=dict)
    inventory: Counter = field(default_factory=Counter)
    satiety: float = 80.0
    energy: float = 100.0
    health: float = 100.0
    activity: dict | None = None
    asleep: bool = True
    node_id: str | None = None
    last_think_tick: int = -999
    thinking: bool = False
    wake_reason: str | None = "woke"
    say: str | None = None
    say_until: int = 0
    collapsed_until: int = 0
    known_recipes: set = field(default_factory=set)
    seen: dict = field(default_factory=dict)
    seen_pos: dict = field(default_factory=dict)  # lowercase name -> (x, y, tick) where last seen
    stats: Counter = field(default_factory=Counter)

    @property
    def collapsed(self) -> bool:
        return self.collapsed_until > 0


class World:
    def __init__(self, width: int, height: int, tiles: list[list[str]], catalog: Catalog, seed: int = 0):
        self.width = width
        self.height = height
        self.tiles = tiles
        self.catalog = catalog.copy()
        self.rng = random.Random(seed + 1)
        self.objects: dict[str, WorldObject] = {}
        self.grid: dict[tuple[int, int], str] = {}
        self.ground: dict[tuple[int, int], Counter] = {}
        self.creatures: dict[str, Creature] = {}
        self.tick = START_TICK
        self.events: list[Event] = []
        self.discoveries: dict[str, dict] = {}
        self.center = (width // 2, height // 2)
        self._next_id = 0
        self.changed_objects: set[str] = set()
        self.removed_objects: set[str] = set()

    # --- ids / objects -------------------------------------------------
    def new_id(self, prefix: str) -> str:
        self._next_id += 1
        return f"{prefix}{self._next_id}"

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    def tile(self, x: int, y: int) -> str:
        return self.tiles[y][x] if self.in_bounds(x, y) else "W"

    def object_at(self, x: int, y: int) -> WorldObject | None:
        oid = self.grid.get((x, y))
        return self.objects.get(oid) if oid else None

    def add_object(self, kind: str, x: int, y: int, **data) -> WorldObject:
        if (x, y) in self.grid:
            raise ValueError(f"tile {(x, y)} already has an object")
        obj = WorldObject(self.new_id("o"), kind, x, y, dict(data))
        self.objects[obj.id] = obj
        self.grid[(x, y)] = obj.id
        self.changed_objects.add(obj.id)
        return obj

    def change_kind(self, obj: WorldObject, kind: str) -> None:
        obj.kind = kind
        self.changed_objects.add(obj.id)

    def move_object(self, obj: WorldObject, x: int, y: int) -> bool:
        if (x, y) in self.grid or not self.walkable(x, y) or self.tile(x, y) in "wW":
            return False
        self.grid.pop((obj.x, obj.y), None)
        obj.x, obj.y = x, y
        self.grid[(x, y)] = obj.id
        self.changed_objects.add(obj.id)
        return True

    def remove_object(self, oid: str) -> None:
        obj = self.objects.pop(oid, None)
        if obj:
            self.grid.pop((obj.x, obj.y), None)
            self.removed_objects.add(oid)
            self.changed_objects.discard(oid)

    def walkable(self, x: int, y: int) -> bool:
        if not self.in_bounds(x, y) or self.tile(x, y) == "W":
            return False
        obj = self.object_at(x, y)
        return not (obj and (obj.kind in BLOCKING or obj.kind in ANIMALS))

    def occupied(self, x: int, y: int, ignore: str | None = None) -> bool:
        return any(c.x == x and c.y == y and c.id != ignore and not c.collapsed for c in self.creatures.values())

    # --- ground items ----------------------------------------------------
    def drop_items(self, x: int, y: int, items: Counter) -> None:
        pile = self.ground.setdefault((x, y), Counter())
        pile.update({k: v for k, v in items.items() if v > 0})
        self.changed_objects.add(f"pile:{x}:{y}")

    def take_items(self, x: int, y: int, item: str, n: int) -> int:
        pile = self.ground.get((x, y))
        if not pile or pile[item] <= 0:
            return 0
        got = min(n, pile[item])
        pile[item] -= got
        if pile[item] <= 0:
            del pile[item]
        key = f"pile:{x}:{y}"
        if not pile:
            del self.ground[(x, y)]
            self.removed_objects.add(key)
            self.changed_objects.discard(key)
        else:
            self.changed_objects.add(key)
        return got

    # --- time ----------------------------------------------------------
    def clock(self) -> dict:
        day = self.tick // DAY_TICKS + 1
        t = (self.tick % DAY_TICKS) / DAY_TICKS
        if t < 0.1:
            phase, light = "dawn", 0.35 + 6.5 * t
        elif t < 0.55:
            phase, light = "day", 1.0
        elif t < 0.65:
            phase, light = "dusk", 1.0 - 7.0 * (t - 0.55)
        else:
            phase, light = "night", 0.25
        return {"day": day, "phase": phase, "light": round(min(1.0, light), 2)}

    def time_text(self) -> str:
        c = self.clock()
        t = (self.tick % DAY_TICKS) / DAY_TICKS
        if c["phase"] == "day":
            part = "morning" if t < 0.3 else ("midday" if t < 0.42 else "afternoon")
        else:
            part = {"dawn": "dawn", "dusk": "dusk", "night": "night"}[c["phase"]]
        return f"Day {c['day']}, {part}"

    # --- spawning ------------------------------------------------------
    def spawn_point(self, radius: int = 6) -> tuple[int, int]:
        cx, cy = self.center
        for _ in range(500):
            x = cx + self.rng.randint(-radius, radius)
            y = cy + self.rng.randint(-radius, radius)
            if self.walkable(x, y) and not self.object_at(x, y) and not self.occupied(x, y):
                return x, y
        for r in range(radius, max(self.width, self.height)):
            for y in range(cy - r, cy + r + 1):
                for x in range(cx - r, cx + r + 1):
                    if self.walkable(x, y) and not self.object_at(x, y):
                        return x, y
        return cx, cy

    # --- serialization -------------------------------------------------
    def obj_dict(self, o: WorldObject) -> dict:
        d = {"id": o.id, "kind": o.kind, "x": o.x, "y": o.y, "label": o.name}
        if "lit" in o.data:
            d["lit"] = bool(o.data["lit"])
        if "stage" in o.data:
            d["stage"] = o.data["stage"]
        if o.data.get("crop"):
            d["crop"] = o.data["crop"]
        if o.data.get("tamed_by"):
            d["tamed_by"] = o.data["tamed_by"]
        if o.data.get("text"):
            d["text"] = o.data["text"][:200]
        if o.kind == "terminal" and o.data.get("screen"):
            d["text"] = "\n".join(o.data["screen"][-4:])[:200]
        return d

    def pile_dict(self, x: int, y: int) -> dict:
        pile = self.ground.get((x, y), Counter())
        label = ", ".join(f"{n} {self.catalog.name(i)}" for i, n in pile.items())
        return {"id": f"pile:{x}:{y}", "kind": "pile", "x": x, "y": y, "label": label}

    def cre_dict(self, c: Creature) -> dict:
        holding = None
        for tool in ("copper_pickaxe", "stone_pickaxe", "stone_axe", "stone_knife"):
            if c.inventory.get(tool):
                holding = tool
                break
        return {
            "id": c.id, "name": c.name, "x": c.x, "y": c.y, "model": c.model, "color": c.color,
            "activity": (c.activity or {}).get("label", "idle") if not c.collapsed else "collapsed",
            "thinking": c.thinking, "asleep": c.asleep,
            "say": c.say if c.say_until > self.tick else None,
            "satiety": round(c.satiety), "energy": round(c.energy), "health": round(c.health),
            "holding": holding,
        }

    def all_object_dicts(self) -> list[dict]:
        out = [self.obj_dict(o) for o in self.objects.values()]
        out += [self.pile_dict(x, y) for (x, y) in self.ground]
        return out

    def to_init(self) -> dict:
        return {
            "type": "init",
            "width": self.width,
            "height": self.height,
            "tiles": ["".join(row) for row in self.tiles],
            "objects": self.all_object_dicts(),
            "creatures": [self.cre_dict(c) for c in self.creatures.values()],
            "tick": self.tick,
            "clock": self.clock(),
            "items": {i: it.name for i, it in self.catalog.items.items()},
        }

    def take_object_changes(self) -> tuple[list[dict], list[str]]:
        upsert = []
        for oid in self.changed_objects:
            if oid.startswith("pile:"):
                _, x, y = oid.split(":")
                if (int(x), int(y)) in self.ground:
                    upsert.append(self.pile_dict(int(x), int(y)))
            elif oid in self.objects:
                upsert.append(self.obj_dict(self.objects[oid]))
        removed = list(self.removed_objects)
        self.changed_objects.clear()
        self.removed_objects.clear()
        return upsert, removed

    def emit(self, kind: str, actor: str | None, x: int, y: int, text: str, **data) -> Event:
        ev = Event(self.tick, kind, actor, x, y, text, data)
        self.events.append(ev)
        return ev
