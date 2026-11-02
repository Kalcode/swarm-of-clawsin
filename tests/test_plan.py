from swarmworld.mind.memory import Memory, same_plan
from swarmworld.mind.prompts import INTENTION_SCHEMA, INTENTION_SCHEMA_PLAN, build_act_messages
from swarmworld.server.harness import Harness
from swarmworld.server.persistence import restore, save
from swarmworld.server.state import ServerState
from swarmworld.world.actions import parse_intention, step_activity

STEPS = ["get 3 plant fiber", "make rope", "get 2 stone"]


class NullWS:
    closed = False

    async def send_json(self, _):
        pass


def setup(layers=("plan",)):
    st = ServerState(seed=7, harness=Harness(set(layers), set(layers)))
    node, cs = st.register_node(NullWS(), {"node": "t", "slots": 2, "models": [{"tag": "mock", "creatures": 1}]})
    return st, node, cs[0]


def act(st, node, c, output):
    job = st.make_job(node, c)
    st.handle_result(node, {"job": job["job"], "ok": True, "output": output})
    return job


def test_set_plan_and_advance():
    m = Memory()
    assert m.set_plan(STEPS)
    assert m.advance() == "get 3 plant fiber" and m.advance() == "make rope"
    assert m.plan_step == 2
    assert m.advance() == "get 2 stone"
    assert m.plan == [] and m.plan_step == 0
    assert m.advance() is None


def test_reworded_plan_keeps_progress():
    m = Memory()
    m.set_plan(STEPS)
    m.advance()
    assert not m.set_plan(["Get 3 plant fibers", "Make rope.", "get 2 stones"])
    assert m.plan_step == 1 and m.plan == STEPS
    assert m.set_plan(["find water", "drink"]) and m.plan_step == 0
    assert same_plan(["a b"], ["A b!"]) and not same_plan(["a"], ["a", "b"])


def test_parse_limits():
    it = parse_intention({"action": "say", "plan": ["x" * 200] + ["b"] * 9, "step_done": True})
    assert len(it.plan) == 5 and len(it.plan[0]) == 80 and it.step_done
    assert parse_intention({"action": "say"}).plan == []


def test_goal_change_keeps_the_plan():
    st, node, c = setup()
    mem = st.memory(c.id)
    mem.set_plan(STEPS)
    act(st, node, c, {"action": "say", "text": "hi", "goal": "something else entirely", "plan": []})
    assert mem.goal == "something else entirely" and mem.plan == STEPS and mem.plan_step == 0


def test_new_plan_through_handle_result():
    st, node, c = setup()
    act(st, node, c, {"action": "say", "text": "hi", "plan": STEPS})
    assert st.memory(c.id).plan == STEPS


def test_step_done_advances_only_on_success():
    st, node, c = setup()
    mem = st.memory(c.id)
    mem.set_plan(STEPS)
    act(st, node, c, {"action": "say", "text": "hi", "step_done": True})
    assert mem.plan_step == 1
    act(st, node, c, {"action": "eat", "target": "unobtainium", "step_done": True})
    assert mem.plan_step == 1
    act(st, node, c, {"action": "say", "text": "again", "step_done": False})
    assert mem.plan_step == 1


def test_finishing_the_plan_is_remembered():
    st, node, c = setup()
    mem = st.memory(c.id)
    mem.set_plan(["only step"])
    act(st, node, c, {"action": "say", "text": "hi", "step_done": True})
    assert mem.plan == [] and any("You finished your plan: only step" in e.text for e in mem.entries)


def test_step_done_on_a_walk_advances_when_it_arrives():
    st, node, c = setup()
    w = st.world
    mem = st.memory(c.id)
    mem.set_plan(STEPS)
    far = max((o for o in w.objects.values() if o.kind in ("tree", "rock", "pine")),
              key=lambda o: abs(o.x - c.x) + abs(o.y - c.y))
    act(st, node, c, {"action": "walk_to", "target": far.kind, "step_done": True})
    assert c.activity and c.activity.get("step_done")
    assert mem.plan_step == 0
    for _ in range(400):
        res = step_activity(w, c)
        if res:
            st._on_activity_result(c, res)
        if not c.activity:
            break
    assert mem.plan_step == 1


def test_plan_only_in_plan_layer_prompts():
    st, node, c = setup()
    mem = st.memory(c.id)
    mem.set_plan(STEPS)
    mem.advance()
    on = build_act_messages(st.world, c, mem, "You see nothing.", layers={"plan"})[1]["content"]
    assert "- Your plan: 1. done: get 3 plant fiber. 2. NOW: make rope. 3. get 2 stone." in on
    assert "Set step_done to true" in on
    off = build_act_messages(st.world, c, mem, "You see nothing.")[1]["content"]
    assert not any(w in off for w in ("Your plan", "No plan yet", "NOW:", "step_done"))
    none = build_act_messages(st.world, c, Memory(), "x", layers={"plan"})[1]["content"]
    assert "- No plan yet. If your goal takes several steps, write them in plan (up to 5 short steps)." in none

    assert st.make_job(node, c)["schema"] is INTENTION_SCHEMA_PLAN
    st2, node2, c2 = setup(layers=())
    assert st2.make_job(node2, c2)["schema"] is INTENTION_SCHEMA


def test_plan_schema_extends_without_mutating():
    assert "plan" not in INTENTION_SCHEMA["properties"]
    p = INTENTION_SCHEMA_PLAN["properties"]
    assert p["plan"]["maxItems"] == 5 and p["step_done"]["type"] == "boolean"
    assert {"plan", "step_done"} <= set(INTENTION_SCHEMA_PLAN["required"])
    assert "plan" not in INTENTION_SCHEMA["required"]


def test_creature_detail_shows_plan():
    st, node, c = setup()
    st.memory(c.id).set_plan(STEPS)
    d = st.creature_detail(c.id)
    assert d["plan"] == STEPS and d["plan_step"] == 0


def test_plan_survives_restart(tmp_path):
    st, node, c = setup()
    mem = st.memory(c.id)
    mem.set_plan(STEPS)
    mem.advance()
    save(st, tmp_path / "w.json")
    st2 = ServerState(seed=7)
    restore(st2, tmp_path / "w.json")
    m2 = st2.memory(c.id)
    assert m2.plan == STEPS and m2.plan_step == 1


def test_reflection_sees_the_plan_only_in_plan_layer():
    from swarmworld.mind.prompts import build_reflect_messages
    st, node, c = setup()
    mem = st.memory(c.id)
    mem.set_plan(STEPS)
    mem.advance()
    on = build_reflect_messages(c, mem, {"plan"})[1]["content"]
    assert "Your plan: 1. done: get 3 plant fiber. 2. NOW: make rope." in on and "Say if it should change" in on
    assert build_reflect_messages(c, mem)[1]["content"] == build_reflect_messages(c, mem, set())[1]["content"]
    assert "Your plan" not in build_reflect_messages(c, mem)[1]["content"]
    mem.thinks_since_reflect = mem.entries_since_reflect = 12
    assert "Your plan:" in st.make_job(node, c)["messages"][1]["content"]


def test_a_noop_does_not_finish_a_step():
    st, node, c = setup()
    mem = st.memory(c.id)
    mem.set_plan(STEPS)
    from swarmworld.world.actions import ActionResult
    import swarmworld.server.state as S
    orig = S.apply_intention
    S.apply_intention = lambda w, cr, it: ActionResult(True, "Nothing changes.", noop=True)
    try:
        act(st, node, c, {"action": "say", "text": "x", "step_done": True})
    finally:
        S.apply_intention = orig
    assert mem.plan_step == 0


def test_plan_layer_acts_have_room_for_a_plan():
    for layers, want in ((("plan",), 360), (("disclose", "recall"), 260), ((), 260)):
        st, node, c = setup(layers)
        job = st.make_job(node, c)
        assert job["kind"] == "act" and job["max_tokens"] == want, layers
