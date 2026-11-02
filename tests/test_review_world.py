import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("review_world", Path(__file__).parent.parent / "scripts" / "review_world.py")
rw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rw)


def act(name, model, harness, action, ok=True, noop=False, tin=1000, cached=400, tout=50, **extra):
    return {"name": name, "model": model, "kind": "act", "harness": harness, "output": {"action": action, "target": "x"},
            "result": {"ok": ok, "noop": noop, "message": ""}, "tokens_in": tin, "cached_tokens": cached,
            "tokens_out": tout, **extra}


def test_split_report_groups_by_model_and_layers():
    thinks = [act("Ann", "m1", ["plan", "recall"], "gather", recalled=["a"]),
              act("Ann", "m1", ["recall", "plan"], "gather", ok=False, tin=800, cached=0, tout=150),
              act("Ann", "m1", ["plan", "recall"], "gather", noop=True),
              act("Ann", "m1", ["plan", "recall"], "gather"),
              {"name": "Ann", "model": "m1", "kind": "reflect", "harness": ["plan", "recall"]},
              act("Bob", "m1", [], "walk_to"),
              act("Cy", "m2", [], "eat")]
    events = [{"kind": "collapse", "actor": "Bob", "text": "Bob collapses"},
              {"kind": "craft", "actor": "Ann", "text": "Ann made a rope"},
              {"kind": "craft", "actor": "Ann", "text": "Ann made a net"}]
    r = rw.split_report(thinks, events)
    assert set(r) == {("m1", "plan+recall"), ("m1", "none"), ("m2", "none")}
    a = r[("m1", "plan+recall")]
    assert a["replies"] == 4
    assert a["success_rate"] == 0.5  # 2 ok of 4 (one failed, one noop)
    assert a["noop_rate"] == 0.25
    assert a["streaks"] == 1
    assert a["failures"] == 1
    assert a["crafted"] == 2
    assert a["recall_uses"] == 1
    assert a["collapses"] == 0
    assert a["uncached_in"] == (600 + 800 + 600 + 600) / 4
    assert a["tokens_out"] == (50 + 150 + 50 + 50) / 4
    assert r[("m1", "none")]["collapses"] == 1
