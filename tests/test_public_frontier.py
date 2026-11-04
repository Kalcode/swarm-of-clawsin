"""The public viewer follows a growth: static.json is rebuilt the moment the width or origin changes, live.json says
how much was laid, the allowlists hold, and the page re-inits (with its camera kept) instead of diffing."""

import json
import subprocess
from collections import Counter

import pytest

from swarmworld.server.public import LIVE_KEYS, Publisher
from swarmworld.server.public_view import public_almanac
from swarmworld.server.state import ServerState
from swarmworld.world.model import FrontierSettings
from swarmworld.world.packs.frontier import grow

from .test_viewer_public import HARNESS, LIVE1, NODE, SCENARIOS, STATIC, WEB, needs_node


def make(side="east"):
    st = ServerState(seed=7, frontier=FrontierSettings(on=True, pace=0))
    now = [0.0]
    pub = Publisher(st, clock=lambda: now[0])
    pub.publish()

    def step():
        pub.observe(st.tick_dict(st.sim.tick()), [])

    def publish():
        now[0] += 3
        pub.publish()
        return json.loads(pub.static_doc().body), json.loads(pub.live_doc().body)

    return st, pub, step, publish


def test_a_growth_rebuilds_the_static_at_once():
    st, pub, step, publish = make()
    v1 = pub.static_version
    grow(st.world, "east")
    step()
    static, live = publish()
    assert pub.static_version != v1 and static["width"] == 160 and static["origin_x"] == 0
    assert live["frontier"] == {"origin_x": 0, "strips": 1} and "frontier" in LIVE_KEYS
    assert live["static"] == pub.static_version


def test_a_west_growth_rebuilds_the_static_before_the_live_deltas():
    st, pub, step, publish = make()
    w = st.world
    free = next((x, y) for y in range(60, 70) for x in range(5, 15) if (x, y) not in w.grid and w.tiles[y][x] == "g")
    rock = w.add_object("rock", *free)
    pub.observe(st.tick_dict(st.sim.tick()), [])
    w.move_object(rock, free[0] + 1, free[1])
    w.drop_items(free[0] + 2, free[1], Counter(stick=1))
    step()
    grow(w, "west")
    step()
    static, live = publish()
    assert live["objects_upsert"] == [] and live["objects_removed"] == []  # not the old x's, left unshifted
    assert static["origin_x"] == 32
    at = {o["id"]: (o["x"], o["y"]) for o in static["objects"]}
    assert at[rock.id] == (free[0] + 33, free[1]) == (rock.x, rock.y)
    assert any(o["id"] == f"pile:{free[0] + 34}:{free[1]}" for o in static["objects"]), "the pile at its new x"


def test_the_live_paths_follow_a_west_growth():
    st, pub, step, publish = make()
    st.register_node(type("W", (), {"send_json": lambda s, m: None})(), {"node": "n", "slots": 2, "models": [{"tag": "mock", "creatures": 2}]})
    w = st.world
    c = next(iter(w.creatures.values()))
    c.x, c.y = 40, 40
    step()
    pub.publish()
    c.x = 41
    step()
    grow(w, "west")
    step()
    c.x += 1
    step()
    _, live = publish()
    path = next(card for card in live["creatures"] if card["id"] == c.id).get("path", [])
    assert path and all(x >= 32 + 40 for x, _ in path), path  # 32 further east, with no jump back to the old column


def test_the_almanac_lands_keep_only_east_and_west():
    full = {"world": {"lands": {"strips": {"east": 1, "west": 2, "secret": 3}, "count": 1,
                                "found": [{"name": "the Eastern Meadow", "theme": "meadow", "by": "Ada", "secret": 1}],
                                "secret": 1}}}
    out = public_almanac(full)["world"]["lands"]
    assert out == {"strips": {"east": 1, "west": 2}, "count": 1,
                   "found": [{"name": "the Eastern Meadow", "theme": "meadow", "by": "Ada"}]}


STATIC_GROWN = {**STATIC, "version": "b-2", "width": 6, "origin_x": 2, "tiles": ["gggggg", "gggdgg", "rrrrrr"],
                "objects": [{"id": "o1", "kind": "tree", "x": 3, "y": 0}, {"id": "o2", "kind": "rock", "x": 4, "y": 0}]}
LIVE_GROWN = {**LIVE1, "seq": 6, "tick": 106, "from_tick": 103, "static": "b-2", "objects_upsert": [], "objects_removed": [],
              "tiles": [], "frontier": {"origin_x": 2, "strips": 1},
              "creatures": [{**LIVE1["creatures"][0], "x": 5, "y": 1, "path": [[4, 1], [5, 1]]}],
              "events": [{"seq": 2, "tick": 103, "kind": "say", "actor": "c1", "x": 1, "y": 1, "text": "hi"},
                         {"seq": 3, "tick": 105, "kind": "say", "actor": "c1", "x": 5, "y": 1, "text": "later"}]}

SCENARIOS_ADD = {
    "grow": """
      const t = rig([LIVE1, D.LIVE_GROWN], [STATIC, D.STATIC_GROWN]);
      await t.open();
      const before = t.msgs.length;
      await t.advance(3000);
      await t.advance(3000);
      const after = t.msgs.slice(before);
      out.v = { types: after.map((m) => m.type), grow: after[0], init: after[1], null_same: SP.growOf(STATIC, STATIC),
                east: SP.growOf(STATIC, Object.assign({}, STATIC, { width: 7 })),
                events: after.filter((m) => m.type === 'tick').flatMap((m) => m.events.map((e) => e.seq)) };""",
}


def run(tmp_path, scenario):
    harness = tmp_path / "h.js"
    harness.write_text(HARNESS % SCENARIOS_ADD[scenario])
    data = {"STATIC": STATIC, "LIVE1": LIVE1, "LIVE2": LIVE1, "LIVE_GROWN": LIVE_GROWN, "STATIC_GROWN": STATIC_GROWN}
    r = subprocess.run([NODE, str(harness), str(WEB / "public.js")], input=json.dumps(data), capture_output=True,
                       text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)["v"]


@needs_node
def test_the_public_client_reinits_on_a_growth(tmp_path):
    v = run(tmp_path, "grow")
    assert v["types"] == ["grow", "init", "metrics", "tick"]  # the one tick frame carries events only, nothing diffed across the growth
    assert v["grow"] == {"type": "grow", "side": "west", "columns": 2, "width": 6, "origin_x": 2}
    assert v["init"]["width"] == 6 and v["init"]["origin_x"] == 2 and v["init"]["tick"] == 106
    assert v["null_same"] is None
    assert v["east"] == {"type": "grow", "side": "east", "columns": 3, "width": 7, "origin_x": 0}
    assert v["events"] == [2, 3]  # one frame after the init: LIVE1's cursor was seq 1, so the growth's own events play


@needs_node
def test_events_after_the_growth_still_play(tmp_path):
    harness = tmp_path / "h2.js"
    harness.write_text(HARNESS % """
      const later = Object.assign({}, D.LIVE_GROWN, { seq: 7, tick: 109, from_tick: 106,
        events: D.LIVE_GROWN.events.concat([{ seq: 4, tick: 108, kind: 'say', actor: 'c1', x: 5, y: 1, text: 'new' }]) });
      const t = rig([LIVE1, D.LIVE_GROWN, later], [STATIC, D.STATIC_GROWN]);
      await t.open();
      await t.advance(3000);
      await t.advance(3000);
      await t.advance(3000);
      out.v = t.msgs.filter((m) => m.type === 'tick').flatMap((m) => m.events.map((e) => e.seq));""")
    data = {"STATIC": STATIC, "LIVE1": LIVE1, "LIVE2": LIVE1, "LIVE_GROWN": LIVE_GROWN, "STATIC_GROWN": STATIC_GROWN}
    r = subprocess.run([NODE, str(harness), str(WEB / "public.js")], input=json.dumps(data), capture_output=True,
                       text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["v"] == [1, 2, 3, 4]  # open's frame; the growth's events past the cursor; then the new one


def test_the_live_events_follow_a_west_growth():
    st, pub, step, publish = make()
    w = st.world
    ev = w.emit("say", None, 40, 40, "before the strip")
    pub.observe(st.tick_dict(st.sim.tick()), [ev])
    grow(w, "west")
    pub.observe(st.tick_dict(st.sim.tick()), [])
    _, live = publish()
    xs = [e["x"] for e in live["events"] if e.get("text") == "before the strip"]
    assert xs == [40 + 32]


def test_metrics_say_whether_the_frontier_is_on():
    off = json.loads(ServerState(seed=7).metrics_message())["frontier"]
    assert off == {"on": False, "strips": 0, "width": 128, "origin_x": 0}
    st = ServerState(seed=7, frontier=FrontierSettings(on=True, pace=0))
    grow(st.world, "west")
    grow(st.world, "east")
    grow(st.world, "west")
    assert json.loads(st.metrics_message())["frontier"] == {"on": True, "strips": 3, "width": 224, "origin_x": 64}
