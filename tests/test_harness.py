import json

from swarmworld.server.harness import Harness
from swarmworld.server.persistence import restore, save
from swarmworld.server.state import ServerState
from swarmworld.world.model import Creature


class NullWS:
    closed = False

    async def send_json(self, _):
        pass


def make(model, n, start=0):
    return [Creature(f"c{model}{i + start}", f"N{i}", 0, 0, model=model) for i in range(n)]


def count(h, cs, layer="plan"):
    return sum(layer in h.layers_for(c) for c in cs)


def test_new_layer_goes_to_half_of_each_model():
    a, b = make("a", 4), make("b", 3)
    h = Harness({"plan"}, set())
    h.assign(a + b)
    assert count(h, a) == 2 and count(h, b) in (1, 2)


def test_assignment_is_stable_and_new_creatures_balance():
    a = make("a", 4)
    h = Harness({"plan"}, set())
    h.assign(a)
    before = [dict(c.harness) for c in a]
    h.assign(a)
    assert [c.harness for c in a] == before
    extra = make("a", 1, start=4)
    h.assign(a + extra)
    assert count(h, a + extra) == 3  # balanced at 2/2, so the newcomer takes the layer
    h.assign(a + extra + make("a", 1, start=5))
    assert count(h, a + extra) == 3 and sum(c.harness["plan"] is False for c in a + extra) == 2


def test_harness_all_gives_layer_to_everyone():
    cs = make("a", 3) + make("b", 2)
    h = Harness({"plan", "recall"}, {"plan"})
    h.assign(cs)
    assert all("plan" in h.layers_for(c) for c in cs)
    assert all("plan" not in c.harness for c in cs)  # no trial for a layer everyone has
    assert 0 < count(h, cs, "recall") < len(cs)


def test_unavailable_layers_are_off():
    c = make("a", 1)[0]
    c.harness["plan"] = True
    assert Harness().layers_for(c) == set()


def test_pre_harness_save_gets_a_trial_split(tmp_path):
    st = ServerState(seed=7)
    st.register_node(NullWS(), {"node": "t", "slots": 4, "models": [{"tag": "a", "creatures": 4}, {"tag": "b", "creatures": 2}]})
    save(st, tmp_path / "w.json")
    data = json.loads((tmp_path / "w.json").read_text())
    for cd in data["world"]["creatures"]:
        cd.pop("harness", None)
    (tmp_path / "w.json").write_text(json.dumps(data))
    st2 = ServerState(seed=7, harness=Harness({"plan"}, set()))
    restore(st2, tmp_path / "w.json")
    for model, n in (("a", 4), ("b", 2)):
        group = [c for c in st2.world.creatures.values() if c.model == model]
        assert count(st2.harness, group) == n // 2
    save(st2, tmp_path / "w2.json")
    st3 = ServerState(seed=7, harness=Harness({"plan"}, set()))
    restore(st3, tmp_path / "w2.json")
    assert {c.id: c.harness for c in st3.world.creatures.values()} == {c.id: c.harness for c in st2.world.creatures.values()}


def test_think_log_records_harness(tmp_path):
    st = ServerState(seed=7, run_dir=tmp_path, harness=Harness({"plan"}, {"plan"}))
    node, _ = st.register_node(NullWS(), {"node": "t", "slots": 2, "models": [{"tag": "mock", "creatures": 1}]})
    job = next(job for _, job in st.plan_dispatch())
    st.handle_result(node, {"job": job["job"], "ok": True, "output": {"action": "say", "text": "hello"}})
    line = json.loads((tmp_path / "thinks.jsonl").read_text().splitlines()[-1])
    assert line["harness"] == ["plan"]
    cid = next(iter(st.world.creatures))
    assert st.creature_detail(cid)["harness"] == ["plan"]
