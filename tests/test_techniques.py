from swarmworld.mind.prompts import SYSTEM_PROMPT, SYSTEM_PROMPT_CORE, build_act_messages
from swarmworld.mind.memory import Memory
from swarmworld.mind.techniques import CORE_VERBS, TECHNIQUES, lore, relevant
from swarmworld.server.harness import Harness
from swarmworld.server.state import ServerState
from swarmworld.world.actions import VERBS
from swarmworld.world.catalog import Catalog
from swarmworld.world.model import START_TICK, Creature, World

HEADER = "Things you could also do here:"


class NullWS:
    closed = False

    async def send_json(self, _):
        pass


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
    assert len(SYSTEM_PROMPT_CORE) <= 0.7 * len(SYSTEM_PROMPT)


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
        assert (HEADER in msgs[1]["content"]) == on
        if on:
            assert "program" in msgs[1]["content"].split(HEADER)[1]
