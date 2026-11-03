from collections import Counter

from swarmworld.mind.prompts import SYSTEM_PROMPT, SYSTEM_PROMPT_CORE, build_act_messages
from swarmworld.mind.memory import Memory
from swarmworld.mind.techniques import CORE_VERBS, TECHNIQUES, lore, relevant
from swarmworld.server.harness import Harness
from swarmworld.server.state import ServerState
from swarmworld.world import registry
from swarmworld.world.actions import VERBS, Intention, apply_intention
from swarmworld.world.catalog import Catalog
from swarmworld.world.model import START_TICK, Creature, World
from swarmworld.world.registry import Technique

HEADER = "Things you could also do here:"


class NullWS:
    closed = False

    async def send_json(self, _):
        pass


def tips_section(content: str) -> list[str]:
    """The lines listed under "Things you could also do here:" (none when the section isn't there)."""
    if HEADER not in content:
        return []
    tips = []
    for line in content.split(HEADER, 1)[1].splitlines()[1:]:
        if not line.startswith("- "):
            break
        tips.append(line[2:])
    return tips


def pack_technique(name: str, score: float | None, line: str | None = None) -> str:
    """Register a pack verb and its technique (call inside registry.sandbox()); returns the technique's line."""
    line = line or f"{name}: a pack's thing to do."
    registry.register_verb(name, lambda world, c, it: None)
    registry.register_technique(Technique(name, line, lambda world, c: score))
    return line


def make_world():
    w = World(40, 40, [["g"] * 40 for _ in range(40)], Catalog.load())
    w.tick = START_TICK + 100
    c = Creature("c1", "Tam", 10, 10, asleep=False)
    w.creatures[c.id] = c
    return w, c


def test_every_verb_is_core_or_a_technique():
    technique_verbs = {v for t in TECHNIQUES for v in t.verbs}
    assert set(VERBS) == set(CORE_VERBS) | technique_verbs | {"recall"}
    assert set(CORE_VERBS) | technique_verbs <= set(VERBS)


def test_core_prompt_is_much_shorter():
    assert len(SYSTEM_PROMPT_CORE) <= 0.75 * len(SYSTEM_PROMPT)  # 0.74 since the manners lines stay in the core


def test_core_prompt_keeps_the_manners():
    for line in ("Only name things you can actually see, carry or remember.",
                 "Skip empty pleasantries; talk about useful things: where food and materials are, what you made and how, "
                 "what you need, plans to work together."):
        assert line in SYSTEM_PROMPT and line in SYSTEM_PROMPT_CORE


def test_terminal_in_sight_discloses_program():
    w, c = make_world()
    assert not any("program" in line for line in relevant(w, c))
    w.add_object("terminal", 13, 10)
    assert any("program" in line for line in relevant(w, c))


def test_at_most_five_best_first():
    w, c = make_world()
    for kind, x in (("basket", 11), ("sign", 9), ("campfire", 10)):
        w.add_object(kind, x, 11 if kind != "campfire" else 12)
    other = Creature("c2", "Mara", 12, 10, asleep=False)
    w.creatures[other.id] = other
    c.inventory.update({"wheat_seeds": 2, "workbench": 1})
    lines = relevant(w, c)
    assert len(lines) == 5
    scored = sorted(((t.trigger(w, c), t.line, t.pack) for t in TECHNIQUES if t.trigger(w, c) is not None), reverse=True)
    packs = [line for _, line, pack in scored if pack][:2]  # the packs' best two keep their slots
    core = [line for _, line, pack in scored if not pack][:5 - len(packs)]
    assert packs and lines == [line for _, line, _ in scored if line in packs + core]
    assert len(relevant(w, c, limit=2)) == 2


def test_other_triggers():
    w, c = make_world()
    assert relevant(w, c) == []
    c.inventory.update({"stick": 1, "stone": 1})
    assert any("invent" in line for line in relevant(w, c))
    c.stats[f"invented_day_{w.clock()['day']}"] = 1
    assert not any("invent" in line for line in relevant(w, c))
    w.drop_items(10, 10, __import__("collections").Counter({"stick": 2}))
    assert any("pick_up" in line for line in relevant(w, c))


def test_lore_covers_techniques():
    assert {line for _, line in lore()} >= {t.line for t in TECHNIQUES}


def test_disclose_layer_uses_core_prompt():
    for on in (True, False):
        layers = {"disclose"} if on else set()
        st = ServerState(seed=7, harness=Harness(set(layers), set(layers)))
        node, cs = st.register_node(NullWS(), {"node": "t", "slots": 2, "models": [{"tag": "mock", "creatures": 1}]})
        c = cs[0]
        st.world.add_object("terminal", c.x + 1, c.y)
        msgs = st.make_job(node, c)["messages"]
        assert msgs[0]["content"] == (SYSTEM_PROMPT_CORE if on else SYSTEM_PROMPT)
        tips = tips_section(msgs[1]["content"])
        if on:
            assert any("program" in t for t in tips)
        else:  # without the layer only packs' techniques are listed (their verbs aren't in the system prompt)
            assert not {t.line for t in TECHNIQUES if not t.pack} & set(tips)


def test_pack_techniques_reach_every_creature():
    w, c = make_world()
    w.add_object("terminal", 13, 10)  # the core program (7.0) and read (6.0) techniques fit too
    with registry.sandbox():
        skim = pack_technique("probe_skim", 8.0, "probe_skim: skip a stone across the water.")
        pack_technique("probe_idle", None)  # registered, but nothing makes it fit now
        assert {t.name: t.pack for t in TECHNIQUES if t.name in ("program", "probe_skim")} == {"program": False, "probe_skim": True}
        off = build_act_messages(w, c, Memory(), "PERCEPTION", layers=set())
        on = build_act_messages(w, c, Memory(), "PERCEPTION", layers={"disclose"})
    assert off[0]["content"] == SYSTEM_PROMPT and tips_section(off[1]["content"]) == [skim]
    assert on[0]["content"] == SYSTEM_PROMPT_CORE
    assert tips_section(on[1]["content"]) == [skim, "program (text): enter Lua code into a terminal beside you.",
                                              "read (target): read a sign, carving, tablet or terminal."]
    assert HEADER not in build_act_messages(w, c, Memory(), "PERCEPTION", layers=set())[1]["content"]  # packs gone


def test_pack_techniques_keep_the_limit_and_ranking():
    w, c = make_world()
    with registry.sandbox():
        lines = [pack_technique(f"probe_{n}", score) for n, score in enumerate((3.0, 9.0, 1.0, 7.5, 5.0, 8.0))]

        def shown(layers):
            return tips_section(build_act_messages(w, c, Memory(), "PERCEPTION", layers=layers)[1]["content"])

        best = [lines[n] for n in (1, 5, 3, 4, 0)]  # the five highest scores, highest first
        assert shown(set()) == best == relevant(w, c, packs_only=True)
        assert shown({"recall"}) == best[:4]  # the recall layer makes room for itself: four tips
        w.add_object("terminal", 13, 10)  # program (7.0) and read (6.0) now compete, but only with the layer
        assert shown(set()) == best
        assert shown({"disclose"}) == [lines[1], lines[5], lines[3], "program (text): enter Lua code into a terminal beside you.",
                                       "read (target): read a sign, carving, tablet or terminal."]


def test_job_records_the_pack_techniques_shown():
    with registry.sandbox():
        pack_technique("probe_skim", 8.0)
        for on in (False, True):
            layers = {"disclose"} if on else set()
            st = ServerState(seed=7, harness=Harness(set(layers), set(layers)))
            node, cs = st.register_node(NullWS(), {"node": "t", "slots": 2, "models": [{"tag": "mock", "creatures": 1}]})
            c = cs[0]
            st.world.add_object("terminal", c.x + 1, c.y)
            shown = st.jobs[st.make_job(node, c)["job"]].shown
            if on:
                assert {"program", "probe_skim"} <= set(shown)
            else:
                assert shown == ["probe_skim"]


FEED_LINE = "give (target, items): feed an animal food it eats; fed often, it may come to trust you."


def test_feed_tip_is_for_animals_that_can_be_fed_not_wild_game():
    w, c = make_world()
    c.inventory["berries"] = 3
    deer = w.add_object("deer", 13, 10)  # wild game bolts when fed: hunting is its tip, with a weapon
    assert FEED_LINE not in relevant(w, c)
    w.remove_object(deer.id)
    w.add_object("sheep", 13, 10)
    assert FEED_LINE in relevant(w, c)


PLANT_LINE = "plant (target, count): plant seeds or berries in the soil beside you (needs a tool to break the soil)."
WRITE_LINE = "write (text): carve words onto a sign, tree or boulder beside you; they stay for anyone to find."


def tried(w, c, **kw):
    """Whether the action would succeed: tried on a copy of the world, so nothing here changes."""
    import copy
    w2 = copy.deepcopy(w)
    return apply_intention(w2, w2.creatures[c.id], Intention(**kw)).ok


def test_plant_tip_fits_only_when_planting_would_work():
    w, c = make_world()
    c.inventory["berries"] = 2  # plantable, but bare hands can't break the soil
    assert PLANT_LINE not in relevant(w, c) and not tried(w, c, action="plant", target="berries")
    c.inventory["hoe"] = 1
    assert PLANT_LINE in relevant(w, c) and tried(w, c, action="plant", target="berries")
    for dx in (-1, 0, 1):  # no free soil beside: water all around
        for dy in (-1, 0, 1):
            if dx or dy:
                w.tiles[10 + dy][10 + dx] = "w"
    assert PLANT_LINE not in relevant(w, c) and not tried(w, c, action="plant", target="berries")
    w2, c2 = make_world()
    c2.inventory.update({"hoe": 1, "stick": 2})  # a hoe, nothing that grows
    assert PLANT_LINE not in relevant(w2, c2) and not tried(w2, c2, action="plant", target="stick")
    c2.inventory["carrot_seeds"] = 1
    assert PLANT_LINE in relevant(w2, c2) and tried(w2, c2, action="plant", target="carrot seeds")


def test_write_tip_needs_a_surface_beside_you_and_something_to_write():
    w, c = make_world()
    c.known_recipes = {r.output for r in w.catalog.recipes if r.known_at_start}
    c.inventory["sign"] = 1  # a sign in the pack is nothing to write on until it is placed
    assert WRITE_LINE not in relevant(w, c) and not tried(w, c, action="write", text="rope: 3 plant fiber")
    w.add_object("tree", 11, 10)  # beside a tree with nothing of its own to record: no tip
    assert WRITE_LINE not in relevant(w, c)
    c.known_recipes.add("stone_axe")  # a recipe it found out itself is worth carving
    assert WRITE_LINE in relevant(w, c) and tried(w, c, action="write", text="stone axe: stick, stone, rope")
    c.stats["writing"] += 1  # written down: nothing new until it learns more
    assert WRITE_LINE not in relevant(w, c)
    w.add_object("sign", 9, 10)  # a sign beside you is always for writing on
    assert WRITE_LINE in relevant(w, c) and tried(w, c, action="write", text="berries to the east")


def crowded_world():
    """Seven core techniques fit (program, pick_up, read, feed, store, place, invent) and none of the installed packs'."""
    w, c = make_world()
    w.add_object("terminal", 14, 10)
    w.drop_items(11, 11, Counter({"stick": 2}))
    w.add_object("sheep", 10, 14)
    w.add_object("basket", 7, 10)
    c.inventory.update({"plant_fiber": 2, "workbench": 1})
    return w, c


def test_pack_tips_keep_their_slots_among_many_core_tips():
    w, c = crowded_world()
    core = relevant(w, c, limit=7)
    assert len(core) == 7 and not {t.line for t in TECHNIQUES if t.pack} & set(core)
    with registry.sandbox():
        low = [pack_technique(f"probe_{n}", s) for n, s in enumerate((1.0, 0.5, 0.2))]  # below every core score
        for limit in (5, 4, 3, 2):
            kept = min(2, limit // 2)
            assert relevant(w, c, limit) == core[:limit - kept] + low[:kept]  # best first, packs' slots kept
        assert relevant(w, c, 5, packs_only=True) == low  # without disclose: packs only, unchanged
    with registry.sandbox():
        one = pack_technique("probe_one", 0.5)
        assert relevant(w, c) == core[:4] + [one]  # a lone pack tip takes one slot; core tips fill the rest
    with registry.sandbox():
        high = [pack_technique(f"probe_{n}", s) for n, s in enumerate((9.0, 8.5, 8.0))]
        assert relevant(w, c) == high[:2] + core[:3]  # beyond their slots, packs don't push core tips out


def test_disclose_recall_creature_by_a_fire_with_company_is_shown_dance_and_play():
    w, c = crowded_world()
    w.add_object("campfire", 10, 9, lit=True, fuel=500)  # fire (5.2) fits too: eight core tips in all
    w.creatures["c2"] = Creature("c2", "Mara", 11, 10, asleep=False)  # and teach (3.0)
    dance = "dance: dance by a lit campfire; anyone beside you may join and be cheered."
    play = "play: play a game with someone beside you; you both feel the better for it."
    program = "program (text): enter Lua code into a terminal beside you."
    pick_up = "pick_up (target) / drop (target): take or leave items on the ground."

    def shown(layers):
        return tips_section(build_act_messages(w, c, Memory(), "PERCEPTION", layers=layers)[1]["content"])

    assert shown({"plan", "disclose", "recall"}) == [program, pick_up, dance, play]  # a teacher creature's layers
    assert shown({"disclose"}) == [program, pick_up, "read (target): read a sign, carving, tablet or terminal.", dance, play]
    assert shown(set()) == [dance, play]  # without disclose: the packs' only, as before
