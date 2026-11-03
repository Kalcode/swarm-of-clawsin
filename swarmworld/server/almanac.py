"""The almanac (GET /api/almanac): everything in the game, what this world has found so far, and what's coming.

For the user (web/almanac.html), never for creatures: nothing here reaches world-to-text. It reads

- the game: the catalog (items, recipes, inventions), the registry (object kinds, verbs, techniques, systems,
  perception lines, populate hooks), the packs' data and modules, and the harness layers;
- this world: its discovery records, the recipes each creature knows, what stands on the map, what is carried, stored
  or lying on the ground, the buildings and sites, and how often each verb was chosen (Metrics.verbs);
- the roadmap: issues/README.md's table, with each issue's first paragraph of prose.

Each item gets a tier for the tech tree: 0 for what you can gather, hunt or catch bare-handed, otherwise one more than
its cheapest way to get it, where a way costs the highest tier among what it needs (its ingredients, the tools held,
the station nearby, or the tool it takes to gather it, such as an axe for logs). The whole answer is built at most
once a tick (Almanac caches it)."""

from __future__ import annotations

import importlib
import json
import pkgutil
import re
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from ..mind.prompts import RECALL_HINT, SYSTEM_PROMPT
from ..mind.techniques import CORE_VERBS
from ..world import registry
from ..world.actions import EMPTY_KINDS, SOURCE_HINT, TOOLS_AXE, TOOLS_PICK
from ..world.catalog import DATA, data_files
from ..world.model import DAY_TICKS
from .harness import LAYERS

if TYPE_CHECKING:
    from .state import ServerState

ROOT = Path(__file__).resolve().parent.parent.parent
ISSUES = ROOT / "issues"
PACKS_DIR = Path(registry.__file__).resolve().parent / "packs"
CORE, INVENTED = "core", "invented"
CORE_ABOUT = ("The base world: the meadow and its terrain, the core verbs, and the base items, recipes and kinds of "
              "thing (trees, bushes, boulders, ore, clay, farm animals, the stations creatures build).")

# How the core verbs get things that no recipe makes (swarmworld/world/actions.py): what gathering needs a tool for,
# what the bare ground gives, and what grows from planting (with a hoe) and is then gathered from the crop.
GATHER_TOOLS = {"log": TOOLS_AXE, "copper_ore": TOOLS_PICK, "iron_ore": TOOLS_PICK}
GROUND = [
    {"item": "plant_fiber", "source": "grass", "note": "pull it from grass"},
    {"item": "wheat_seeds", "source": "grass", "note": "now and then, with the fiber (more often holding a knife)"},
    {"item": "carrot_seeds", "source": "grass", "note": "now and then, with the fiber (more often holding a knife)"},
    {"item": "sand", "source": "sand", "note": "scoop it up on sandy ground"},
    {"item": "fish", "source": "water", "tools": ["fishing_rod"], "how": "fish", "note": "cast a line beside water"},
]
GROWN = {"crop"}  # kinds whose gives come from planting, not from the wild
CORE_PROCESSES = [
    {"output": "wheat", "inputs": {"wheat_seeds": 1}, "tools": ["hoe"], "how": "grow",
     "note": "plant the seeds in soil broken with a hoe; gather the ripe wheat (and new seeds)"},
    {"output": "carrot", "inputs": {"carrot_seeds": 1}, "tools": ["hoe"], "how": "grow",
     "note": "plant the seeds in soil broken with a hoe; gather the ripe carrots (and new seeds)"},
]

# When each technique (a verb's tip) is shown, in plain words. A technique missing here is described by its
# trigger's docstring, or generically.
TRIGGER_WORDS = {
    "read": "when a sign, a carving, a stone tablet or a terminal is in sight",
    "program": "when a terminal is in sight",
    "write": "when it carries a sign, or stands beside a sign, a tree or a boulder",
    "store": "when a basket, a chest or another store is in sight",
    "place": "when it carries something it can set down (a campfire, a workbench, a sign...)",
    "plant": "when it carries seeds or berries",
    "teach": "when someone is within earshot (5 steps)",
    "invent": "when it carries two or more kinds of things and hasn't invented anything today",
    "pick_up": "when there are things on the ground beside it, or it carries six or more kinds of things",
    "fire": "when a campfire is in sight",
    "feed": "when an animal is in sight and it carries food that animals eat",
    "build": "beside a building site, when it carries everything a design needs or any building material (logs, "
             "planks, thatch), or when building is its drive",
    "hunt": "when it holds a spear or a sling and wild game is in sight",
    "fill": "when it carries an empty pot and a well or water is in sight",
    "cook": "when it carries raw food and is beside the campfire, oven or smoker that cooks it",
    "drying rack": "when it carries raw meat or fish and a drying rack is in sight",
    "play": "when another awake creature is within 3 steps",
    "dance": "beside a lit campfire",
    "make_music": "when it carries a flute or a drum",
}
LAYER_ABOUT = {
    "plan": "A creature may answer with a plan of up to 5 steps, and its prompt keeps the plan and the step it is on.",
    "disclose": "The instructions name only the everyday verbs; the others appear as tips when they fit, and lore moves "
                "into recall.",
    "recall": "A creature can think back (recall), and related memories, places and recipes come to mind unasked.",
}
GROUP_LABEL = {"animals": "Animals", "plants": "Plants & wood", "insects": "Insects", "stone": "Stone & earth",
               "built": "Built", "other": "Finds & landmarks"}
STATES = (("in progress", "progress"), ("fixed", "fixed"), ("done", "fixed"), ("closed", "fixed"), ("open", "open"))


# ------------------------------------------------------------------ where things come from
def pack_of(source: str | None) -> str:
    """The pack a registry owner or data file belongs to: "swarmworld.world.packs.food" and "packs/food/items.json"
    are "food"; the core modules and the base data files are "core"; anything else (a test) is its module's name."""
    if not source:
        return CORE
    m = re.match(r"(?:swarmworld\.world\.packs\.|packs/)([a-z0-9_]+)", source)
    if m:
        return m.group(1)
    if source.startswith("swarmworld.") or ("/" not in source and source.endswith(".json")):
        return CORE
    return source.rsplit(".", 1)[-1]


@lru_cache(maxsize=4)
def _data_packs(data_dir: Path = DATA) -> tuple[dict[str, str], dict[str, str]]:
    """item id -> pack, and recipe output -> pack, from the data files (they don't change while the world runs)."""
    items = {iid: pack_of(src) for src, path in data_files("items.json", data_dir) for iid in json.loads(path.read_text())}
    recipes = {r["output"]: pack_of(src) for src, path in data_files("recipes.json", data_dir)
               for r in json.loads(path.read_text())}
    return items, recipes


def _pack_module(name: str):
    try:
        return importlib.import_module(f"swarmworld.world.packs.{name}")
    except ImportError:
        return None


def pack_names() -> list[str]:
    mods = {m.name for m in pkgutil.iter_modules([str(PACKS_DIR)]) if not m.name.startswith("_")}
    data = {p.name for p in (DATA / "packs").iterdir() if p.is_dir()} if (DATA / "packs").is_dir() else set()
    return sorted(mods | data)


def _first_para(doc: str | None, limit: int = 440) -> str:
    """A docstring's opening: its first paragraph up to any list, without a dangling "...:" introducing it."""
    lines = []
    for line in (doc or "").strip().splitlines():
        if not line.strip() or LIST.match(line.strip()):
            break
        lines.append(line.strip())
    text = " ".join(" ".join(lines).split())
    if text.endswith(":") and ". " in text:
        text = text[: text.rindex(". ") + 1]
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…"


def _about(fn) -> str:
    return _first_para(getattr(fn, "__doc__", None), 200)


def _designs() -> list[dict]:
    """The building pack's designs (what build can raise), with their pack."""
    mod = _pack_module("building")
    out = []
    for key, d in (getattr(mod, "DESIGNS", None) or {}).items():
        out.append({"id": key, "name": d.get("name", key), "about": d.get("about", ""), "needs": dict(d.get("needs") or {}),
                    "work": d.get("work"), "roof": bool(d.get("roof")), "over_water": bool(d.get("over_water")),
                    "pack": "building",
                    "kinds": sorted({v["kind"] for v in (d.get("legend") or {}).values() if v.get("kind")}
                                    | ({d["kind"]} if d.get("kind") else set()))})
    return out


def _sources(items: dict, kinds: dict) -> dict[str, list[dict]]:
    """item -> how it's got without a recipe: gathered from a kind, hunted, fished, from the bare ground, or from
    farm animals. Each {"how", "source", "tools" (any one of them will do), "amount" [min, max] or None, "note"}."""
    out: dict[str, list[dict]] = defaultdict(list)

    def add(item, how, source, tools=(), amount=None, note=""):
        if item in items:
            out[item].append({"how": how, "source": source, "tools": [t for t in tools if t in items],
                              "amount": amount, "note": note})

    for kind, spec in kinds.items():
        y = spec.get("yields")
        game = spec.get("game") if isinstance(spec.get("game"), dict) else None
        for item, (lo, hi) in (y["items"].items() if y else ()):
            add(item, "gather", kind, [y["tool"]] if y["tool"] else (), [lo, hi])
        for item, amount in ((game.get("gives") or {}).items() if game else ()):
            add(item, "hunt", kind, sorted(game.get("hit") or {}), list(amount))
        for item in spec["gives"]:
            if (y and item in y["items"]) or kind in GROWN:
                continue
            add(item, "animal" if spec["animal"] else "gather", kind, GATHER_TOOLS.get(item, ()),
                note=SOURCE_HINT.get(item, "") if spec["animal"] else "")
    for g in GROUND:
        add(g["item"], g.get("how", "ground"), g["source"], g.get("tools", ()), note=g["note"])
    for crop in GROWN & set(kinds):
        for item in kinds[crop]["gives"]:
            add(f"{item}_seeds", "harvest", crop, note="gathering a ripe crop gives seeds too")
    food = _pack_module("food")
    for item in sorted(getattr(food, "FISHING_ITEMS", ())):
        if item != "fish":
            add(item, "fish", "water", ["fishing_rod"], note=_catch_note(food, item))
    return dict(out)


def _catch_note(food, item: str) -> str:
    for c in (getattr(food, "FISHING", None) or {}).get("catches", []):
        if c.get("item") == item:
            return f"bites in {' or '.join(c.get('water', []))} water at {', '.join(c.get('times', []))}"
    return ""


def _processes(items: dict) -> list[dict]:
    """What turns one thing into another without a recipe: growing crops (core), and the food pack's drying rack and
    water pots. Shaped like recipes, with "how" and "note"."""
    out = [dict(p, station=None, count=1, known_at_start=False, pack=CORE) for p in CORE_PROCESSES]
    food = _pack_module("food")
    for raw, made in (getattr(food, "DRY_MAKES", None) or {}).items():
        out.append({"output": made, "inputs": {raw: 1}, "tools": [], "station": "drying_rack", "count": 1,
                    "known_at_start": False, "pack": "food", "how": "dry",
                    "note": "laid on a drying rack, it dries in dry weather"})
    for empty, full in (getattr(food, "FILL", None) or {}).items():
        out.append({"output": full, "inputs": {empty: 1}, "tools": [], "station": None, "count": 1,
                    "known_at_start": False, "pack": "food", "how": "fill", "note": "filled at a well or the water's edge"})
    return [p for p in out if p["output"] in items and all(i in items for i in [*p["inputs"], *p["tools"]])]


def _tiers(ids: list[str], ways: dict[str, list[list[tuple[str, ...]]]]) -> dict[str, int | None]:
    """Each id's tier from its ways to be got: a way is a list of needs, each need a tuple of alternatives (any one
    will do). No needs is tier 0; otherwise 1 + the highest need, each need costing its cheapest alternative. None for
    what no way reaches."""
    inf = float("inf")
    tier: dict[str, float] = {i: inf for i in ids}
    changed = True
    while changed:
        changed = False
        for i in ids:
            for needs in ways.get(i, ()):
                cost = 0 if not needs else 1 + max(min(tier.get(a, inf) for a in alts) for alts in needs)
                if cost < tier[i]:
                    tier[i], changed = cost, True
    return {i: (None if t == inf else int(t)) for i, t in tier.items()}


# ------------------------------------------------------------------ verbs and their tips
@lru_cache(maxsize=1)
def prompt_lines() -> dict[str, str]:
    """verb -> what the full system prompt's "Actions:" list says of it: its own sentence where a line describes two
    verbs ("eat (target): eat food you carry. drink: drink while beside water."), the whole line where they share
    one description ("store (target, items) / take (target, items): ...")."""
    block = SYSTEM_PROMPT.split("Actions:", 1)[1].split("\n\n", 1)[0]
    out: dict[str, str] = {}
    for raw in block.splitlines():
        line = raw.strip().removeprefix("- ")
        found = list(re.finditer(r"(?:^|[.;/]\s+)([a-z_]+)(?= \(|:)", line))
        for i, m in enumerate(found):
            end = found[i + 1].start() if i + 1 < len(found) else len(line)
            own = line[m.start(1):end].strip()
            own += "" if own.endswith((".", "!", "?", "/")) else "."
            out.setdefault(m.group(1), own if re.search(r"\):|^[a-z_]+:", own) and not own.endswith("/") else line)
    return out


# verb -> one plain sentence for a watcher (the public almanac); the prompt lines above are for the creatures
VERB_ABOUT: dict[str, str] = {
    "walk_to": "Walks to stand beside something or someone the creature can see.",
    "explore": "Wanders about eight steps in one direction to find new places.",
    "gather": "Takes materials from something beside the creature: sticks from trees (logs with an axe), berries from bushes, stone from boulders.",
    "combine": "Tries putting carried things together to discover a recipe; some need a tool in hand or a station close by.",
    "craft": "Makes something from a recipe the creature already knows.",
    "eat": "Eats food from the creature's pack.",
    "drink": "Drinks from water beside the creature.",
    "say": "Speaks aloud, to one creature or to anyone in earshot.",
    "give": "Hands an item to a creature nearby, feeds an animal, or feeds sticks to a campfire.",
    "pick_up": "Picks up items lying on the ground.",
    "drop": "Leaves carried items on the ground.",
    "place": "Sets down a structure the creature carries, such as a campfire, workbench, chest or sign.",
    "write": "Carves words onto a sign, tree or boulder, where anyone can read them later.",
    "read": "Reads a sign, carving, tablet or terminal.",
    "program": "Enters Lua code into a terminal beside the creature.",
    "rest": "Sits still to recover energy.",
    "wait": "Pauses and watches what happens.",
    "plant": "Plants seeds or berries in soil that has been broken with a tool.",
    "invent": "Makes up a brand-new item from two to four things the creature carries, and names it; the world adds it to its catalog.",
    "store": "Puts items into a basket or chest that every creature can use.",
    "take": "Takes items out of a basket or chest.",
    "teach": "Shows a nearby creature how to make something the teacher knows.",
    "wish": "Wishes aloud for something the world lacks; the sky may be listening.",
    "recall": "Searches the creature's own memories for something it half remembers.",
    "build": "Starts or works on a building, bringing the materials its design asks for.",
    "dig": "Digs the ground with a tool, opening a pit or a way down into the deep.",
    "fill_in": "Fills a pit or hole back in, closing it.",
    "hunt": "Hunts an animal with a weapon for meat and hides.",
    "fill": "Fills a container, such as a bottle or bucket, from water or another source.",
    "play": "Plays with another creature or an animal, which builds friendship.",
    "dance": "Dances, alone or with others, for the joy of it.",
    "make_music": "Plays a tune on an instrument; creatures nearby can hear it.",
    "climb": "Climbs down into the deep at a cave mouth, shaft or open pit, or back up to the surface.",
    "light": "Lights a torch or lamp so the creature can see in the dark.",
}


def _when(t: registry.Technique) -> str:
    if t.name in TRIGGER_WORDS:
        return TRIGGER_WORDS[t.name]
    doc = _about(t.trigger)
    return f"when this fits: {doc.rstrip('.')}" if doc else "when its pack's trigger says it fits"


def _technique_verb(t: registry.Technique) -> str | None:
    """The verb a technique is about: its own, or for a use of a core verb (verbs == ()) the line's first word."""
    if t.verbs:
        return t.verbs[0]
    m = re.match(r"([a-z_]+)", t.line)
    return m.group(1) if m and m.group(1) in registry.VERBS else None


def _shown(verb: str, techs: list[registry.Technique]) -> str:
    when = "; or ".join(_when(t) for t in techs)
    if verb in CORE_VERBS:
        return "Always: every creature's instructions describe it."
    if verb in prompt_lines():
        tip = f"as a tip {when}" if when else "it isn't described"
        return f"In the instructions of creatures without the disclose layer; for those with it, {tip}."
    if verb == "recall":
        return "With the recall or disclose layer: a reminder at the end of every prompt."
    if techs:
        return f"As a tip, to every creature, {when}."
    return "Never described to creatures, though it works if one tries it."


# ------------------------------------------------------------------ the game
def game(st: ServerState) -> dict:
    """Everything installed: items, recipes, processes, designs, kinds, verbs, techniques, systems, perception lines,
    populate hooks, packs and harness layers, with each item's tier, sources and uses."""
    w = st.world
    cat = w.catalog
    item_pack, recipe_pack = _data_packs()
    inventions = {inv["id"]: inv for inv in getattr(cat, "inventions", [])}
    kinds = registry.KINDS
    designs = _designs()
    recipes = [{"output": r.output, "inputs": dict(r.inputs), "tools": list(r.tools), "station": r.station,
                "count": r.count, "known_at_start": r.known_at_start,
                "pack": INVENTED if r.output in inventions else recipe_pack.get(r.output, CORE)} for r in cat.recipes]
    processes = _processes(cat.items)
    sources = _sources(cat.items, kinds)

    ways: dict[str, list[list[tuple[str, ...]]]] = defaultdict(list)
    for r in recipes + processes:
        ways[r["output"]].append([(i,) for i in r["inputs"]] + [(t,) for t in r["tools"]]
                                 + ([(r["station"],)] if r["station"] else []))
    for item, srcs in sources.items():
        for s in srcs:
            ways[item].append([tuple(s["tools"])] if s["tools"] else [])
    for d in designs:
        ways[f"design:{d['id']}"].append([(i,) for i in d["needs"]])
    ids = list(cat.items) + [f"design:{d['id']}" for d in designs]
    tier = _tiers(ids, ways)

    edges = []
    for r in recipes + processes:
        how = r.get("how")
        edges += [{"from": i, "to": r["output"], "kind": "input", "n": n, **({"how": how} if how else {})}
                  for i, n in r["inputs"].items()]
        edges += [{"from": t, "to": r["output"], "kind": "tool"} for t in r["tools"]]
        if r["station"]:
            edges.append({"from": r["station"], "to": r["output"], "kind": "station"})
    for item, srcs in sources.items():
        for t in sorted({t for s in srcs for t in s["tools"]}):
            edges.append({"from": t, "to": item, "kind": "gather_tool"})
    for d in designs:
        edges += [{"from": i, "to": f"design:{d['id']}", "kind": "input", "n": n} for i, n in d["needs"].items()]
    edges = [e for e in edges if e["from"] in tier and e["to"] in tier]
    # a tool to gather with is drawn from the tools that set the tier (a stone pickaxe for ore, not the copper one,
    # which is listed in the item's sources); any other edge into an earlier tier is an alternative way, marked back
    lvl = lambda i: tier[i] if tier[i] is not None else 0  # noqa: E731
    edges = [e for e in edges if e["kind"] != "gather_tool" or lvl(e["from"]) < lvl(e["to"])]
    for e in edges:
        if lvl(e["from"]) >= lvl(e["to"]):
            e["back"] = True

    used_in: dict[str, list[dict]] = defaultdict(list)
    for e in edges:
        if e["kind"] != "gather_tool":
            used_in[e["from"]].append({"output": e["to"], "as": e["kind"]})
    makes = {r["output"] for r in recipes}
    found = w.discoveries
    items = []
    for iid, it in cat.items.items():
        r = next((x for x in recipes if x["output"] == iid), None)
        d = found.get(iid)
        status = ("invented" if d and d.get("invented") else "found" if d else "start" if r and r["known_at_start"]
                  else "unfound" if iid in makes else "raw")
        items.append({"id": iid, "name": it.name, "aliases": list(it.aliases), "tags": list(it.tags), "food": it.food,
                      "placeable": it.placeable, "desc": it.desc,
                      "pack": INVENTED if iid in inventions else item_pack.get(iid, CORE),
                      "tier": tier.get(iid) if tier.get(iid) is not None else 0, "reached": tier.get(iid) is not None,
                      "status": status, "discovered": _discovery(d) if d else None,
                      "sources": sources.get(iid, []), "hint": SOURCE_HINT.get(iid, ""),
                      "used_in": used_in.get(iid, []), "kind": iid if iid in kinds else None})
    for d in designs:
        d["tier"] = tier.get(f"design:{d['id']}") or 1

    station_kinds = {r["station"] for r in recipes + processes if r["station"]}
    built = ({i.id for i in cat.items.values() if i.placeable} | {"creation", getattr(_pack_module("building"), "SITE_KIND", "")}
             | {k for d in designs for k in d["kinds"]} | station_kinds)
    built |= {k for k, spec in kinds.items() if spec["name"] in {i.name for i in cat.items.values() if i.placeable}}
    growing = set(EMPTY_KINDS) | {"sapling"} | {s["yields"]["becomes"] for s in kinds.values()
                                                if s.get("yields") and s["yields"].get("becomes")}
    kind_list = [_kind(k, spec, cat.items, built, growing, station_kinds) for k, spec in kinds.items()]

    techs = registry.TECHNIQUES
    own: dict[str, list[registry.Technique]] = defaultdict(list)  # verb -> the techniques that disclose it
    uses: dict[str, list[registry.Technique]] = defaultdict(list)  # verb -> techniques for a use of it (cook: combine)
    for t in techs:
        for v in t.verbs:
            own[v].append(t)
        if not t.verbs and _technique_verb(t):
            uses[_technique_verb(t)].append(t)
    verbs = []
    for v in registry.VERBS:
        mine = own.get(v, [])
        tip = mine[0].line if mine else prompt_lines().get(v) or (RECALL_HINT if v == "recall" else "")
        verbs.append({"name": v, "pack": pack_of(registry.owner("verb", v)),
                      "aliases": sorted(a for a, x in registry.VERB_ALIASES.items() if x == v),
                      "core": v in CORE_VERBS, "about": VERB_ABOUT.get(v, ""),
                      "tip": tip or f"{v}: (no description)", "shown": _shown(v, mine),
                      "uses": [{"name": t.name, "line": t.line, "shown": f"As a tip, {_when(t)}."}
                               for t in uses.get(v, ())]})
    technique_list = [{"name": t.name, "line": t.line, "verbs": list(t.verbs) or [_technique_verb(t)],
                       "pack": pack_of(registry.owner("technique", t.name)),
                       "audience": "every creature" if t.pack else "creatures with the disclose layer",
                       "when": _when(t)} for t in techs]
    systems = [{"name": s.name, "every": s.every, "pack": pack_of(registry.owner("system", s.name)), "about": _about(s.fn)}
               for s in registry.SYSTEMS]
    perception = [{"name": getattr(p.fn, "__name__", "?").strip("_").replace("_", " "), "priority": p.priority,
                   "pack": pack_of(registry.owner("perception", id(p.fn))), "about": _about(p.fn)}
                  for p in registry.PERCEPTIONS]
    populate = [{"name": p.name, "pack": pack_of(registry.owner("populate", p.name)), "about": _about(p.fn)}
                for p in registry.POPULATE]

    lists = {"items": items, "recipes": recipes, "kinds": kind_list, "verbs": verbs, "techniques": technique_list,
             "systems": systems, "perception": perception, "populate": populate, "designs": designs}
    names = [CORE] + [n for n in pack_names() if n != CORE]
    names += sorted({x["pack"] for xs in lists.values() for x in xs} - set(names) - {INVENTED})
    if inventions:
        names.append(INVENTED)
    packs = []
    for name in names:
        mod = _pack_module(name) if name not in (CORE, INVENTED) else None
        about = (CORE_ABOUT if name == CORE else "What the creatures of this world invented themselves."
                 if name == INVENTED else _first_para(getattr(mod, "__doc__", None)))
        packs.append({"id": name, "about": about, **{k: sum(1 for x in xs if x["pack"] == name) for k, xs in lists.items()}})

    layers = st.harness.available
    harness = [{"name": layer, "about": LAYER_ABOUT.get(layer, ""), "in_world": layer in layers,
                "everyone": layer in st.harness.everyone,
                "creatures": sum(1 for c in w.creatures.values() if layer in st.harness.layers_for(c))} for layer in LAYERS]
    nodes = [{"id": i, "type": "item", "tier": x["tier"]} for i, x in zip(cat.items, items)]
    nodes += [{"id": f"design:{d['id']}", "type": "design", "tier": d["tier"]} for d in designs]
    return {**lists, "processes": processes, "packs": packs, "harness": harness, "tree": {"nodes": nodes, "edges": edges},
            "inventions": list(inventions.values())}


def _discovery(d: dict) -> dict:
    return {"item": d["item"], "by": d.get("by"), "by_id": d.get("by_id"), "model": d.get("model"), "tick": d["tick"],
            "day": d["tick"] // DAY_TICKS + 1, "invented": bool(d.get("invented"))}


def _kind(kind: str, spec: dict, items: dict, built: set, growing: set, stations: set) -> dict:
    tags = {t for i in spec["gives"] if i in items for t in items[i].tags}
    if spec["animal"]:
        group = "animals"
    elif "insect" in spec["aliases"]:
        group = "insects"
    elif kind in built or spec["store"] or spec.get("over_water"):
        group = "built"
    elif tags & {"stone", "ore", "earth"}:
        group = "stone"
    elif tags & {"wood", "plant", "food", "crop", "seed"} or kind in growing:
        group = "plants"
    else:
        group = "other"
    game = spec.get("game") if isinstance(spec.get("game"), dict) else None
    return {"id": kind, "name": spec["name"], "aliases": spec["aliases"], "pack": pack_of(registry.owner("object kind", kind)),
            "look": spec.get("look"), "glyph": spec.get("glyph"), "glow": spec.get("glow"), "category": group,
            "yields": spec["yields"], "gives": spec["gives"], "blocking": spec["blocking"], "animal": spec["animal"],
            "gatherable": spec["gatherable"], "carvable": spec["carvable"], "store": spec["store"],
            "station": kind in stations, "water": bool(spec.get("water")), "over_water": bool(spec.get("over_water")),
            "wild": bool(spec.get("wild")), "wary": spec.get("wary"), "flee": spec.get("flee"),
            "habitat": spec.get("habitat"), "game": game, "count": 0}


# ------------------------------------------------------------------ this world now
def world_now(st: ServerState, kinds: list[dict]) -> dict:
    """The census: what stands on the map by kind (and by group), what is carried, stored or on the ground, the
    buildings and sites, tamed animals and crops, the discoveries in order, each creature's known recipes, and how
    often each verb was chosen."""
    w = st.world
    on_map = Counter(o.kind for o in w.objects.values())
    carried, stored, ground = Counter(), Counter(), Counter()
    for c in w.creatures.values():
        carried.update({i: n for i, n in c.inventory.items() if n > 0})
    for o in w.objects.values():
        if o.kind in registry.STORES:
            stored.update({i: n for i, n in (o.data.get("items") or {}).items() if isinstance(n, int) and n > 0})
    for pile in w.ground.values():
        ground.update({i: n for i, n in pile.items() if n > 0})
    held = {i: {"carried": carried[i], "stored": stored[i], "ground": ground[i]} for i in sorted(carried | stored | ground)}
    groups: dict[str, dict] = {g: {"label": label, "count": 0, "kinds": {}} for g, label in GROUP_LABEL.items()}
    for k in kinds:
        k["count"] = on_map.get(k["id"], 0)
        if k["count"]:
            g = groups[k["category"]]
            g["count"] += k["count"]
            g["kinds"][k["id"]] = k["count"]
    bstate = w.ext.get("building") or {}
    sites = [{"design": s.get("design"), "needs": s.get("needs", {}), "have": s.get("have", {}), "work": s.get("work"),
              "done": s.get("done"), "by": s.get("by", [])} for s in (bstate.get("sites") or {}).values()]
    built = w.building_dicts()
    for b, raw in zip(built, (bstate.get("built") or {}).values()):
        b["by"], b["tick"] = list(raw.get("by") or []), raw.get("tick")
    m = st.metrics
    return {
        "tick": w.tick, "clock": w.clock(),
        "kinds": dict(on_map), "groups": groups, "items": held,
        "tamed": dict(Counter(o.kind for o in w.objects.values() if o.data.get("tamed_by"))),
        "crops": dict(Counter(o.data.get("crop") or "wheat" for o in w.objects.values() if o.kind == "crop")),
        "buildings": built, "built": dict(Counter(b["design"] for b in built)), "sites": sites,
        "discoveries": [_discovery(d) for d in sorted(w.discoveries.values(), key=lambda d: d["tick"])],
        "creatures": [{"id": c.id, "name": c.name, "model": c.model, "color": c.color, "asleep": c.asleep,
                       "known": sorted(c.known_recipes)} for c in w.creatures.values()],
        "verbs_since": m.verbs_since,
    }


def _verb_use(st: ServerState, verb: str) -> dict:
    m = st.metrics
    by_model = {model: n[verb] for model, n in m.verbs.items() if n.get(verb)}
    return {"tries": sum(by_model.values()), "ok": sum(n.get(verb, 0) for n in m.verbs_ok.values()), "by_model": by_model}


# ------------------------------------------------------------------ the roadmap
LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
POINTER = re.compile(r":\s*\[[^\]]+\]\([^)]+\)\.?\s*$")  # "How to run it: [docs/x.md](../docs/x.md)."
LIST = re.compile(r"^(?:\d+[.)]|[-*+])\s")


def _plain(md: str) -> str:
    """Markdown to one line of text: links become their words, bold and italics go; `code` stays."""
    text = LINK.sub(r"\1", md)
    text = re.sub(r"\*\*|__", "", text)
    text = re.sub(r"(?<![\w*])\*(?=\S)([^*]+?)(?<=\S)\*(?![\w*])", r"\1", text)  # *emphasis*
    return " ".join(text.split())


def summary(text: str, limit: int = 480) -> str:
    """An issue's first paragraph of prose: not its title, its status line, a heading, a list, a table, code, or a
    line that only points to another document."""
    for para in re.split(r"\n\s*\n", text):
        p = para.strip()
        if (not p or p[0] in "#|>" or p.startswith(("```", "**Priority", "<")) or LIST.match(p)
                or POINTER.search(p)):
            continue
        out = _plain(p)
        return out if len(out) <= limit else out[:limit].rsplit(" ", 1)[0] + "…"
    return ""


def _state(status: str) -> str:
    low = status.lower()
    return next((s for word, s in STATES if low.startswith(word)), "open")


def roadmap(issues_dir: Path = ISSUES) -> dict:
    """issues/README.md's table: each issue's number, priority, label, title, status (and its state: open, progress
    or fixed), file, and summary (its first paragraph)."""
    readme = issues_dir / "README.md"
    if not readme.is_file():
        return {"issues": [], "counts": {}}
    rows = [line.strip() for line in readme.read_text().splitlines() if line.strip().startswith("|")]
    if len(rows) < 2:
        return {"issues": [], "counts": {}}
    cells = lambda line: [c.strip() for c in line.strip().strip("|").split("|")]  # noqa: E731
    head = [h.lower() for h in cells(rows[0])]
    col = {name: head.index(name) for name in ("#", "priority", "label", "title", "status") if name in head}
    issues = []
    for line in rows[2:]:
        c = cells(line)
        get = lambda name: c[col[name]] if name in col and col[name] < len(c) else ""  # noqa: E731
        m = re.match(r"\[([^\]]+)\]\(([^)]+)\)", get("#"))
        number, file = (m.group(1), m.group(2)) if m else (get("#"), None)
        path = (issues_dir / file) if file else None
        status = get("status")
        issues.append({"number": number, "priority": get("priority"), "label": get("label"), "title": get("title"),
                       "status": status, "state": _state(status),
                       "file": file if path and path.is_file() else None,
                       "summary": summary(path.read_text()) if path and path.is_file() else ""})
    return {"issues": issues, "counts": dict(Counter(i["state"] for i in issues))}


# ------------------------------------------------------------------ the whole almanac
def build(st: ServerState, issues_dir: Path = ISSUES) -> dict:
    g = game(st)
    now = world_now(st, g["kinds"])
    for v in g["verbs"]:
        v["used"] = _verb_use(st, v["name"])
    for d in g["designs"]:
        d["built"] = now["built"].get(d["id"], 0)
        d["sites"] = sum(1 for s in now["sites"] if s["design"] == d["id"])
        d["status"] = "built" if d["built"] else "site" if d["sites"] else "unbuilt"
    w = st.world
    return {"tick": w.tick, "day": w.clock()["day"], **g, "world": now, "roadmap": roadmap(issues_dir)}


class Almanac:
    """The almanac for a server, built at most once a tick."""

    def __init__(self, issues_dir: Path = ISSUES):
        self.issues_dir = issues_dir
        self._key: tuple | None = None
        self._value: dict | None = None
        self._text: str | None = None

    def get(self, st: ServerState) -> dict:
        w = st.world
        key = (id(w), w.tick, len(w.catalog.items))
        if key != self._key or self._value is None:
            self._value, self._text, self._key = build(st, self.issues_dir), None, key
        return self._value

    def text(self, st: ServerState) -> str:
        value = self.get(st)
        if self._text is None:
            self._text = json.dumps(value)
        return self._text
