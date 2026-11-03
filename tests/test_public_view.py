"""What a watcher may see: every public document is an allowlist of fields, with nothing private in it."""

import json
import re
from collections import Counter
from pathlib import Path

import pytest

from swarmworld.server.almanac import VERB_ABOUT, build, prompt_lines
from swarmworld.server import public_view as pv
from swarmworld.server.public_view import (
    ALMANAC_KEYS, ALMANAC_PRIVATE, CARD_KEYS, DETAIL_KEYS, DETAIL_PRIVATE, EVENT_KEYS, METRICS_KEYS, METRICS_PRIVATE,
    OBJECT_KEYS, PACK_KEYS, PACK_PRIVATE, VERB_KEYS, VERB_PRIVATE, WISH_KEYS, public_almanac, public_card,
    public_detail, public_event, public_history, public_inventions, public_metrics, public_society, public_wishes)
from swarmworld.server.state import ServerState
from swarmworld.world import registry

from .test_almanac import issues_dir  # noqa: F401  (fixture)

SECRETS = ("sekrit-join-token", "secret-node-xyz", "my-macbook.local", "192.168.77.5", "RAW-MODEL-OUTPUT-42", "Brain node")


class NullWS:
    async def send_json(self, _):
        pass


def _job_for(st, cid):
    """Make the creature ready to think and return the job planned for it."""
    c = st.world.creatures[cid]
    c.asleep, c.thinking, c.wake_reason, c.last_think_tick = False, False, "woke", -1000
    return next(job for _, job in st.plan_dispatch() if job["creature"] == cid)


@pytest.fixture
def busy(tmp_path):
    st = ServerState(seed=7, token="sekrit-join-token", run_dir=tmp_path / "runs")
    node, assigned = st.register_node(NullWS(), {"node": "secret-node-xyz", "slots": 4, "hardware": {"host": "my-macbook.local"},
                                                 "models": [{"tag": "mock", "creatures": 3}]})
    st.cid1, st.cid2 = assigned[0].id, assigned[1].id
    st.node = node
    st.handle_result(node, {"job": _job_for(st, st.cid1)["job"], "ok": True, "output": "RAW-MODEL-OUTPUT-42 not json"})
    st.handle_result(node, {"job": _job_for(st, st.cid2)["job"], "ok": False,
                            "error": "Connection refused http://192.168.77.5:11434/v1"})
    st.admin("weather", {"weather": "rain"})
    for i in range(45):
        for q in range(4):
            st.wishes.add("Mara", f"thing{i}x", "said", f"quote {q}", st.world.tick + q)
    for i in range(300):
        st.relations[f"a{i}|b{i}"] = Counter(talk=i + 1)
    st.finish_chronicle(True, "The creatures gathered.")
    w = st.world
    w.catalog.add_invention({"id": "inv_lamp", "name": "lamp", "desc": "A lamp.", "food": 0, "placeable": True, "tool": False,
                             "depth": 1, "effects": ["light"], "inputs": {"stick": 1, "stone": 1}, "station": None,
                             "by": "Holt", "model": "mock", "tick": 3})
    w.discoveries["inv_lamp"] = {"item": "inv_lamp", "by": "Holt", "by_id": st.cid1, "model": "mock", "tick": 3, "invented": True}
    b = w.ext.setdefault("building", {})
    b.setdefault("sites", {})["s1"] = {"design": "hut", "needs": {"log": 2}, "have": {}, "work": 3, "done": 0, "by": ["Holt"]}
    b.setdefault("built", {})["b1"] = {"design": "hut", "x0": 1, "y0": 1, "x1": 3, "y1": 3, "door": [2, 3], "roof": True,
                                       "by": ["Holt"], "tick": 5}
    st.record_history()
    st.tick_message(st.world.events)
    return st


def test_every_source_field_is_classified(busy, issues_dir):
    w = busy.world
    assert all(set(w.cre_dict(c)) <= set(CARD_KEYS) for c in w.creatures.values())
    assert all(set(o) <= set(OBJECT_KEYS) for o in w.all_object_dicts())
    assert all(set(e.to_dict()) <= set(EVENT_KEYS) for e in w.events)
    for cid in w.creatures:
        assert set(busy.creature_detail(cid)) <= set(DETAIL_KEYS) | set(DETAIL_PRIVATE)
    assert all(set(x) <= set(WISH_KEYS) for x in busy.wishes.ranked())
    soc = busy.society()
    assert set(soc) == {"nodes", "edges", "hubs", "loners"}
    assert set(soc["nodes"][0]) == {"id", "name", "model", "color", "asleep", "drive"}
    assert set(soc["edges"][0]) == {"a", "b", "talk", "gift", "teach", "play", "weight"}
    assert set(busy.metrics.snapshot(w, busy.started)) <= set(METRICS_KEYS) | set(METRICS_PRIVATE)
    full = build(busy, issues_dir)
    assert set(full) <= set(ALMANAC_KEYS) | set(ALMANAC_PRIVATE)
    assert all(set(v) <= set(VERB_KEYS) | set(VERB_PRIVATE) for v in full["verbs"])
    assert all(set(p) <= set(PACK_KEYS) | set(PACK_PRIVATE) for p in full["packs"])


def test_nothing_secret_reaches_a_public_document(busy, issues_dir, tmp_path):
    events = [e for ev in busy.world.events if (e := public_event(ev))]
    docs = [[public_card(busy.world.cre_dict(c)) for c in busy.world.creatures.values()],
            [public_detail(busy, cid) for cid in busy.world.creatures], events, public_wishes(busy),
            public_society(busy), public_metrics(busy), public_inventions(busy), public_history(busy.history),
            public_almanac(build(busy, issues_dir))]
    text = json.dumps(docs)
    for s in (*SECRETS, str(tmp_path)):
        assert s not in text, s
    assert not any(e["kind"] == "steward" for e in events)
    assert any(ev.kind == "steward" for ev in busy.world.events)  # the filter had something to drop
    assert any(ev.data.get("brain_node") for ev in busy.world.events)


def test_a_misparsed_turn_shows_no_raw_output(busy):
    d = public_detail(busy, busy.cid1)
    assert d["last_intention"] == "" and d["last_thought"] == "(confused)"
    assert "node" not in d and "last_error" not in d
    job = _job_for(busy, busy.cid1)
    busy.handle_result(busy.node, {"job": job["job"], "ok": True, "output": {"thought": "hm", "action": "say", "text": "hello"}})
    assert public_detail(busy, busy.cid1)["last_intention"].startswith("say")


def test_wishes_ties_and_history_are_trimmed(busy):
    ws = public_wishes(busy)
    assert len(ws) == 40 and all(len(w["quotes"]) == 1 for w in ws)
    assert ws[0]["quotes"][0] == busy.wishes.ranked(1)[0]["quotes"][-1]
    edges = public_society(busy)["edges"]
    assert len(edges) == 200 and edges == sorted(edges, key=lambda e: -e["weight"])
    rows = [{"tick": i} for i in range(1000)]
    out = public_history(rows)
    assert len(out) == 400 and out[-1] == rows[-1] and out[0] == rows[0]
    assert public_history(rows[:10]) == rows[:10]


def test_public_almanac_has_no_roadmap_or_prompt_lines(busy, issues_dir):
    a = public_almanac(build(busy, issues_dir))
    assert set(a) <= set(ALMANAC_KEYS) and "roadmap" not in a
    assert a["packs"] and all(set(p) <= set(PACK_KEYS) for p in a["packs"])
    text = json.dumps(a)
    for line in [*prompt_lines().values(), *(t.line for t in registry.TECHNIQUES)]:
        assert line not in text, line
    assert all(v["about"] for v in a["verbs"])


def test_every_verb_has_plain_words():
    for v in registry.VERBS:
        about = VERB_ABOUT.get(v, "")
        assert about and about != prompt_lines().get(v), v
        assert "(target" not in about and not re.search(r"\byou\b", about, re.I), v


def test_every_nested_almanac_field_is_classified(busy, issues_dir):
    full = build(busy, issues_dir)
    w = full["world"]
    assert w["sites"] and w["buildings"] and w["discoveries"] and full["inventions"]  # the fixture reaches every part
    assert any(i["discovered"] for i in full["items"]) and any(i["sources"] for i in full["items"])
    checks = [(full["items"], pv.ITEM_KEYS), (full["recipes"], pv.RECIPE_KEYS), (full["processes"], pv.PROCESS_KEYS),
              (full["designs"], pv.DESIGN_KEYS), (full["kinds"], pv.KIND_KEYS), (full["inventions"], pv.INVENTION_KEYS),
              (full["tree"]["nodes"], pv.TREE_NODE_KEYS), (full["tree"]["edges"], pv.TREE_EDGE_KEYS),
              ([x for i in full["items"] for x in i["sources"]], pv.SOURCE_KEYS),
              ([x for i in full["items"] for x in i["used_in"]], pv.USED_IN_KEYS),
              ([i["discovered"] for i in full["items"] if i["discovered"]], pv.DISCOVERY_KEYS),
              (w["discoveries"], pv.DISCOVERY_KEYS), (w["buildings"], pv.BUILDING_KEYS), (w["sites"], pv.SITE_KEYS),
              (w["creatures"], pv.WORLD_CREATURE_KEYS), ([w["clock"]], pv.CLOCK_KEYS),
              (list(w["groups"].values()), pv.GROUP_KEYS), ([v["used"] for v in full["verbs"]], pv.VERB_USED_KEYS)]
    for rows, keys in checks:
        assert rows
        for r in rows:
            assert set(r) <= set(keys), set(r) - set(keys)
    assert set(full["tree"]) == set(pv.TREE_KEYS) and set(w) == set(pv.WORLD_KEYS)
    # and the public copy keeps those fields (nothing is picked away by mistake)
    a = public_almanac(full)
    assert a["world"]["sites"] == w["sites"] and a["world"]["buildings"] == w["buildings"]
    assert a["items"] == full["items"] and a["kinds"] == full["kinds"] and a["inventions"] == full["inventions"]


def test_nested_metrics_history_society_and_detail_fields_are_classified(busy):
    snap = busy.metrics.snapshot(busy.world, busy.started)
    assert all(set(m) <= set(pv.METRICS_MODEL_KEYS) for m in snap["models"].values())
    assert snap["discoveries"] and all(set(d) <= set(pv.METRICS_DISCOVERY_KEYS) for d in snap["discoveries"])
    assert busy.history
    for row in busy.history:
        assert set(row) <= set(pv.HISTORY_KEYS) and set(row["world"]) <= set(pv.HISTORY_WORLD_KEYS)
        assert all(set(m) <= set(pv.HISTORY_MODEL_KEYS) for m in row["models"].values())
    soc = busy.society()
    assert soc["hubs"] and all(set(h) <= set(pv.SOCIETY_HUB_KEYS) for h in soc["hubs"])
    assert all(set(q) <= set(pv.QUOTE_KEYS) for w in busy.wishes.ranked() for q in w["quotes"])
    for cid in busy.world.creatures:
        d = busy.creature_detail(cid)
        assert set(d["persona"]) <= set(pv.PERSONA_KEYS) and all(set(m) <= set(pv.MIND_KEYS) for m in d["minds"])
        assert set(d["stats"]) <= set(pv.STAT_KEYS) | {k for k in d["stats"] if k.startswith("invented_day_")}
        assert all(isinstance(x, str) for k in ("plan", "people", "recent", "harness", "known_recipes") for x in d[k])


def test_every_stat_the_source_counts_is_classified():
    root = Path(pv.__file__).parents[1]
    found = {m for f in root.rglob("*.py") for m in re.findall(r"\bstats\[[\"'](\w+)[\"']\]", f.read_text())}
    assert found and found <= set(pv.STAT_KEYS), found - set(pv.STAT_KEYS)


def test_public_documents_keep_only_listed_fields(busy):
    d = public_detail(busy, busy.cid1)
    assert set(d["stats"]) <= set(pv.STAT_KEYS) and not any(k.startswith("invented_day_") for k in d["stats"])
    busy.world.creatures[busy.cid1].stats["brand_new_counter"] = 1
    busy.world.creatures[busy.cid1].persona["secret"] = "x"
    d = public_detail(busy, busy.cid1)
    assert "brand_new_counter" not in d["stats"] and "secret" not in d["persona"]
    busy.relations["a0|b0"]["gift"] += 1
    assert all(set(e) == set(pv.SOCIETY_EDGE_KEYS) for e in public_society(busy)["edges"])
    row = {"tick": 1, "day": 1, "models": {"m": {"crafted": 1, "extra": 2}}, "world": {"ties": 1, "extra": 3}, "extra": 4}
    assert public_history([row]) == [{"tick": 1, "day": 1, "models": {"m": {"crafted": 1}}, "world": {"ties": 1}}]


def test_static_parts_buildings_landmarks_and_chapters_are_classified(busy):
    busy.sim.tick()  # names the landmarks
    w = busy.world
    init = w.to_init()
    assert set(init) <= set(pv.STATIC_INIT_KEYS) | set(pv.STATIC_INIT_PRIVATE), set(init) - set(pv.STATIC_INIT_KEYS)
    assert init["regions"] and all(set(r) <= set(pv.REGION_KEYS) for r in init["regions"])
    assert all(set(k) <= set(pv.VIEW_KIND_KEYS) for k in init["kinds"].values())
    glyphs = [k["glyph"] for k in init["kinds"].values() if "glyph" in k]
    assert glyphs and all(set(g) <= set(pv.GLYPH_KEYS) for g in glyphs)
    assert init["nature"] and set(init["nature"]) <= set(pv.NATURE_KEYS)
    assert any(lm.get("by_sight") for lm in w.landmarks)  # the fixture reaches every landmark field
    assert all(set(lm) <= set(pv.LANDMARK_KEYS) | set(pv.LANDMARK_PRIVATE) for lm in w.landmarks)
    assert w.building_dicts() and all(set(b) <= set(pv.BUILDING_KEYS) for b in w.building_dicts())
    assert busy.chronicle and all(set(ch) <= set(pv.CHAPTER_KEYS) for ch in busy.chronicle)
    # and the public copies keep those fields (nothing is picked away by mistake)
    s = pv.public_static(init)
    assert set(s) == set(pv.STATIC_INIT_KEYS)
    for k in ("tick", "width", "height", "tiles", "regions", "items", "kinds", "nature", "buildings"):
        assert s[k] == init[k], k
    assert s["objects"] == [pv.public_object(o) for o in init["objects"]]
    assert s["landmarks"] == [{k: v for k, v in lm.items() if k != "by_sight"} for lm in init["landmarks"]]
    assert pv.public_chronicle(busy.chronicle) == busy.chronicle


def test_static_and_live_parts_keep_only_listed_fields(busy):
    init = busy.world.to_init()
    init["secret"] = 1
    init["regions"][0]["secret"] = 1
    init["kinds"]["tree"]["secret"] = 1
    next(k for k in init["kinds"].values() if "glyph" in k)["glyph"]["secret"] = 1
    init["nature"]["secret"] = 1
    init["objects"][0]["secret"] = 1
    init["items"]["odd"] = {"secret": 1}
    init["buildings"] = [{**init["buildings"][0], "secret": 1}]
    init["landmarks"] = [{"name": "a cave", "x": 1, "y": 2, "kind": "cave", "size": 1, "by_sight": True, "secret": 1}]
    text = json.dumps(pv.public_static(init))
    assert "secret" not in text and "by_sight" not in text and "odd" not in text
    chapter = {"tick": 1, "day": 1, "phase": "dawn", "text": "It began.", "secret": 1}
    assert pv.public_chronicle([chapter]) == [{"tick": 1, "day": 1, "phase": "dawn", "text": "It began."}]
    assert pv.public_buildings([{"id": "b1", "design": "hut", "secret": 1}]) == [{"id": "b1", "design": "hut"}]
    assert pv.public_landmarks(init["landmarks"]) == [{"name": "a cave", "x": 1, "y": 2, "kind": "cave", "size": 1}]


def test_public_almanac_pack_descriptions_are_plain_words(busy, issues_dir):
    from swarmworld.server.almanac import PACK_ABOUT
    a = public_almanac(build(busy, issues_dir))
    text = json.dumps(a)
    for bad in ("swarmworld/", ".json", ".py", "Simulation", "_weather", "data:", "Data:"):
        assert bad not in text, bad
    by = {p["id"]: p["about"] for p in a["packs"]}
    assert {"core", "building", "weather", "digging"} <= set(by) and all(by[k] == PACK_ABOUT[k] for k in by if k in PACK_ABOUT)
    assert all(len(v) < 200 and v.endswith(".") for v in PACK_ABOUT.values())
    # a pack with no entry shows nothing, not its docstring
    full = build(busy, issues_dir)
    full["packs"].append({"id": "homebrew", "about": "Internals in swarmworld/x.py", "items": 0, "recipes": 0, "kinds": 0, "verbs": 0, "designs": 0})
    assert {p["id"]: p["about"] for p in public_almanac(full)["packs"]}["homebrew"] == ""
