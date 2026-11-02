import random

from swarmworld.mind.memory import Memory
from swarmworld.mind.prompts import INTENTION_SCHEMA, SYSTEM_PROMPT, build_act_messages, build_reflect_messages, make_persona
from swarmworld.world.actions import VERBS
from swarmworld.world.catalog import Catalog
from swarmworld.world.model import Creature, World


def _world():
    return World(10, 10, [["g"] * 10 for _ in range(10)], Catalog.load())


def test_system_prompt_static():
    w = _world()
    a = Creature("c1", "Tam", 1, 1, persona={"traits": ["bold", "kind"], "drive": "curious"})
    b = Creature("c2", "Mara", 2, 2, persona={"traits": ["quiet", "proud"], "drive": "builder"})
    ma = build_act_messages(w, a, Memory(), "You see grass.")
    mb = build_act_messages(w, b, Memory(), "You see a tree.")
    assert ma[0] == mb[0] and ma[0]["content"] == SYSTEM_PROMPT
    for v in VERBS:
        assert v in SYSTEM_PROMPT
    assert set(INTENTION_SCHEMA["required"]) == set(INTENTION_SCHEMA["properties"])


def test_messages_order():
    w = _world()
    c = Creature("c1", "Tam", 1, 1, persona={"traits": ["bold", "kind"], "drive": "curious"})
    c.known_recipes = {"rope"}
    m = Memory(goal="make an axe")
    m.add(1, "You gathered 2 stick.")
    msgs = build_act_messages(w, c, m, "PERCEPTION-TEXT", "heard")
    user = msgs[1]["content"]
    assert msgs[0]["role"] == "system"
    assert user.index("make an axe") < user.index("You gathered 2 stick.") < user.index("PERCEPTION-TEXT")
    assert user.rstrip().endswith("Reply with one JSON object.")
    assert "3 plant fiber -> rope" in user


def test_memory_cap_and_reflection():
    m = Memory()
    for i in range(80):
        m.add(i, f"event {i}", importance=3 if i == 0 else 1)
    assert len(m.entries) == 60
    assert m.entries[0].text == "event 0"  # important memories survive
    m.thinks_since_reflect = 12
    assert m.needs_reflection()
    m.apply_reflection("I learned that sticks come from trees.")
    assert not m.needs_reflection() and "sticks" in m.summary
    msgs = build_reflect_messages(Creature("c1", "Tam", 1, 1), m)
    assert "Tam" in msgs[1]["content"]


def test_persona_unique_names():
    rng = random.Random(1)
    used = set()
    for _ in range(50):
        p = make_persona(rng, used)
        assert p["name"] not in used
        used.add(p["name"])


def test_curated_recent_limits_small_talk():
    from swarmworld.mind.prompts import curated_recent
    m = Memory()
    m.add(1, "You gathered 3 stick.")
    for i in range(12):
        m.add(2 + i, f'Gil says to Orla: "Lovely day {i}!"')
    m.add(20, "You made 1 campfire.")
    rec = curated_recent(m)
    assert sum("says" in r for r in rec) == 3
    assert rec[0] == "You gathered 3 stick." and rec[-1] == "You made 1 campfire."


def test_recipe_list_in_prompt_is_capped_and_relevant():
    from swarmworld.mind.prompts import MAX_RECIPES_IN_PROMPT, known_recipes_for_prompt
    w = _world()
    c = Creature("c1", "Tam", 1, 1)
    c.known_recipes = {r.output for r in w.catalog.recipes}
    c.inventory["fish"] = 1
    known = known_recipes_for_prompt(w, c)
    assert len(known) == MAX_RECIPES_IN_PROMPT and "cooked fish" in known[0]


def test_temperament_shapes_the_prompt():
    from swarmworld.mind.prompts import make_persona
    rng = random.Random(5)
    p = make_persona(rng, set())
    assert {"initiative", "role", "novelty"} <= set(p)
    w = _world()
    c = Creature("c1", p["name"], 1, 1, persona=p)
    user = build_act_messages(w, c, Memory(), "PERCEPTION")[1]["content"]
    assert any(k in user for k in ("organize others", "join whatever", "someone who needs", "on your own"))
    assert "speech" in INTENTION_SCHEMA["required"]
