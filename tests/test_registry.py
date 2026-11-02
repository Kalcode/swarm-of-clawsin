"""The foundation for content packs: object kinds from data, packs' items, recipes and kinds, and the plug-in points for
verbs, techniques, per-tick systems, perception lines and sounds."""

import importlib
import json
import shutil
import subprocess
import sys
import textwrap
import uuid
from pathlib import Path

import pytest

from swarmworld.mind.prompts import INTENTION_SCHEMA, INTENTION_SCHEMA_PLAN
from swarmworld.mind.techniques import CORE_VERBS, TECHNIQUES, relevant
from swarmworld.server.persistence import restore
from swarmworld.server.state import ServerState
from swarmworld.world import actions, model, registry
from swarmworld.world.actions import Intention, apply_intention, parse_intention, step_activity
from swarmworld.world.catalog import DATA, Catalog
from swarmworld.world.model import DAY_TICKS, START_TICK, Creature, World
from swarmworld.world.perception import perceive
from swarmworld.world.registry import Technique
from swarmworld.world.simulation import Simulation

# The kind tables as they were written out in model.py and actions.py before they moved to objects.json.
OLD_BLOCKING = {
    "tree", "pine", "rock", "copper_vein", "iron_vein", "wall",
    "workbench", "furnace", "chest", "basket", "terminal", "campfire", "millstone", "bed", "wishing_stone",
}
OLD_NAMES = {
    "tree": "oak tree", "pine": "pine tree", "stump": "tree stump", "bush": "berry bush",
    "bush_empty": "picked-over bush", "rock": "boulder", "copper_vein": "green-streaked rock",
    "iron_vein": "rust-streaked rock", "clay": "clay bank", "campfire": "campfire",
    "workbench": "workbench", "furnace": "furnace", "wall": "wooden wall", "sign": "sign",
    "chest": "chest", "basket": "basket", "terminal": "strange terminal", "tablet": "stone tablet",
    "crop": "wheat", "sapling": "berry sapling", "millstone": "millstone", "bed": "bed", "door": "door",
    "chicken": "chicken", "sheep": "sheep", "cow": "cow", "creation": "creation", "wishing_stone": "wishing stone",
}
OLD_ANIMALS = {"chicken", "sheep", "cow"}
OLD_ALIASES = {
    "wishing_stone": ["wishing stone", "wish stone", "wishing rock", "altar", "shrine"],
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
    "chest": ["chest", "box", "store", "storage"],
    "basket": ["basket", "store", "storage", "shared store"],
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
OLD_GATHERABLE = {"tree", "pine", "bush", "rock", "copper_vein", "iron_vein", "clay", "crop", "chicken", "sheep", "cow"}
OLD_SOURCES = {
    "stick": {"tree", "pine"}, "log": {"tree", "pine"}, "stone": {"rock"}, "flint": {"rock"},
    "berries": {"bush"}, "clay": {"clay"}, "copper_ore": {"copper_vein"}, "iron_ore": {"iron_vein"},
    "wheat": {"crop"}, "carrot": {"crop"}, "egg": {"chicken"}, "milk": {"cow"}, "wool": {"sheep"},
}
OLD_CARVABLE = {"tree", "pine", "rock", "stump"}
OLD_STORES = {"basket", "chest"}

OLD = {"OBJECT_NAMES": OLD_NAMES, "BLOCKING": OLD_BLOCKING, "OBJECT_ALIASES": OLD_ALIASES, "ANIMALS": OLD_ANIMALS,
       "GATHERABLE": OLD_GATHERABLE, "ITEM_SOURCES": OLD_SOURCES, "CARVABLE": OLD_CARVABLE, "STORES": OLD_STORES}
LIVE = {"OBJECT_NAMES": model.OBJECT_NAMES, "BLOCKING": model.BLOCKING, "OBJECT_ALIASES": model.OBJECT_ALIASES,
        "ANIMALS": model.ANIMALS, "GATHERABLE": actions.GATHERABLE, "ITEM_SOURCES": actions.ITEM_SOURCES,
        "CARVABLE": actions.CARVABLE, "STORES": actions.STORES}

REED_PACK = {
    "items": {"reed": {"name": "reed", "aliases": ["reeds"], "tags": ["plant"], "desc": "A long hollow stem."},
              "reed_mat": {"name": "reed mat", "placeable": True}},
    "recipes": [{"output": "reed_mat", "inputs": {"reed": 4}}],
    "objects": {
        "reed_bed": {"name": "reed bed", "aliases": ["reed bed", "reeds"], "look": "reeds",
                     "yields": {"items": {"reed": [2, 2]}, "uses": 2, "becomes": "reed_stubble", "regrow": 100}},
        "reed_stubble": {"name": "cut reeds", "aliases": ["stubble"], "look": "reeds_cut"},
    },
}

HUM_PACK = """
    from swarmworld.world.actions import ActionResult
    from swarmworld.world.registry import Technique, register_technique, register_verb


    def hum(world, c, it):
        return ActionResult(True, f"You hum {it.text or 'a tune'}.")


    def someone_near(world, c):
        return 2.0 if len(world.creatures) > 1 else None


    register_verb("hum", hum, aliases=("whistle", "sing_along"))
    register_technique(Technique("hum", "hum (text): hum a tune for those around you.", someone_near))
"""


def grass_world(catalog=None, size=30):
    w = World(size, size, [["g"] * size for _ in range(size)], catalog or Catalog.load())
    w.tick = START_TICK
    return w


def creature(w, name, x, y):
    c = Creature(f"c{len(w.creatures) + 1}", name, x, y, asleep=False, wake_reason=None, last_think_tick=w.tick)
    c.known_recipes = {r.output for r in w.catalog.recipes if r.known_at_start}
    w.creatures[c.id] = c
    return c


def act(w, c, **kw):
    res = apply_intention(w, c, Intention(**kw))
    while c.activity:
        step_activity(w, c)
    return res


def data_dir(tmp_path, packs):
    """A data folder like swarmworld/data: copies of the base files, plus packs/<pack>/<file>.json for each pack."""
    root = tmp_path / "data"
    root.mkdir(parents=True)
    for name in ("items.json", "recipes.json", "objects.json"):
        shutil.copy(DATA / name, root / name)
    for pack, files in packs.items():
        (root / "packs" / pack).mkdir(parents=True)
        for name, content in files.items():
            (root / "packs" / pack / f"{name}.json").write_text(json.dumps(content))
    return root


@pytest.fixture
def pack_modules(tmp_path, monkeypatch):
    """Write pack modules into a throwaway package and import them the way swarmworld/world/packs/ is imported."""
    package = "scratch_packs_" + uuid.uuid4().hex[:8]
    root = tmp_path / "modules"
    (root / package).mkdir(parents=True)
    (root / package / "__init__.py").write_text("")
    monkeypatch.syspath_prepend(str(root))

    def install(**modules):
        for name, source in modules.items():
            (root / package / f"{name}.py").write_text(textwrap.dedent(source))
        importlib.invalidate_caches()
        return registry.import_modules([root / package], package)

    install.package = package
    yield install
    for name in [m for m in sys.modules if m == package or m.startswith(package + ".")]:
        del sys.modules[name]


# ------------------------------------------------------------------ kinds and packs as data
def test_kind_tables_unchanged_from_data():
    base = registry.load_objects(DATA, packs=False)
    tables = registry.build_tables(base)
    for name, old in OLD.items():
        assert tables[name] == old, name
    kinds = set(base)
    for name, live in LIVE.items():
        assert live is getattr(registry, name), name  # one shared table, so kinds added later are seen everywhere
        # The live tables are the base kinds plus whatever packs add; a pack never changes a base kind.
        if isinstance(live, set):
            assert live & kinds == OLD[name], name
        elif name == "ITEM_SOURCES":
            assert {i: ks & kinds for i, ks in live.items() if ks & kinds} == OLD[name]
        else:
            assert {k: v for k, v in live.items() if k in kinds} == OLD[name], name


def test_pack_items_and_kinds_merge(tmp_path):
    data = data_dir(tmp_path, {"reeds": REED_PACK, "tiny": {"items": {"pebble": {"name": "pebble"}}}})
    base, cat = Catalog.load(data_dir(tmp_path / "base", {})), Catalog.load(data)  # base: no packs at all
    assert set(base.items) | {"reed", "reed_mat", "pebble"} == set(cat.items)
    assert cat.resolve("reeds") == "reed" and cat.items["reed"].desc == "A long hollow stem."
    assert [r.output for r in cat.recipes] == [r.output for r in base.recipes] + ["reed_mat"]  # packs after the base
    assert cat.recipe_for("reed_mat").inputs == {"reed": 4}

    kinds = registry.load_objects(data)
    assert list(kinds) == list(registry.load_objects(DATA, packs=False)) + ["reed_bed", "reed_stubble"]
    tables = registry.build_tables(kinds)
    assert tables["OBJECT_NAMES"]["reed_bed"] == "reed bed" and tables["OBJECT_ALIASES"]["reed_stubble"] == ["stubble"]
    assert "reed_bed" in tables["GATHERABLE"] and "reed_stubble" not in tables["GATHERABLE"]
    assert "reed_bed" not in tables["BLOCKING"] | tables["ANIMALS"] | tables["CARVABLE"] | tables["STORES"]
    assert tables["ITEM_SOURCES"]["reed"] == {"reed_bed"}  # gives defaults to what it yields
    assert tables["YIELDS"]["reed_bed"] == {"items": {"reed": [2, 2]}, "tool": None, "uses": 2,
                                            "becomes": "reed_stubble", "regrow": 100}
    assert tables["DEPLETED"] == {"reed_stubble"}
    assert tables["LOOKS"] == {"reed_bed": "reeds", "reed_stubble": "reeds_cut"}
    assert "reed_bed" not in registry.KINDS  # reading a data folder registers nothing


def test_duplicate_registration_names_both_packs(tmp_path, pack_modules):
    with registry.sandbox():
        with pytest.raises(ValueError) as err:
            pack_modules(alpha=HUM_PACK, beta=HUM_PACK)
    message = str(err.value)
    assert "'hum'" in message and f"{pack_modules.package}.alpha" in message and f"{pack_modules.package}.beta" in message
    assert "hum" not in actions.VERBS  # the sandbox took alpha's verb back out

    reed_kind = {"name": "reed bed"}
    data = data_dir(tmp_path, {"a": {"objects": {"reed_bed": reed_kind}},
                               "b": {"objects": {"reed_bed": reed_kind}, "items": {"stick": {"name": "stick"}}}})
    with pytest.raises(ValueError, match=r"'reed_bed'.*packs/a/objects\.json.*packs/b/objects\.json"):
        registry.load_objects(data)
    with pytest.raises(ValueError, match=r"'stick'.*in items\.json.*packs/b/items\.json"):
        Catalog.load(data)
    data = data_dir(tmp_path / "again", {"c": {"recipes": [{"output": "rope", "inputs": {"stick": 2}}]}})
    with pytest.raises(ValueError, match=r"'rope'.*in recipes\.json.*packs/c/recipes\.json"):
        Catalog.load(data)

    with registry.sandbox():  # registering at run time: the first owner and the second are both named
        with pytest.raises(ValueError, match=r"'tree'.*objects\.json.*test_registry"):
            registry.register_kinds({"tree": {"name": "tree"}})
        with pytest.raises(ValueError, match=r"'read'.*swarmworld\.mind\.techniques.*test_registry"):
            registry.register_technique(Technique("read", "read (target): again.", lambda w, c: None))
        with pytest.raises(ValueError, match=r"'gather'.*swarmworld\.world\.actions.*test_registry"):
            registry.register_verb("gather", lambda w, c, it: None)
        with pytest.raises(ValueError, match=r"'chop'.*swarmworld\.world\.actions.*test_registry"):
            registry.register_verb("fell", lambda w, c, it: None, aliases=("chop",))  # chop already means gather
        registry.register_system("tides", 5, lambda sim, t: None)
        with pytest.raises(ValueError, match=r"'tides'.*test_registry.*test_registry"):
            registry.register_system("tides", 7, lambda sim, t: None)

        def line(world, c):
            return None

        registry.register_perception(line)
        with pytest.raises(ValueError, match="registered twice"):
            registry.register_perception(line)
    assert "fell" not in actions.VERBS and not any(s.name == "tides" for s in registry.SYSTEMS)


def test_generic_yields_gather_deplete_regrow(tmp_path):
    w = grass_world(Catalog.load(data_dir(tmp_path, {"reeds": REED_PACK})))
    c = creature(w, "Tam", 5, 5)
    with registry.sandbox():
        registry.register_kinds(REED_PACK["objects"], "packs/reeds/objects.json")  # only data: no code for reeds
        assert "reed_bed" in actions.GATHERABLE and actions.ITEM_SOURCES["reed"] == {"reed_bed"}
        bed = w.add_object("reed_bed", 6, 5)
        assert bed.name == "reed bed" and w.walkable(6, 5)

        res = act(w, c, action="gather", target="reeds")
        assert res.ok and c.inventory["reed"] == 2 and bed.kind == "reed_bed" and bed.data["uses"] == 1
        res = act(w, c, action="gather")  # nothing named: whatever beside you still gives something
        assert res.ok and c.inventory["reed"] == 4
        assert bed.kind == "reed_stubble" and bed.name == "cut reeds" and bed.data["regrow_at"] == w.tick + 100
        res = act(w, c, action="gather", target="stubble")
        assert not res.ok and "nothing left" in res.message and c.inventory["reed"] == 4

        sim = Simulation(w)
        for _ in range(110):
            sim.tick()
        assert bed.kind == "reed_bed" and not {"uses", "regrow_at", "regrows"} & set(bed.data)
        res = act(w, c, action="gather", target="reed")  # the item's name finds what gives it
        assert res.ok and c.inventory["reed"] == 6 and bed.data["uses"] == 1


def test_generic_yields_need_their_tool_and_can_run_out():
    w = grass_world()
    c = creature(w, "Tam", 5, 5)
    with registry.sandbox():
        registry.register_kinds({"flint_nodule": {
            "name": "flint nodule", "aliases": ["nodule"], "blocking": True,
            "yields": {"items": {"flint": [1, 1], "stone": [0, 0]}, "tool": "stone_pickaxe", "uses": 1}}})
        nodule = w.add_object("flint_nodule", 6, 5)
        assert not w.walkable(6, 5)
        res = act(w, c, action="gather", target="nodule")
        assert not res.ok and "stone pickaxe" in res.message and nodule.id in w.objects
        c.inventory["stone_pickaxe"] = 1
        res = act(w, c, action="gather", target="nodule")
        assert res.ok and c.inventory["flint"] == 1 and "stone" not in c.inventory
        assert nodule.id not in w.objects and w.walkable(6, 5)  # used up with nothing to become: gone


# ------------------------------------------------------------------ registries
def test_registered_verb_works_and_is_in_the_schema(pack_modules):
    # Packs are imported by actions itself, before anything reads VERBS, and the schema shares that very list.
    assert "swarmworld.world.packs" in sys.modules
    assert INTENTION_SCHEMA["properties"]["action"]["enum"] is actions.VERBS
    assert INTENTION_SCHEMA_PLAN["properties"]["action"]["enum"] is actions.VERBS
    w = grass_world()
    c, _ = creature(w, "Tam", 5, 5), creature(w, "Mara", 6, 5)
    with registry.sandbox():
        assert pack_modules(hum=HUM_PACK) == ["hum"]
        assert actions.VERBS[-1] == "hum" and "hum" in INTENTION_SCHEMA["properties"]["action"]["enum"]
        it = parse_intention({"action": "whistle", "text": "softly"})
        assert it.action == "hum"
        res = apply_intention(w, c, it)
        assert res.ok and res.message == "You hum softly."
        assert "hum (text): hum a tune for those around you." in relevant(w, c)
        assert set(actions.VERBS) == set(CORE_VERBS) | {v for t in TECHNIQUES for v in t.verbs} | {"recall"}
    assert "hum" not in actions.VERBS and "hum" not in actions.HANDLERS and "whistle" not in actions.VERB_ALIASES
    assert parse_intention({"action": "hum"}) is None and not any(t.name == "hum" for t in TECHNIQUES)


def test_pack_verb_can_take_over_a_core_alias():
    w = grass_world()
    c = creature(w, "Tam", 5, 5)
    assert parse_intention({"action": "build", "target": "campfire"}).action == "craft"
    with registry.sandbox():
        registry.register_verb("build", lambda world, cr, it: actions.ActionResult(True, f"You start a {it.target}."))
        assert parse_intention({"action": "build"}).action == "build" and "build" not in actions.VERB_ALIASES
        assert act(w, c, action="build", target="hut").message == "You start a hut."
    assert parse_intention({"action": "build"}).action == "craft" and actions.VERB_ALIASES["build"] == "craft"


def test_registered_system_runs_on_its_interval():
    w = grass_world()
    creature(w, "Tam", 5, 5)
    sim = Simulation(w)
    calls = []
    with registry.sandbox():
        registry.register_system("every 7", 7, lambda s, t: calls.append(("seven", t, s is sim)))
        registry.register_system("every tick", 1, lambda s, t: calls.append(("one", t, s is sim)))
        with pytest.raises(ValueError):
            registry.register_system("never", 0, lambda s, t: None)
        start = w.tick
        for _ in range(21):
            sim.tick()
        sevens = [t for name, t, _ in calls if name == "seven"]
        assert sevens == [t for t in range(start + 1, start + 22) if t % 7 == 0] and len(sevens) == 3
        assert [t for name, t, _ in calls if name == "one"] == list(range(start + 1, start + 22))
        assert all(same for _, _, same in calls)
        assert [name for name, t, _ in calls if t == sevens[0]] == ["seven", "one"]  # due systems in registration order
    sim.tick()
    assert len(calls) == 24  # unregistered on leaving the sandbox


def test_extra_perception_lines_are_capped():
    w = grass_world()
    c = creature(w, "Tam", 5, 5)
    before = perceive(w, c, heard=['Mara says: "hello"'])
    called = []

    def quiet(world, cr):
        called.append("quiet")

    def first(world, cr):
        called.append("first")
        return "The air smells of rain."

    def blank(world, cr):
        called.append("blank")
        return ""

    def second(world, cr):
        called.append("second")
        return "Bees hum in the clover."

    def third(world, cr):
        called.append("third")
        return "A third line that must not show."

    with registry.sandbox():
        for fn in (quiet, first, blank, second, third):
            registry.register_perception(fn)
        text = perceive(w, c, heard=['Mara says: "hello"'])
    lines = text.splitlines()
    carry = next(i for i, line in enumerate(lines) if line.startswith("You carry"))
    assert lines[carry - 3:carry] == ['You hear: Mara says: "hello"', "The air smells of rain.", "Bees hum in the clover."]
    assert "third" not in text and called == ["quiet", "first", "blank", "second"]  # no room left: not even asked
    assert [line for line in lines if line not in ("The air smells of rain.", "Bees hum in the clover.")] == before.splitlines()
    assert perceive(w, c, heard=['Mara says: "hello"']) == before


# ------------------------------------------------------------------ sound
def test_sound_reaches_listeners_with_direction():
    w = grass_world()
    sim = Simulation(w)
    chopper = creature(w, "Tam", 10, 10)
    south = creature(w, "Mara", 10, 16)  # 6 steps south of the sound
    beside = creature(w, "Odo", 11, 10)
    far = creature(w, "Pell", 10, 19)  # 9 steps: out of earshot
    ev = w.sound(10, 10, "chopping", radius=8, kind="chop", source=chopper.id)
    assert ev.kind == "sound" and ev.actor == chopper.id
    assert ev.to_dict()["sound"] == "chop" and ev.to_dict()["radius"] == 8 and ev.to_dict()["loud"] is False
    sim.tick()
    assert sim.take_heard(south) == ["You hear chopping, about 6 steps north."]
    assert sim.take_heard(beside) == ["You hear chopping, right beside you to the west."]
    assert sim.take_heard(far) == [] and sim.take_heard(chopper) == []

    for x in (10, 9):  # the same kind of sound twice: only the latest is kept
        w.sound(x, 10, "chopping", kind="chop", source=chopper.id)
    w.sound(4, 16, "a splash", kind="splash")
    sim.tick()
    heard = sim.take_heard(south)
    assert heard == ["You hear chopping, about 6 steps north.", "You hear a splash, about 6 steps west."]
    for n in range(4):  # never more than two sounds a turn
        w.sound(10, 12 + n, f"sound {n}", kind=f"k{n}")
    sim.tick()
    assert sim.take_heard(south) == ["You hear sound 2, about 2 steps north.",
                                     "You hear sound 3, right beside you to the north."]
    text = perceive(w, south, heard=['Odo says: "over here"', *heard])
    lines = text.splitlines()
    i = lines.index('You hear: Odo says: "over here"')
    assert lines[i + 1:i + 4] == [*heard, "You carry: nothing."]


def test_sound_skips_source_and_sleepers():
    w = grass_world()
    w.tick = DAY_TICKS * 2 + int(DAY_TICKS * 0.7)  # night
    notes = {}
    sim = Simulation(w, memory_sink=lambda c, t, i: notes.setdefault(c.name, []).append(t))
    source = creature(w, "Tam", 10, 10)
    sleeper = creature(w, "Mara", 12, 10)
    sim._start_sleep(sleeper, True)
    away = creature(w, "Odo", 10, 12)
    away.asleep = True  # its mind is away: the body is in stasis
    w.sound(10, 10, "a branch snapping", kind="snap", source=source.id)
    sim.tick()
    assert sim.take_heard(source) == [] and sim.take_heard(sleeper) == [] and sim.take_heard(away) == []
    assert (sleeper.activity or {}).get("sleep") and "Mara" not in notes

    w.sound(10, 10, "thunder crashing", radius=20, kind="thunder", loud=True)
    sim.tick()
    assert sim.take_heard(sleeper) == ["You hear thunder crashing, about 2 steps west."]
    assert not (sleeper.activity or {}).get("sleep") and sleeper.wake_reason == "woke"
    assert any("wakes you" in n for n in notes["Mara"])
    assert sim.take_heard(away) == [] and away.asleep
    assert sim.take_heard(source) == ["You hear thunder crashing, right here."]  # no source: everyone awake hears it


# ------------------------------------------------------------------ the packs and data that are installed
FIRST_IMPORTS = ["swarmworld.world.simulation", "swarmworld.mind.techniques", "swarmworld.mind.prompts",
                 "swarmworld.world.model", "swarmworld.world.registry", "swarmworld.world.packs", "swarmworld.server.state"]
WHAT_REGISTERED = """
import importlib, json, sys
import swarmworld.world.packs
seen = {}
for first in FIRST + ["swarmworld.world.packs." + n for n in swarmworld.world.packs.LOADED]:
    for name in [m for m in sys.modules if m.split(".")[0] == "swarmworld"]:
        del sys.modules[name]
    importlib.import_module(first)
    from swarmworld.mind.prompts import INTENTION_SCHEMA
    from swarmworld.mind.techniques import TECHNIQUES
    from swarmworld.world import registry
    seen[first] = [registry.VERBS, INTENTION_SCHEMA["properties"]["action"]["enum"], [t.name for t in TECHNIQUES],
                   [s.name for s in registry.SYSTEMS], len(registry.PERCEPTIONS), list(registry.KINDS)]
print(json.dumps(seen))
"""


def test_packs_import_whichever_module_comes_first():
    """Whatever a program imports first, every pack registers the same things in the same order. (A pack that
    imports swarmworld.world.simulation or swarmworld.mind at its top fails here: see registry.py.)"""
    script = f"FIRST = {FIRST_IMPORTS!r}\n" + WHAT_REGISTERED
    out = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                         cwd=Path(__file__).resolve().parent.parent)
    assert out.returncode == 0, out.stderr
    seen = json.loads(out.stdout)
    assert len(seen) >= len(FIRST_IMPORTS)
    first = seen[FIRST_IMPORTS[0]]
    assert first[0] == first[1]  # the schema lists every verb
    for entry, registered in seen.items():
        assert registered == first, entry


def test_installed_data_is_consistent():
    """Every item, kind and tool that packs' data names exists, so a typo in a pack's JSON fails here."""
    cat = Catalog.load()
    items = set(cat.items)
    for r in cat.recipes:
        assert r.output in items and set(r.inputs) <= items and set(r.tools) <= items, r
        assert r.station is None or r.station in items or r.station in registry.KINDS, r
    for kind, spec in registry.KINDS.items():
        assert set(spec["gives"]) <= items, kind
        y = spec["yields"]
        if y:
            assert set(y["items"]) <= items and (y["tool"] is None or y["tool"] in items), kind
            assert y["becomes"] is None or y["becomes"] in registry.KINDS, kind


def test_prepack_save_loads(prepack_save):
    st = ServerState(seed=1)
    restore(st, prepack_save)
    w = st.world
    assert (w.width, w.height, len(w.creatures)) == (64, 64, 6)
    assert {"campfire", "basket", "sign", "crop"} <= {o.kind for o in w.objects.values()}
    for c in w.creatures.values():
        c.asleep = False
    for _ in range(200):
        st.tick_message(st.sim.tick())
    assert w.tick == 1044 + 200 and all(perceive(w, c) for c in w.creatures.values())
