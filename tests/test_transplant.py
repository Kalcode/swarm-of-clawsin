from swarmworld.node.__main__ import apply_adopts
from swarmworld.node.client import ModelSpec
from swarmworld.server.persistence import restore, save
from swarmworld.server.state import ServerState


class NullWS:
    closed = False

    async def send_json(self, _):
        pass


def join(st, name, models):
    node, got = st.register_node(NullWS(), {"node": name, "slots": 4, "models": models})
    return node, got


def test_a_node_can_adopt_another_models_creatures_and_bring_newcomers():
    st = ServerState(seed=7)
    old_node, olds = join(st, "mac", [{"tag": "gemma", "creatures": 2}])
    olds[0].stats["crafted"] = 5
    st.unregister_node(old_node.id)  # the old minds go away; their creatures sleep
    _, got = join(st, "pc", [{"tag": "gpt-oss", "creatures": 3, "adopt": ["gemma"]}])
    assert {c.id for c in olds} <= {c.id for c in got} and len(got) == 3  # two transplants, one newcomer
    a = olds[0]
    assert a.model == "gpt-oss" and a.minds[0]["model"] == "gemma" and not a.asleep
    assert any(e.kind == "join" and "mind" in e.text for e in st.world.events)


def test_without_adopt_old_creatures_keep_sleeping():
    st = ServerState(seed=7)
    old_node, olds = join(st, "mac", [{"tag": "gemma", "creatures": 2}])
    st.unregister_node(old_node.id)
    _, got = join(st, "pc", [{"tag": "gpt-oss", "creatures": 2}])
    assert not {c.id for c in olds} & {c.id for c in got} and all(c.model == "gemma" and c.asleep for c in olds)


def test_stats_from_the_old_mind_stay_with_the_old_model():
    st = ServerState(seed=7)
    old_node, (a,) = join(st, "mac", [{"tag": "gemma", "creatures": 1}])
    a.stats["crafted"] = 5
    st.unregister_node(old_node.id)
    join(st, "pc", [{"tag": "gpt-oss", "creatures": 1, "adopt": ["gemma"]}])
    a.stats["crafted"] += 2
    models = st.metrics.snapshot(st.world, 0)["models"]
    assert models["gemma"]["crafted"] == 5 and models["gpt-oss"]["crafted"] == 2
    st.record_history()
    h = st.history[-1]["models"]
    assert h["gemma"]["crafted"] == 5 and h["gpt-oss"]["crafted"] == 2


def test_transplants_survive_a_restart(tmp_path):
    st = ServerState(seed=7)
    old_node, (a,) = join(st, "mac", [{"tag": "gemma", "creatures": 1}])
    a.stats["crafted"] = 5
    st.unregister_node(old_node.id)
    join(st, "pc", [{"tag": "gpt-oss", "creatures": 1, "adopt": ["gemma"]}])
    save(st, tmp_path / "w.json")
    st2 = ServerState(seed=99)
    restore(st2, tmp_path / "w.json")
    b = st2.world.creatures[a.id]
    assert b.model == "gpt-oss" and b.minds[0]["model"] == "gemma" and b.stats_base["crafted"] == 5
    assert st2.metrics.snapshot(st2.world, 0)["models"]["gemma"]["crafted"] == 5


def test_adopt_flags_map_old_models_to_this_nodes_models():
    specs = [ModelSpec("gpt-oss:20b", None, 12), ModelSpec("qwen3.5:9b", None, 8)]
    apply_adopts(specs, ["gemma-4-e4b", "qwen3.5-4b=qwen3.5:9b"])
    assert specs[0].adopt == ["gemma-4-e4b"] and specs[1].adopt == ["qwen3.5-4b"]


def test_the_same_machine_can_rejoin_with_new_minds():
    st = ServerState(seed=7)
    old_node, olds = join(st, "mac", [{"tag": "gemma", "creatures": 2}])
    st.unregister_node(old_node.id)
    _, got = join(st, "mac", [{"tag": "gpt-oss", "creatures": 2, "adopt": ["gemma"]}])
    assert {c.id for c in got} == {c.id for c in olds} and all(c.model == "gpt-oss" for c in olds)


def test_a_node_can_pace_its_creatures():
    st = ServerState(seed=7)
    node, (a,) = st.register_node(NullWS(), {"node": "cloud", "slots": 4, "min_gap_ticks": 30,
                                             "models": [{"tag": "fast", "creatures": 1}]})
    a.asleep, a.wake_reason, a.last_think_tick = False, "result", st.world.tick - 10
    assert not st.plan_dispatch()  # 10 ticks since the last thought < 30
    a.last_think_tick = st.world.tick - 31
    assert [job["creature"] for _, job in st.plan_dispatch()] == [a.id]
