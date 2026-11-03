"""Core world state: tiles, objects, creatures and the clock."""

from __future__ import annotations

import random
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field

from .catalog import Catalog
from .events import Event
# Object kinds live in swarmworld/data/objects.json and the packs' objects.json; these are the registry's shared tables.
from .registry import ANIMALS, BLOCKING, KINDS, OBJECT_ALIASES, OBJECT_NAMES, STORES  # noqa: F401

VIEW_KIND_FIELDS = ("look", "glyph", "glow")  # what the viewer's art reads from a kind's data, besides its name

TICK_SECONDS = 0.5
DAY_TICKS = 1200
START_TICK = int(DAY_TICKS * 0.12)

SOAKING = ("rain", "storm")  # weather that soaks whoever is out in it (a fire or a roof keeps it off)
WET = SOAKING + ("drizzle",)  # weather that wets the land: plants grow faster, insects shelter, a roof drums


def wet(world, drizzle: bool = False) -> bool:
    """Rain or a storm is falling (with drizzle=True, a drizzle counts too)."""
    return getattr(world, "weather", "clear") in (WET if drizzle else SOAKING)


# Tiles: g grass, d dirt, s sand, w shallow water (wadeable), W deep water, r rocky ground, f forest floor;
# underground: R rock wall, c cave floor, u cave water; dug: t trench floor, h pit bottom, O open pit (edge)
TILE_NAMES = {
    "g": "grass", "d": "dirt", "s": "sand", "w": "shallow water",
    "W": "deep water", "r": "rocky ground", "f": "forest floor",
    "R": "rock wall", "c": "cave floor", "u": "cave water", "t": "the floor of a trench",
    "h": "the bottom of a pit", "O": "the edge of an open pit",
}
SOLID_TILES = "RO"  # rock wall, open pit: nothing stands or moves here
WATER_TILES = "wWu"  # water: objects can't be moved onto it
REGION_GAP = 32  # rows of solid rock between regions: more than any sensing radius, so no distance check crosses one
LIGHT_ITEMS: dict[str, int] = {}  # carried item id -> steps it lets you see in the dark (packs add to it)


@dataclass(frozen=True)
class Region:
    """A band of rows of the one map (rows y0 <= y < y1): the surface, or a layer above or below it."""
    name: str
    level: int  # 0 the surface, negative below it
    y0: int
    y1: int
    sky: bool  # open to the sky: the time of day shows, and weather may fall
    weather: bool

    @property
    def height(self) -> int:
        return self.y1 - self.y0

    def to_dict(self) -> dict:
        return {"name": self.name, "level": self.level, "y0": self.y0, "y1": self.y1, "sky": self.sky,
                "weather": self.weather}


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
    last_noop: str = ""  # "action target" of the last turn that changed nothing
    spots: dict = field(default_factory=dict)  # object kind (or "water") -> (x, y, tick) of the nearest one last seen
    minds: list = field(default_factory=list)  # earlier models that thought for this body: {"model", "until"}
    stats_base: Counter = field(default_factory=Counter)  # stats earned before the current mind took over
    stats: Counter = field(default_factory=Counter)
    landmarks_seen: set = field(default_factory=set)  # names of landmarks it has been near
    last_recall: tuple[str, int, str] | None = None  # (query lowercased, tick, answer) of the last recall action
    harness: dict = field(default_factory=dict)  # layer -> decided on/off for this creature (the trial split)
    ext: dict = field(default_factory=dict)  # packs' state, by pack name: ext["play"]["joy"] (JSON-able; saved)

    @property
    def collapsed(self) -> bool:
        return self.collapsed_until > 0

    @property
    def sleeping(self) -> bool:
        """Asleep for the night (an activity), as opposed to `asleep`: in stasis because no brain is connected."""
        return bool(self.activity and self.activity.get("sleep"))


class World:
    def __init__(self, width: int, height: int, tiles: list[list[str]], catalog: Catalog, seed: int = 0):
        self.seed: int | None = seed
        self.regions: list[Region] = [Region("surface", 0, 0, height, True, True)]
        self.skylight: set[tuple[int, int]] = set()  # tiles of a sky-less region that are open to the sky
        self.changed_tiles: dict[tuple[int, int], str] = {}  # land changed since the last tick message (viewer)
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
        self._next_id = 0
        self.changed_objects: set[str] = set()
        self.removed_objects: set[str] = set()
        self.recall_hook: Callable[[Creature, str], list[tuple[str, str]]] | None = None  # set by the server: (creature, query) -> [(kind, text)]
        self.ext: dict = {}  # packs' world state, by pack name: ext["nature"]["rivers"] (JSON-able; saved)
        self.buildings_changed = False  # a building went up or came down since the last tick message (viewer)
        self.tiles_version = 0  # bumped by set_tile, so what is worked out from the land can be kept until it changes
        self.terminals: dict[str, None] = {}  # ids of the terminal objects, in the order they came (Simulation)

    @property
    def center(self) -> tuple[int, int]:
        s = self.region("surface")
        return self.width // 2, (s.y0 + s.y1) // 2

    # --- regions -------------------------------------------------------
    def region(self, name: str) -> Region | None:
        return next((r for r in self.regions if r.name == name), None)

    def region_at(self, x: int, y: int) -> Region | None:
        """The region holding row y (None in a band of rock between regions, or off the map)."""
        if not 0 <= x < self.width:
            return None
        return next((r for r in self.regions if r.y0 <= y < r.y1), None)

    def same_region(self, a: tuple[int, int], b: tuple[int, int]) -> bool:
        ra = self.region_at(*a)
        return ra is not None and ra is self.region_at(*b)

    def region_bounds(self, name: str = "surface") -> tuple[int, int, int, int]:
        """x0, y0, x1, y1 of a region, half-open."""
        r = self.region(name)
        return 0, r.y0, self.width, r.y1

    def view_rows(self, y: int, r: int) -> range:
        """Rows within r of y that lie in y's own region (empty when y is in no region)."""
        reg = self.region_at(0, y)
        if reg is None:
            return range(0)
        return range(max(y - r, reg.y0), min(y + r + 1, reg.y1))

    def _shifted(self, x: int, y: int, step: int) -> tuple[int, int] | None:
        here = self.region_at(x, y)
        there = here and next((r for r in self.regions if r.level == here.level + step), None)
        if not there or y - here.y0 >= there.height:
            return None
        return x, there.y0 + (y - here.y0)

    def above(self, x: int, y: int) -> tuple[int, int] | None:
        """The same column and row offset in the region one level up."""
        return self._shifted(x, y, 1)

    def below(self, x: int, y: int) -> tuple[int, int] | None:
        """The same column and row offset in the region one level down."""
        return self._shifted(x, y, -1)

    def under_sky(self, x: int, y: int) -> bool:
        r = self.region_at(x, y)
        return bool(r and (r.sky or (x, y) in self.skylight))

    def add_region(self, name: str, level: int, rows: list[list[str]], sky: bool, weather: bool,
                   gap: int = REGION_GAP) -> Region:
        """Add a region at the bottom of the map: `gap` rows of rock, then `rows`."""
        if self.region(name):
            raise ValueError(f"region {name!r} already exists")
        if any(len(row) != self.width for row in rows):
            raise ValueError(f"every row of region {name!r} must be {self.width} tiles wide")
        self.tiles.extend(["R"] * self.width for _ in range(gap))
        y0 = len(self.tiles)
        self.tiles.extend(list(row) for row in rows)
        self.height = len(self.tiles)
        region = Region(name, level, y0, self.height, sky, weather)
        self.regions.append(region)
        self.tiles_version += 1
        return region

    def take_tile_changes(self) -> list[list] | None:
        """[[x, y, tile], ...] changed since the last call, or None."""
        if not self.changed_tiles:
            return None
        out = [[x, y, t] for (x, y), t in self.changed_tiles.items()]
        self.changed_tiles.clear()
        return out

    # --- ids / objects -------------------------------------------------
    def new_id(self, prefix: str) -> str:
        self._next_id += 1
        return f"{prefix}{self._next_id}"

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    def tile(self, x: int, y: int) -> str:
        return self.tiles[y][x] if self.in_bounds(x, y) else "W"

    def set_tile(self, x: int, y: int, t: str) -> None:
        """Change the land at (x, y): use this rather than writing self.tiles, so cached views of the land update."""
        self.tiles[y][x] = t
        self.tiles_version += 1
        self.changed_tiles[(x, y)] = t

    def object_at(self, x: int, y: int) -> WorldObject | None:
        oid = self.grid.get((x, y))
        return self.objects.get(oid) if oid else None

    def add_object(self, kind: str, x: int, y: int, **data) -> WorldObject:
        if (x, y) in self.grid:
            raise ValueError(f"tile {(x, y)} already has an object")
        obj = WorldObject(self.new_id("o"), kind, x, y, dict(data))
        self.objects[obj.id] = obj
        self.grid[(x, y)] = obj.id
        self._index(obj)
        self.changed_objects.add(obj.id)
        return obj

    def _index(self, obj: WorldObject) -> None:
        if obj.kind == "terminal":
            self.terminals[obj.id] = None
        else:
            self.terminals.pop(obj.id, None)

    def reindex(self) -> None:
        """Rebuild the object indexes after objects were put in self.objects directly (a restored save)."""
        self.terminals = {}
        for obj in self.objects.values():
            self._index(obj)

    def change_kind(self, obj: WorldObject, kind: str) -> None:
        obj.kind = kind
        self._index(obj)
        self.changed_objects.add(obj.id)

    def move_object(self, obj: WorldObject, x: int, y: int) -> bool:
        if (x, y) in self.grid or not self.walkable(x, y) or self.tile(x, y) in WATER_TILES:
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
            self.terminals.pop(oid, None)
            self.removed_objects.add(oid)
            self.changed_objects.discard(oid)

    def walkable(self, x: int, y: int) -> bool:
        if not self.in_bounds(x, y):
            return False
        if self.tile(x, y) in SOLID_TILES:
            return False
        obj = self.object_at(x, y)
        if self.tile(x, y) == "W" and not (obj and KINDS.get(obj.kind, {}).get("over_water")):
            return False  # deep water, unless something to walk on spans it (a kind with "over_water": a bridge)
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
        weather = getattr(self, "weather", "clear")
        if wet(self):
            light *= 0.75
        elif weather in ("fog", "drizzle"):
            light *= 0.85
        return {"day": day, "phase": phase, "light": round(min(1.0, light), 2), "weather": weather}

    def time_text(self) -> str:
        return f"Day {self.clock()['day']}, {self.day_part()}"

    def day_part(self) -> str:
        """dawn, morning, midday, afternoon, dusk or night."""
        phase = self.clock()["phase"]
        if phase != "day":
            return phase
        t = (self.tick % DAY_TICKS) / DAY_TICKS
        return "morning" if t < 0.3 else ("midday" if t < 0.42 else "afternoon")

    # --- spawning ------------------------------------------------------
    def spawn_point(self, radius: int = 6) -> tuple[int, int]:
        cx, cy = self.center
        surface = self.region("surface")

        def free(x: int, y: int) -> bool:  # dry, open ground on the surface: nobody wakes in water
            return (surface.y0 <= y < surface.y1 and self.walkable(x, y) and self.tiles[y][x] not in WATER_TILES
                    and not self.object_at(x, y))

        for _ in range(500):
            x = cx + self.rng.randint(-radius, radius)
            y = cy + self.rng.randint(-radius, radius)
            if free(x, y) and not self.occupied(x, y):
                return x, y
        for r in range(radius, max(self.width, surface.height)):
            for y in range(cy - r, cy + r + 1):
                for x in range(cx - r, cx + r + 1):
                    if free(x, y):
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
        if o.kind in STORES:
            d["text"] = ", ".join(f"{n} {self.catalog.name(i)}" for i, n in (o.data.get("items") or {}).items()) or "empty"
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
        d = {
            "id": c.id, "name": c.name, "x": c.x, "y": c.y, "model": c.model, "color": c.color,
            "activity": (c.activity or {}).get("label", "idle") if not c.collapsed else "collapsed",
            "thinking": c.thinking, "asleep": c.asleep, "sleeping": c.sleeping,
            "say": c.say if c.say_until > self.tick else None,
            "satiety": round(c.satiety), "energy": round(c.energy), "health": round(c.health),
            "holding": holding,
        }
        light = max((n for item, n in LIGHT_ITEMS.items() if c.inventory.get(item)), default=0)
        if light:
            d["light"] = light
        return d

    def all_object_dicts(self) -> list[dict]:
        out = [self.obj_dict(o) for o in self.objects.values()]
        out += [self.pile_dict(x, y) for (x, y) in self.ground]
        return out

    def to_init(self) -> dict:
        init = {
            "type": "init",
            "width": self.width,
            "height": self.height,
            "tiles": ["".join(row) for row in self.tiles],
            "objects": self.all_object_dicts(),
            "creatures": [self.cre_dict(c) for c in self.creatures.values()],
            "regions": [r.to_dict() for r in self.regions],
            "tick": self.tick,
            "clock": self.clock(),
            "items": {i: it.name for i, it in self.catalog.items.items()},
            "landmarks": getattr(self, "landmarks", []),
            "buildings": self.building_dicts(),
            "kinds": {k: {"name": spec["name"], **{f: spec[f] for f in VIEW_KIND_FIELDS if spec.get(f)}}
                      for k, spec in KINDS.items()},
        }
        # the land's biomes and river flow (rows aligned with tiles; see terrain.py), for the viewer's art only
        land = {k: v for k, v in (self.ext.get("nature") or {}).items() if k in ("biomes", "flow") and v}
        if land:
            init["nature"] = land
        return init

    def building_dicts(self) -> list[dict]:
        """What creatures have built, for the viewer to draw floors and roofs (the building pack keeps it in
        ext["building"]["built"]): {"id", "design", "x0", "y0", "x1", "y1" (an inclusive rectangle of tiles),
        "door": [x, y] or None, "roof": bool}."""
        built = (self.ext.get("building") or {}).get("built") or {}
        return [{"id": bid, "design": b["design"], "x0": b["x0"], "y0": b["y0"], "x1": b["x1"], "y1": b["y1"],
                 "door": b.get("door"), "roof": bool(b.get("roof"))} for bid, b in built.items()]

    def take_building_changes(self) -> list[dict] | None:
        """Every building, if one went up or came down since the last call; otherwise None."""
        if not self.buildings_changed:
            return None
        self.buildings_changed = False
        return self.building_dicts()

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

    def sound(self, x: int, y: int, text: str, radius: int = 8, kind: str = "", loud: bool = False,
              source: str | None = None, makers: list[str] | None = None) -> Event:
        """Something makes a noise at (x, y), e.g. text "chopping". The simulation tells awake creatures within
        radius, except the source (a creature id, or the id of the thing that makes it, like a fire) and any other
        makers (creature ids: a crowd doesn't hear itself), "You hear chopping, about 6 steps north." Creatures
        asleep for the night only hear a loud sound, and it wakes them. kind names the sound for the viewer's audio
        (see registry.SOUND_KINDS). Every sound is logged and sent to viewers: make ambient ones sparingly."""
        extra = {"makers": list(makers)} if makers else {}
        return self.emit("sound", source, x, y, text, sound=kind, radius=radius, loud=loud, source=source, **extra)
