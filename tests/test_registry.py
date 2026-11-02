"""The foundation for content packs: object kinds from data, packs' items, recipes and kinds, and the plug-in points for
verbs, techniques, per-tick systems, perception lines and sounds."""

import importlib
import json
import logging
import random
import subprocess
import sys
import textwrap
import uuid
from contextlib import contextmanager
from pathlib import Path

import pytest

from swarmworld.mind.prompts import INTENTION_SCHEMA, INTENTION_SCHEMA_PLAN
from swarmworld.mind.techniques import CORE_VERBS, TECHNIQUES, relevant
from swarmworld.server.persistence import restore, save
from swarmworld.server.state import ServerState
from swarmworld.world import actions, model, registry
from swarmworld.world.actions import Intention, apply_intention, parse_intention, step_activity
from swarmworld.world.catalog import DATA, Catalog, _norm
from swarmworld.world.model import DAY_TICKS, START_TICK, Creature, World
from swarmworld.world.perception import perceive
from swarmworld.world.registry import Technique
from swarmworld.world.simulation import Simulation
from swarmworld.world.terrain import generate_world

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

# Test packs use probe names, so they never collide with what real packs install.
REED_PACK = {
    "items": {"probe_reed": {"name": "probe reed", "aliases": ["probe reeds"], "tags": ["plant"], "desc": "A long hollow stem."},
              "probe_mat": {"name": "probe mat"}},
    "recipes": [{"output": "probe_mat", "inputs": {"probe_reed": 4}}],
    "objects": {
        "probe_bed": {"name": "probe bed", "aliases": ["probe bed", "probe reeds"], "look": "reeds",
                      "yields": {"items": {"probe_reed": [2, 2]}, "uses": 2, "becomes": "probe_stubble", "regrow": 100}},
        "probe_stubble": {"name": "cut probe reeds", "aliases": ["probe stubble"], "look": "reeds_cut"},
    },
}

HUM_PACK = """
    from swarmworld.world.actions import ActionResult
    from swarmworld.world.registry import Technique, register_technique, register_verb


    def hum(world, c, it):
        return ActionResult(True, f"You hum {it.text or 'a tune'}.")


    def someone_near(world, c):
        return 99.0 if len(world.creatures) > 1 else None


    register_verb("probe_hum", hum, aliases=("probe_whistle", "probe_sing"))
    register_technique(Technique("probe_hum", "probe_hum (text): hum a tune for those around you.", someone_near))
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


@contextmanager
def only_this_test():
    """A sandbox without the installed packs' systems, perception lines and populate hooks, so a test sees only its own."""
    with registry.sandbox():
        registry.SYSTEMS.clear()
        registry.PERCEPTIONS.clear()
        registry.POPULATE.clear()
        yield


class NullWS:
    closed = False

    async def send_json(self, _):
        pass


def core_alias() -> tuple[str, str]:
    """A word that so far only means a core verb (packs may take some over), and that verb."""
    return next((a, v) for a, v in actions.VERB_ALIASES.items() if registry.owner("verb", a) == registry.CORE_VERBS_MODULE)


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


def test_pack_items_and_kinds_merge(data_dir):
    data = data_dir({"reeds": REED_PACK, "tiny": {"items": {"probe_pebble": {"name": "probe pebble"}}}})
    base, cat = Catalog.load(data_dir({})), Catalog.load(data)  # base: no packs at all
    assert set(base.items) | {"probe_reed", "probe_mat", "probe_pebble"} == set(cat.items)
    assert cat.resolve("probe reeds") == "probe_reed" and cat.items["probe_reed"].desc == "A long hollow stem."
    assert [r.output for r in cat.recipes] == [r.output for r in base.recipes] + ["probe_mat"]  # packs after the base
    assert cat.recipe_for("probe_mat").inputs == {"probe_reed": 4}

    kinds = registry.load_objects(data)
    assert list(kinds) == list(registry.load_objects(DATA, packs=False)) + ["probe_bed", "probe_stubble"]
    tables = registry.build_tables(kinds)
    assert tables["OBJECT_NAMES"]["probe_bed"] == "probe bed"
    assert tables["OBJECT_ALIASES"]["probe_stubble"] == ["probe stubble"]
    assert "probe_bed" in tables["GATHERABLE"] and "probe_stubble" not in tables["GATHERABLE"]
    assert "probe_bed" not in tables["BLOCKING"] | tables["ANIMALS"] | tables["CARVABLE"] | tables["STORES"]
    assert tables["ITEM_SOURCES"]["probe_reed"] == {"probe_bed"}  # gives defaults to what it yields
    assert tables["YIELDS"]["probe_bed"] == {"items": {"probe_reed": [2, 2]}, "tool": None, "uses": 2,
                                             "becomes": "probe_stubble", "regrow": 100}
    assert tables["DEPLETED"] == {"probe_stubble"}
    assert tables["LOOKS"] == {"probe_bed": "reeds", "probe_stubble": "reeds_cut"}
    assert "probe_bed" not in registry.KINDS  # reading a data folder registers nothing


def test_duplicate_registration_names_both_packs(data_dir, pack_modules):
    with registry.sandbox():
        with pytest.raises(ValueError) as err:
            pack_modules(alpha=HUM_PACK, beta=HUM_PACK)
    message = str(err.value)
    assert "'probe_hum'" in message
    assert f"{pack_modules.package}.alpha" in message and f"{pack_modules.package}.beta" in message
    assert "probe_hum" not in actions.VERBS  # the sandbox took alpha's verb back out

    data = data_dir({"a": {"objects": {"probe_bed": {"name": "probe bed"}}},
                               "b": {"objects": {"probe_bed": {"name": "probe bed"}}, "items": {"stick": {"name": "stick"}}}})
    with pytest.raises(ValueError, match=r"'probe_bed'.*packs/a/objects\.json.*packs/b/objects\.json"):
        registry.load_objects(data)
    with pytest.raises(ValueError, match=r"'stick'.*in items\.json.*packs/b/items\.json"):
        Catalog.load(data)
    data = data_dir({"c": {"recipes": [{"output": "rope", "inputs": {"stick": 2}}]}})
    with pytest.raises(ValueError, match=r"'rope'.*in recipes\.json.*packs/c/recipes\.json"):
        Catalog.load(data)

    alias, _ = core_alias()
    with registry.sandbox():  # registering at run time: the first owner and the second are both named
        with pytest.raises(ValueError, match=r"'tree'.*objects\.json.*test_registry"):
            registry.register_kinds({"tree": {"name": "tree"}})
        with pytest.raises(ValueError, match=r"'read'.*swarmworld\.mind\.techniques.*test_registry"):
            registry.register_technique(Technique("read", "read (target): again.", lambda w, c: None))
        with pytest.raises(ValueError, match=r"'gather'.*swarmworld\.world\.actions.*test_registry"):
            registry.register_verb("gather", lambda w, c, it: None)
        with pytest.raises(ValueError, match=rf"'{alias}'.*swarmworld\.world\.actions.*test_registry"):
            registry.register_verb("probe_fell", lambda w, c, it: None, aliases=(alias,))  # already a core verb's word
        registry.register_system("probe tides", 5, lambda sim, t: None)
        with pytest.raises(ValueError, match=r"'probe tides'.*test_registry.*test_registry"):
            registry.register_system("probe tides", 7, lambda sim, t: None)

        def line(world, c):
            return None

        registry.register_perception(line)
        with pytest.raises(ValueError, match="registered twice"):
            registry.register_perception(line)
    assert "probe_fell" not in actions.VERBS and not any(s.name == "probe tides" for s in registry.SYSTEMS)


def test_generic_yields_gather_deplete_regrow(data_dir):
    w = grass_world(Catalog.load(data_dir({"reeds": REED_PACK})))
    c = creature(w, "Tam", 5, 5)
    with only_this_test():
        registry.register_kinds(REED_PACK["objects"], "packs/reeds/objects.json")  # only data: no code for these
        assert "probe_bed" in actions.GATHERABLE and actions.ITEM_SOURCES["probe_reed"] == {"probe_bed"}
        bed = w.add_object("probe_bed", 6, 5)
        assert bed.name == "probe bed" and w.walkable(6, 5)

        res = act(w, c, action="gather", target="probe reeds")
        assert res.ok and c.inventory["probe_reed"] == 2 and bed.kind == "probe_bed" and bed.data["uses"] == 1
        res = act(w, c, action="gather")  # nothing named: whatever beside you still gives something
        assert res.ok and c.inventory["probe_reed"] == 4
        assert bed.kind == "probe_stubble" and bed.name == "cut probe reeds" and bed.data["regrow_at"] == w.tick + 100
        res = act(w, c, action="gather", target="probe stubble")
        assert not res.ok and "nothing left" in res.message and c.inventory["probe_reed"] == 4

        sim = Simulation(w)
        for _ in range(110):
            sim.tick()
        assert bed.kind == "probe_bed" and not {"uses", "regrow_at", "regrows"} & set(bed.data)
        res = act(w, c, action="gather", target="probe reed")  # the item's name finds what gives it
        assert res.ok and c.inventory["probe_reed"] == 6 and bed.data["uses"] == 1


def test_generic_yields_need_their_tool_and_can_run_out():
    w = grass_world()
    c = creature(w, "Tam", 5, 5)
    with registry.sandbox():
        registry.register_kinds({"probe_nodule": {
            "name": "probe nodule", "aliases": ["probe nodule"], "blocking": True,
            "yields": {"items": {"flint": [1, 1], "stone": [0, 0]}, "tool": "stone_pickaxe", "uses": 1}}})
        nodule = w.add_object("probe_nodule", 6, 5)
        assert not w.walkable(6, 5)
        res = act(w, c, action="gather", target="probe nodule")
        assert not res.ok and "stone pickaxe" in res.message and nodule.id in w.objects
        c.inventory["stone_pickaxe"] = 1
        res = act(w, c, action="gather", target="probe nodule")
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
        assert pack_modules(probe_humming=HUM_PACK) == ["probe_humming"]
        assert actions.VERBS[-1] == "probe_hum" and "probe_hum" in INTENTION_SCHEMA["properties"]["action"]["enum"]
        it = parse_intention({"action": "probe_whistle", "text": "softly"})
        assert it.action == "probe_hum"
        res = apply_intention(w, c, it)
        assert res.ok and res.message == "You hum softly."
        assert "probe_hum (text): hum a tune for those around you." in relevant(w, c)
        assert set(actions.VERBS) == set(CORE_VERBS) | {v for t in TECHNIQUES for v in t.verbs} | {"recall"}
    assert "probe_hum" not in actions.VERBS and "probe_hum" not in actions.HANDLERS
    assert "probe_whistle" not in actions.VERB_ALIASES and not any(t.name == "probe_hum" for t in TECHNIQUES)
    assert parse_intention({"action": "probe_hum"}) is None


def test_pack_verb_takes_a_core_alias_only_when_it_says_so():
    """A word that so far only meant a core verb (as "build" means craft) becomes a pack's verb only with
    replaces_alias=True; otherwise it's a clash like any other, naming both."""
    alias, verb = core_alias()
    with registry.sandbox():
        with pytest.raises(ValueError, match=rf"'{alias}'.*swarmworld\.world\.actions.*test_registry.*replaces_alias"):
            registry.register_verb(alias, lambda world, cr, it: None)
        assert parse_intention({"action": alias}).action == verb and alias not in actions.VERBS
        with pytest.raises(ValueError, match="isn't an alias of a core verb"):
            registry.register_verb("probe_new", lambda world, cr, it: None, replaces_alias=True)
        registry.register_verb("probe_owner", lambda world, cr, it: None, aliases=("probe_word",))
        with pytest.raises(ValueError, match=r"'probe_word'.*test_registry.*test_registry"):  # a pack's word stays its own
            registry.register_verb("probe_word", lambda world, cr, it: None, replaces_alias=True)


def test_pack_verb_can_take_over_a_core_alias():
    w = grass_world()
    c = creature(w, "Tam", 5, 5)
    alias, verb = core_alias()
    with registry.sandbox():
        registry.register_verb(alias, lambda world, cr, it: actions.ActionResult(True, f"You start a {it.target}."),
                               replaces_alias=True)
        assert parse_intention({"action": alias}).action == alias and alias not in actions.VERB_ALIASES
        assert registry.owner("verb", alias).endswith("test_registry")
        assert act(w, c, action=alias, target="hut").message == "You start a hut."
    assert parse_intention({"action": alias}).action == verb and registry.owner("verb", alias) == "swarmworld.world.actions"


def test_registered_system_runs_on_its_interval():
    w = grass_world()
    creature(w, "Tam", 5, 5)
    sim = Simulation(w)
    calls = []
    with only_this_test():
        registry.register_system("probe every 7", 7, lambda s, t: calls.append(("seven", t, s is sim)))
        registry.register_system("probe every tick", 1, lambda s, t: calls.append(("one", t, s is sim)))
        with pytest.raises(ValueError):
            registry.register_system("probe never", 0, lambda s, t: None)
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
    installed = list(registry.PERCEPTIONS)
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

    with only_this_test():
        before = perceive(w, c, heard=['Mara says: "hello"'])
        for fn in (quiet, first, blank, second, third):
            registry.register_perception(fn)
        text = perceive(w, c, heard=['Mara says: "hello"'])
    lines = text.splitlines()
    carry = next(i for i, line in enumerate(lines) if line.startswith("You carry"))
    assert lines[carry - 3:carry] == ['You hear: Mara says: "hello"', "The air smells of rain.", "Bees hum in the clover."]
    assert "third" not in text and called == ["quiet", "first", "blank", "second"]  # no room left: not even asked
    assert [line for line in lines if line not in ("The air smells of rain.", "Bees hum in the clover.")] == before.splitlines()
    assert registry.PERCEPTIONS == installed


def test_perception_priority_keeps_the_best_lines():
    w = grass_world()
    c = creature(w, "Tam", 5, 5)
    with only_this_test():
        for text, priority in (("Line A.", None), ("Line B.", 10), ("Line C.", 50), ("Line D.", 90)):
            def fn(world, cr, text=text):
                return text
            registry.register_perception(fn) if priority is None else registry.register_perception(fn, priority=priority)
        lines = perceive(w, c).splitlines()
    carry = next(i for i, line in enumerate(lines) if line.startswith("You carry"))
    assert lines[carry - 2:carry] == ["Line B.", "Line A."]  # lower priority first; then first registered first
    assert "Line C." not in lines and "Line D." not in lines


# ------------------------------------------------------------------ sound
def test_sound_reaches_listeners_with_direction():
    w = grass_world()
    sim = Simulation(w)
    chopper = creature(w, "Tam", 10, 10)
    south = creature(w, "Mara", 10, 16)  # 6 steps south of the sound
    beside = creature(w, "Odo", 11, 10)
    far = creature(w, "Pell", 10, 19)  # 9 steps: out of earshot
    with only_this_test():  # no pack's own sounds or lines in the way
        assert {"chop", "splash", "thunder", "crickets", "animal:<kind>"} <= set(registry.SOUND_KINDS)  # advisory names
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
        lines = perceive(w, south, heard=['Odo says: "over here"', *heard]).splitlines()
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
    with only_this_test():
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


# ------------------------------------------------------------------ robustness, state and placement
def test_failing_pack_callbacks_never_stop_the_world(caplog):
    ran = []

    def broken_system(sim, t):
        raise RuntimeError("the system broke")

    def broken_line(world, c):
        raise RuntimeError("the line broke")

    def broken_trigger(world, c):
        raise RuntimeError("the trigger broke")

    with only_this_test(), caplog.at_level(logging.ERROR, logger="swarmworld.packs"):
        registry.register_system("probe broken", 1, broken_system)
        registry.register_system("probe fine", 1, lambda sim, t: ran.append(t))  # still runs after the broken one
        registry.register_perception(broken_line)
        registry.register_perception(lambda world, c: "Still here.")
        registry.register_verb("probe_x", lambda world, c, it: None)
        registry.register_technique(Technique("probe_x", "probe_x: do x.", broken_trigger))
        st = ServerState(seed=7)
        node, cs = st.register_node(NullWS(), {"node": "t", "slots": 2, "models": [{"tag": "mock", "creatures": 1}]})
        for _ in range(3):
            st.sim.tick()
        jobs = st.plan_dispatch()
        assert relevant(st.world, cs[0]) == [line for line in relevant(st.world, cs[0]) if "probe_x" not in line]
    assert len(ran) == 3 and jobs and "Still here." in jobs[0][1]["messages"][1]["content"]
    for name in ("broken_system", "broken_line", "broken_trigger"):
        logged = [r for r in caplog.records if name in r.getMessage()]
        assert len(logged) == 1, name  # three failures (or more) in a minute: logged once
        assert "test_registry" in logged[0].getMessage() and logged[0].exc_info


def test_pack_state_is_saved_and_old_saves_start_empty(tmp_path, prepack_save):
    with only_this_test():
        st = ServerState(seed=7)
        c = st.new_creature("mock")
        assert c.ext == {} and st.world.ext == {}
        c.ext["probe"] = {"joy": 70, "played_with": ["Mara"]}
        st.world.ext["probe"] = {"seeded": True, "spots": [[1, 2]]}
        save(st, tmp_path / "w.json")
        st2 = ServerState(seed=99)
        restore(st2, tmp_path / "w.json")
        assert st2.world.creatures[c.id].ext == {"probe": {"joy": 70, "played_with": ["Mara"]}}
        assert st2.world.ext == {"probe": {"seeded": True, "spots": [[1, 2]]}}
        st3 = ServerState(seed=1)
        restore(st3, prepack_save)
        assert st3.world.ext == {} and all(cr.ext == {} for cr in st3.world.creatures.values())


def test_populate_runs_on_generation_and_after_restore(tmp_path, prepack_save):
    calls = []

    def populate(world, rng, fresh):
        calls.append((fresh, isinstance(rng, random.Random), len(world.creatures)))
        mine = world.ext.setdefault("probe", {})
        if not mine.get("placed"):  # idempotent: a restored world already has its sign
            x, y = world.spawn_point()
            world.add_object("sign", x, y, text="probe sign")
            mine["placed"] = True

    def probe_signs(world):
        return sum(1 for o in world.objects.values() if o.data.get("text") == "probe sign")

    with only_this_test():
        registry.register_populate("probe", populate)
        with pytest.raises(ValueError, match=r"'probe'.*test_registry.*test_registry"):
            registry.register_populate("probe", populate)
        w = generate_world(5)
        assert calls == [(True, True, 0)] and probe_signs(w) == 1 and w.ext["probe"]["placed"]
        st = ServerState(seed=5)
        save(st, tmp_path / "w.json")
        st2 = ServerState(seed=6)
        restore(st2, tmp_path / "w.json")
        assert calls[-1] == (False, True, 0) and probe_signs(st2.world) == 1
        restore(st2, prepack_save)  # a save from before the pack: placed now, once
        assert calls[-1] == (False, True, 6) and probe_signs(st2.world) == 1


def test_pack_item_names_that_shadow_others_warn(data_dir, caplog):
    data = data_dir({"a": {"items": {"probe_twig": {"name": "probe twig", "aliases": ["stick"]}}}})
    with caplog.at_level(logging.WARNING, logger="swarmworld.packs"):
        cat = Catalog.load(data)
    assert cat.resolve("stick") == "stick" and cat.resolve("probe twig") == "probe_twig"  # the first item keeps a name
    assert "'stick'" in caplog.text and "probe_twig" in caplog.text and "packs/a/items.json" in caplog.text


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
    names: dict[str, str] = {}
    for it in cat.items.values():  # no item's name or alias is already another item's
        for name in {_norm(n) for n in (it.id, it.name, *it.aliases)}:
            assert names.setdefault(name, it.id) == it.id, f"'{name}' names both {names[name]} and {it.id}"
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
