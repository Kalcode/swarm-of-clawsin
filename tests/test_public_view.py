"""What a watcher may see: every public document is an allowlist of fields, with nothing private in it."""

import json
import re
from collections import Counter

import pytest

from swarmworld.server.almanac import VERB_ABOUT, build, prompt_lines
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
