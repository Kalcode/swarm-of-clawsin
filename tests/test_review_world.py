import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("review_world", Path(__file__).parent.parent / "scripts" / "review_world.py")
rw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rw)


def act(cid, name, model, harness, action, ok=True, noop=False, tin=1000, cached=400, tout=50, **extra):
    return {"creature": cid, "name": name, "model": model, "kind": "act", "harness": harness, "output": {"action": action, "target": "x"},
            "result": {"ok": ok, "noop": noop, "message": ""}, "tokens_in": tin, "cached_tokens": cached,
            "tokens_out": tout, **extra}


def test_split_report_groups_by_model_and_layers():
    thinks = [act("c1", "Ann", "m1", ["plan", "recall"], "gather", recalled=["a"]),
              act("c1", "Ann", "m1", ["recall", "plan"], "gather", ok=False, tin=800, cached=0, tout=150),
              act("c1", "Ann", "m1", ["plan", "recall"], "gather", noop=True),
              act("c1", "Ann", "m1", ["plan", "recall"], "gather"),
              act("c1", "Ann", "m1", ["plan", "recall"], "recall"),
              {"creature": "c1", "name": "Ann", "model": "m1", "kind": "reflect", "harness": ["plan", "recall"]},
              act("c2", "Bob", "m1", [], "walk_to"),
              act("c3", "Cy", "m2", [], "eat")]
    events = [{"kind": "collapse", "actor": "c2", "text": "Bob collapses"},
              {"kind": "craft", "actor": "c1", "text": "Ann made a rope"},
              {"kind": "craft", "actor": "c1", "text": "Ann made a net"}]
    r = rw.split_report(thinks, events)
    assert set(r) == {("m1", "plan+recall"), ("m1", "none"), ("m2", "none")}
    a = r[("m1", "plan+recall")]
    assert a["replies"] == 5
    assert a["success_rate"] == 0.6  # 3 ok of 5 (one failed, one noop)
    assert a["noop_rate"] == 0.2
    assert a["streaks"] == 1
    assert a["failures"] == 1
    assert a["crafted"] == 2
    assert a["recall_uses"] == 1
    assert a["collapses"] == 0
    assert a["uncached_in"] == (600 + 800 + 600 + 600 + 600) / 5
    assert a["tokens_out"] == (50 + 150 + 50 + 50 + 50) / 5
    assert r[("m1", "none")]["collapses"] == 1
