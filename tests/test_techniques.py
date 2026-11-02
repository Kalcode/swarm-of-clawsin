from swarmworld.mind.prompts import SYSTEM_PROMPT, SYSTEM_PROMPT_CORE, build_act_messages
from swarmworld.mind.memory import Memory
from swarmworld.mind.techniques import CORE_VERBS, TECHNIQUES, lore, relevant
from swarmworld.server.harness import Harness
from swarmworld.server.state import ServerState
from swarmworld.world import registry
from swarmworld.world.actions import VERBS
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
    scored = sorted(((t.trigger(w, c), t.line) for t in TECHNIQUES if t.trigger(w, c) is not None), reverse=True)
    assert lines == [line for _, line in scored[:5]]
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
