"""Plug-in points for content packs, so each pack adds to the world without editing the same core lists.

A pack is one module, swarmworld/world/packs/<pack>.py (its behaviour), plus data files in
swarmworld/data/packs/<pack>/ (items.json, recipes.json, objects.json, any of them). The data is merged after the
base files; the module is imported, sorted by name, when swarmworld.world.actions is first imported, and registers
what it adds:

    register_verb(name, handler, aliases)       a new action; handler(world, creature, intention) -> ActionResult
    register_technique(Technique(...))          how a verb is disclosed to creatures, and when it fits
    register_system(name, every, fn)            world behaviour: fn(simulation, tick) every `every` ticks
    register_perception(fn, priority)           an extra perception line: fn(world, creature) -> str | None
    register_populate(name, fn, land=fn)        place the pack's things: fn(world, rng, fresh) on a new or restored world;
                                                land(world, rng, bounds) fills one new land (the frontier)

A pack keeps its state in Creature.ext[<pack>] and World.ext[<pack>] (JSON-able; saved with the world). Callbacks
(systems, perception lines, triggers, populate) that raise are logged and skipped: one broken pack never stops the
world.

Object kinds come from swarmworld/data/objects.json and the packs' objects.json. Each kind is
{"name", "aliases", "blocking", "animal", "gatherable", "carvable", "store", "gives", "yields", "look"}; the tables
built from them (OBJECT_NAMES, BLOCKING, GATHERABLE...) are shared objects, re-exported by model.py and actions.py
and updated in place. A name registered twice (a verb, an alias, a kind, a technique, a system), and an item, recipe
or kind defined in two data files, raises ValueError naming both places. A word that is an alias of a core verb (as
"build" is of craft) becomes a pack's verb only with register_verb(..., replaces_alias=True).

Pack modules import, at their top, from swarmworld.world (actions, model, perception, catalog, events, registry,
terrain), but never swarmworld.world.simulation, swarmworld.mind or swarmworld.server: those import actions, and so
the packs, before they are done, so whichever is imported first would find the pack half-loaded. Import them under
TYPE_CHECKING or inside a function. tests/test_registry.py::test_packs_import_whichever_module_comes_first checks."""

from __future__ import annotations

import bisect
import importlib
import json
import logging
import pkgutil
import random
import re
import sys
import time
from collections.abc import Callable, Iterable
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .catalog import DATA, data_files, defined_twice

if TYPE_CHECKING:
    from .actions import ActionResult, Intention
    from .model import Creature, World
    from .simulation import Simulation

CORE_VERBS_MODULE = "swarmworld.world.actions"
PERCEPTION_LINES = 2  # extra perception lines a turn, from all packs together
log = logging.getLogger("swarmworld.packs")

# World.sound's kind: an advisory shared vocabulary, so the viewer's audio can match sounds from any pack.
# "animal:<kind>" means one per animal kind (animal:cow, animal:deer). Every sound is an event, logged and sent to
# viewers: emit ambient sounds from systems sparingly (cooldowns, a few at a time).
SOUND_KINDS = ("chop", "knock", "splash", "fire", "thunder", "rain", "river", "crickets", "bird", "animal:<kind>",
               "crowd", "footsteps", "build", "music", "dance", "hunt", "rustle")

# (what, name) -> the module or data file that registered it
_OWNERS: dict[tuple[str, object], str] = {}


def _caller() -> str:
    """The module that called the register_* function that called this."""
    return sys._getframe(2).f_globals.get("__name__", "?")


def owner(what: str, name: object) -> str | None:
    """Who registered a name: owner("verb", "gather") is "swarmworld.world.actions"; what is "verb" (verbs and their
    aliases), "object kind", "technique", "system" or "populate"."""
    return _OWNERS.get((what, name))


LOG_EVERY = 60.0  # seconds: how often the same failing callback is reported
_failed_at: dict[int, float] = {}


def call_safely(what: str, fn: Callable, *args, default=None):
    """Run a pack's callback. If it raises, log it (once a minute per callback, naming its module and function) and
    return default: a failing perception line or trigger counts as nothing, a failing system skips that tick."""
    try:
        return fn(*args)
    except Exception:
        now, last = time.monotonic(), _failed_at.get(id(fn))
        if last is None or now - last >= LOG_EVERY:
            _failed_at[id(fn)] = now
            log.error("%s %s.%s failed (reported at most once a minute)", what, getattr(fn, "__module__", "?"),
                      getattr(fn, "__qualname__", repr(fn)), exc_info=True)
        return default


def _check_free(what: str, key: object, source: str, shown: str | None = None, note: str = "") -> None:
    first = _OWNERS.get((what, key))
    if first is not None:
        raise ValueError(f"{what} '{shown or key}'{note} is registered twice: by {first} and by {source}")


# ------------------------------------------------------------------ object kinds
KINDS: dict[str, dict] = {}  # kind -> its full spec (extra fields a pack adds are kept, for its own code)

OBJECT_NAMES: dict[str, str] = {}
OBJECT_ALIASES: dict[str, list[str]] = {}  # only kinds that have aliases
BLOCKING: set[str] = set()
ANIMALS: set[str] = set()
GATHERABLE: set[str] = set()
CARVABLE: set[str] = set()
STORES: set[str] = set()
ITEM_SOURCES: dict[str, set[str]] = {}  # item -> the kinds that give it
SOURCE_PRODUCTS: dict[str, list[str]] = {}  # kind -> the items it gives, sorted
YIELDS: dict[str, dict] = {}  # kind -> its generic yields
DEPLETED: set[str] = set()  # what a kind with yields turns into while it regrows, when that has nothing to give
LOOKS: dict[str, str] = {}  # kind -> a hint for the viewer's art
TABLES = ("OBJECT_NAMES", "OBJECT_ALIASES", "BLOCKING", "ANIMALS", "GATHERABLE", "CARVABLE", "STORES",
          "ITEM_SOURCES", "SOURCE_PRODUCTS", "YIELDS", "DEPLETED", "LOOKS")


def _yields(kind: str, y: dict | None, where: str) -> dict | None:
    if y is None:
        return None
    try:
        items = {i: [int(lo), int(hi)] for i, (lo, hi) in (y.get("items") or {}).items()}
        out = {"items": items, "tool": y.get("tool"), "uses": int(y.get("uses", 1)), "becomes": y.get("becomes"),
               "regrow": None if y.get("regrow") is None else int(y["regrow"])}
    except (TypeError, ValueError) as exc:
        raise ValueError(f"kind '{kind}' in {where}: yields is {{\"items\": {{item: [min, max]}}, \"tool\": item or null, "
                         f"\"uses\": n, \"becomes\": kind or null, \"regrow\": ticks or null}} ({exc})") from None
    if not items or any(not 0 <= lo <= hi for lo, hi in items.values()):
        raise ValueError(f"kind '{kind}' in {where}: yields needs items, each with [min, max] amounts, 0 <= min <= max")
    if out["uses"] < 1 or (out["regrow"] is not None and out["regrow"] < 1) or not isinstance(out["tool"], str | None):
        raise ValueError(f"kind '{kind}' in {where}: yields needs uses >= 1, regrow (ticks) >= 1 or null, "
                         f"and tool an item id or null")
    return out


def normal_kind(kind: str, spec: dict, where: str = "?") -> dict:
    """A kind's spec with every field filled in. gatherable defaults to having yields; gives to what it yields."""
    if not re.fullmatch(r"[a-z][a-z0-9_]*", kind) or not isinstance(spec, dict) or not spec.get("name"):
        raise ValueError(f"kind '{kind}' in {where}: kinds are lower_snake_case and need a name")
    y = _yields(kind, spec.get("yields"), where)
    gives = spec.get("gives")
    return {**spec, "name": spec["name"], "aliases": list(spec.get("aliases") or []),
            "blocking": bool(spec.get("blocking")), "animal": bool(spec.get("animal")),
            "gatherable": bool(spec.get("gatherable", y is not None)), "carvable": bool(spec.get("carvable")),
            "store": bool(spec.get("store")), "gives": list(gives) if gives is not None else list(y["items"] if y else []),
            "yields": y, "look": spec.get("look")}


def build_tables(kinds: dict[str, dict]) -> dict[str, dict | set]:
    """The kind tables for a set of (normalized) kinds."""
    t: dict[str, dict | set] = {name: set() if name in ("BLOCKING", "ANIMALS", "GATHERABLE", "CARVABLE", "STORES",
                                                       "DEPLETED") else {} for name in TABLES}
    flags = {"BLOCKING": "blocking", "ANIMALS": "animal", "GATHERABLE": "gatherable", "CARVABLE": "carvable",
             "STORES": "store"}
    for kind, spec in kinds.items():
        t["OBJECT_NAMES"][kind] = spec["name"]
        if spec["aliases"]:
            t["OBJECT_ALIASES"][kind] = list(spec["aliases"])
        for table, flag in flags.items():
            if spec[flag]:
                t[table].add(kind)
        for item in spec["gives"]:
            t["ITEM_SOURCES"].setdefault(item, set()).add(kind)
        if spec["gives"]:
            t["SOURCE_PRODUCTS"][kind] = sorted(spec["gives"])
        if spec["yields"]:
            t["YIELDS"][kind] = spec["yields"]
        if spec["look"]:
            t["LOOKS"][kind] = spec["look"]
    for y in t["YIELDS"].values():
        if y["becomes"] and y["regrow"] and y["becomes"] not in t["GATHERABLE"]:
            t["DEPLETED"].add(y["becomes"])
    return t


def _rebuild() -> None:
    for name, value in build_tables(KINDS).items():
        table = globals()[name]
        table.clear()
        table.update(value)


def kind_files(data_dir: Path = DATA, packs: bool = True) -> list[tuple[str, dict]]:
    return [(source, json.loads(path.read_text())) for source, path in data_files("objects.json", data_dir, packs)]


def load_objects(data_dir: Path = DATA, packs: bool = True) -> dict[str, dict]:
    """Every kind in a data folder (objects.json, then the packs'), normalized; registers nothing."""
    kinds: dict[str, dict] = {}
    found_in: dict[str, str] = {}
    for source, raw in kind_files(data_dir, packs):
        for kind, spec in raw.items():
            if kind in found_in:
                raise defined_twice("object kind", kind, found_in[kind], source)
            found_in[kind] = source
            kinds[kind] = normal_kind(kind, spec, source)
    return kinds


def register_kinds(kinds: dict[str, dict], source: str | None = None) -> None:
    """Add object kinds (as in objects.json) to the world's tables. The world's own data files register at import."""
    source = source or _caller()
    for kind in kinds:
        _check_free("object kind", kind, source)
    normal = {kind: normal_kind(kind, spec, source) for kind, spec in kinds.items()}
    for kind, spec in normal.items():
        _OWNERS[("object kind", kind)] = source
        KINDS[kind] = spec
    _rebuild()


# ------------------------------------------------------------------ verbs
Handler = Callable[["World", "Creature", "Intention"], "ActionResult"]
VERBS: list[str] = []  # every action a mind may choose, in schema order: the core verbs, then the packs'
VERB_ALIASES: dict[str, str] = {}  # other words minds use -> the verb
ALIAS_TARGETS: dict[str, str] = {}  # an alias that also says where ("dig_down" -> "down"): the target it means
HANDLERS: dict[str, Handler] = {}
VERB_WORD = re.compile(r"[a-z][a-z0-9_]*")


def _register_verb(name: str, handler: Handler, aliases: tuple[str, ...], source: str, replaces_alias: bool,
                   alias_targets: dict[str, str] | None = None) -> None:
    aliases = (aliases,) if isinstance(aliases, str) else tuple(aliases)
    alias_targets = dict(alias_targets or {})
    if set(alias_targets) - set(aliases):
        raise ValueError(f"verb '{name}' from {source}: alias_targets names words that aren't its aliases: "
                         f"{sorted(set(alias_targets) - set(aliases))}")
    for word in (name, *aliases):
        if not VERB_WORD.fullmatch(word):
            raise ValueError(f"'{word}' (from {source}) isn't a verb word: lower_snake_case, like 'go_fishing'")
    core_alias = _OWNERS.get(("verb", name)) == CORE_VERBS_MODULE and name in VERB_ALIASES
    if core_alias and not replaces_alias:
        raise ValueError(f"verb '{name}' is registered twice: by {CORE_VERBS_MODULE} (an alias of "
                         f"'{VERB_ALIASES[name]}') and by {source}; pass replaces_alias=True to make it this verb")
    if not core_alias:
        _check_free("verb", name, source)
        if replaces_alias:
            raise ValueError(f"verb '{name}' from {source} has replaces_alias=True, but '{name}' isn't an alias "
                             f"of a core verb")
    for a in aliases:
        _check_free("verb", a, source, note=f" (an alias of '{name}')")
    if len(set(aliases) | {name}) != len(aliases) + 1:
        raise ValueError(f"verb '{name}' from {source} lists a word twice")
    if core_alias:
        del VERB_ALIASES[name]
    for word in (name, *aliases):
        _OWNERS[("verb", word)] = source
    VERBS.append(name)
    HANDLERS[name] = handler
    VERB_ALIASES.update({a: name for a in aliases})
    ALIAS_TARGETS.update(alias_targets)


def register_verb(name: str, handler: Handler, aliases: tuple[str, ...] = (), *, replaces_alias: bool = False,
                  alias_targets: dict[str, str] | None = None) -> None:
    """A new action, valid in every intention (it joins the schema's enum). Disclose it with a Technique: the system
    prompts only describe the core verbs. A name that is an alias of a core verb ("build" -> craft) needs
    replaces_alias=True; the word then means this verb, so hand the cases it doesn't cover to the core verb
    (HANDLERS["craft"]). alias_targets: aliases that also say where, {"dig_down": "down"}; an intention for one that
    names no target gets that one."""
    _register_verb(name, handler, aliases, _caller(), replaces_alias, alias_targets)


def pack_verbs() -> list[str]:
    """The verbs packs registered (not the core verbs of swarmworld.world.actions), in schema order."""
    return [v for v in VERBS if _OWNERS.get(("verb", v)) != CORE_VERBS_MODULE]


# ------------------------------------------------------------------ techniques
@dataclass
class Technique:
    """A verb (or a use of one) shown to a creature only when it fits: trigger scores how relevant it is now."""
    name: str
    line: str
    trigger: Callable[["World", "Creature"], float | None]  # higher is more relevant; None means not now
    verbs: tuple[str, ...] | None = None  # None means the verb is the name; () means a use of a core verb
    pack: bool = False  # a pack's (register_technique): shown to every creature, not only those with "disclose"

    def __post_init__(self):
        if self.verbs is None:
            self.verbs = (self.name,)


TECHNIQUES: list[Technique] = []  # the core techniques first (swarmworld.mind.techniques), then the packs'


def register_technique(t: Technique) -> None:
    """A pack's technique. Every creature is shown it when its trigger fits (the core techniques only reach creatures
    with the "disclose" harness layer, whose system prompt leaves their verbs out)."""
    source = _caller()
    _check_free("technique", t.name, source)
    _OWNERS[("technique", t.name)] = source
    t.pack = True
    TECHNIQUES.append(t)


def register_core_techniques(techniques: Iterable[Technique]) -> None:
    """For swarmworld.mind.techniques: the built-in techniques, kept ahead of the packs' whatever the import order."""
    source = _caller()
    techniques = list(techniques)
    for t in techniques:
        _check_free("technique", t.name, source)
        _OWNERS[("technique", t.name)] = source
    TECHNIQUES[:0] = techniques


# ------------------------------------------------------------------ systems
@dataclass(frozen=True)
class System:
    name: str
    every: int
    fn: Callable[["Simulation", int], None]


SYSTEMS: list[System] = []


def register_system(name: str, every: int, fn: Callable[["Simulation", int], None]) -> None:
    """World behaviour that runs on its own: the simulation calls fn(simulation, tick) on every tick divisible by
    `every`, after the world's own steps, in registration order. A system never chooses actions for creatures."""
    source = _caller()
    if not isinstance(every, int) or every < 1:
        raise ValueError(f"system '{name}' from {source}: every is a whole number of ticks, at least 1")
    _check_free("system", name, source)
    _OWNERS[("system", name)] = source
    SYSTEMS.append(System(name, every, fn))


# ------------------------------------------------------------------ perception
@dataclass(frozen=True)
class Perception:
    fn: Callable[["World", "Creature"], str | None]
    priority: int


PERCEPTIONS: list[Perception] = []  # lowest priority first; equal priorities in registration order


def register_perception(fn: Callable[["World", "Creature"], str | None], priority: int = 50) -> None:
    """An extra line for a creature's perception: fn(world, creature) returns one short sentence, or None. The rule:
    say something only when it's relevant right now or has changed (not the same line every turn). Lines appear just
    before "You carry"; all packs together get PERCEPTION_LINES a turn, so the best are kept: lower priority first
    (urgent things, like danger, below 50; ambience above), then the first registered. Once the lines are full the
    remaining functions aren't called that turn, so an "only when it changed" line isn't used up unseen."""
    source = _caller()
    _check_free("perception", id(fn), source, shown=getattr(fn, "__qualname__", repr(fn)))
    _OWNERS[("perception", id(fn))] = source
    bisect.insort(PERCEPTIONS, Perception(fn, priority), key=lambda p: p.priority)


def extra_perception(world: "World", c: "Creature") -> list[str]:
    lines: list[str] = []
    for p in PERCEPTIONS:
        if len(lines) >= PERCEPTION_LINES:
            break
        line = call_safely("perception line", p.fn, world, c)
        if line:
            lines.append(line)
    return lines


# ------------------------------------------------------------------ landmarks and handoffs
LANDMARK_SOURCES: list[Callable[["World"], list[dict]]] = []


def register_landmarks(fn: Callable[["World"], list[dict]]) -> None:
    """Named places a pack knows: fn(world) returns [{"name", "x", "y", "kind"}, ...], merged into world.landmarks each
    time the simulation works them out (every 60 ticks). Creatures hear of a place only in its own region, and know it
    once within LANDMARK_RANGE of it; with "by_sight": True, only once they have seen it (within their sight). A failing
    source is skipped."""
    source = _caller()
    _check_free("landmarks", id(fn), source, shown=getattr(fn, "__qualname__", repr(fn)))
    _OWNERS[("landmarks", id(fn))] = source
    LANDMARK_SOURCES.append(fn)


@dataclass(frozen=True)
class Handoff:
    verb: str
    to: str
    when: Callable[["World", "Creature", "Intention"], bool]


HANDOFFS: list[Handoff] = []


def register_handoff(verb: str, to: str, when: Callable[["World", "Creature", "Intention"], bool]) -> None:
    """In apply_intention, an intention for `verb` becomes the verb `to` when when(world, creature, intention) is true
    (the first match in registration order; a failing `when` counts as False)."""
    HANDOFFS.append(Handoff(verb, to, when))


# ------------------------------------------------------------------ placing a pack's things
@dataclass(frozen=True)
class Populate:
    name: str
    fn: Callable[["World", object, bool], None]
    land: Callable[["World", random.Random, tuple[int, int, int, int]], None] | None = None


POPULATE: list[Populate] = []


def register_populate(name: str, fn: Callable[["World", object, bool], None], *,
                      land: Callable[["World", random.Random, tuple[int, int, int, int]], None] | None = None) -> None:
    """fn(world, rng, fresh) places a pack's things in the world: at the end of world generation (fresh=True, rng the
    generator's) and after a save is restored (fresh=False, rng the world's), so older worlds get them too. Make it
    idempotent, e.g. with a flag in world.ext[<pack>]. land(world, rng, bounds) places the pack's things in one new
    land, bounds = x0, y0, x1, y1 (half-open, inside the surface): no once-flag, and only the rng given."""
    source = _caller()
    _check_free("populate", name, source)
    _OWNERS[("populate", name)] = source
    POPULATE.append(Populate(name, fn, land))


def run_populate(world: "World", rng, fresh: bool, skip: Iterable[str] = ()) -> None:
    """Every pack's populate hook, in registration order, but those named in skip."""
    importlib.import_module("swarmworld.world.packs")  # every pack has registered, whatever was imported first
    for p in POPULATE:
        if p.name not in skip:
            call_safely(f"populate '{p.name}'", p.fn, world, rng, fresh)


def run_populate_land(world: "World", rng, bounds: tuple[int, int, int, int]) -> None:
    """Every pack's land hook, in registration order, to fill the new land inside bounds."""
    importlib.import_module("swarmworld.world.packs")
    for p in POPULATE:
        if p.land:
            call_safely(f"populate land '{p.name}'", p.land, world, rng, bounds)


# ------------------------------------------------------------------ moving the map under the world
@dataclass(frozen=True)
class ShiftHook:
    name: str
    fn: Callable[["World", int], None]
    stores: tuple[str, ...] = ()  # the world state it moves, named for the canary test ("ext.food.piles")


SHIFT_HOOKS: list[ShiftHook] = []


def register_shift_hook(name: str, fn: Callable[["World", int], None], stores: tuple[str, ...] = ()) -> None:
    """fn(world, n) moves every x a pack keeps in its own state by +n, when new land is laid down west of the map
    (World.shift_x). Hooks run in registration order; one that raises is logged and skipped. `stores` names what it
    moves."""
    source = _caller()
    _check_free("shift hook", name, source)
    _OWNERS[("shift hook", name)] = source
    SHIFT_HOOKS.append(ShiftHook(name, fn, tuple(stores)))


def shift_stores() -> set[str]:
    """Every store some shift hook says it moves."""
    return {s for h in SHIFT_HOOKS for s in h.stores}


# ------------------------------------------------------------------ loading packs, and tests
def import_modules(paths: Iterable[Path | str], package: str) -> list[str]:
    """Import every module in these folders as package.<name>, sorted by name (names starting with _ are skipped),
    so each one's registrations run. Returns the names imported."""
    names = sorted(m.name for m in pkgutil.iter_modules([str(p) for p in paths]) if not m.name.startswith("_"))
    for name in names:
        importlib.import_module(f"{package}.{name}")
    return names


@contextmanager
def sandbox():
    """Everything registered inside the block is undone when it ends (for tests)."""
    live = (_OWNERS, KINDS, VERBS, VERB_ALIASES, ALIAS_TARGETS, HANDLERS, TECHNIQUES, SYSTEMS, PERCEPTIONS, POPULATE,
            LANDMARK_SOURCES, HANDOFFS, SHIFT_HOOKS)
    saved = [list(x) if isinstance(x, list) else dict(x) for x in live]
    try:
        yield
    finally:
        for table, old in zip(live, saved):
            if isinstance(table, list):
                table[:] = old
            else:
                table.clear()
                table.update(old)
        _rebuild()


for _source, _raw in kind_files():  # the world's own kinds, then every pack's
    register_kinds(_raw, _source)
