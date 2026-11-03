"""The public viewer's snapshot feed (web/public.js): polls /public/live.json, fetches static.json on a version change and
replays each snapshot's per-tick paths and events as socket-shaped messages. Runs in node with a fake fetch and clock."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parent.parent / "web"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed")


def card(x, y, **more):
    return {"id": "c1", "name": "Ada", "x": x, "y": y, "model": "m", "color": "#fff", "activity": "idle", **more}


def ev(seq, tick, text="hi"):
    return {"seq": seq, "tick": tick, "kind": "say", "actor": "c1", "x": 1, "y": 1, "text": text}


STATIC = {
    "schema": 1, "type": "static", "version": "b-1", "tick": 90, "width": 4, "height": 3,
    "tiles": ["gggg", "gdgg", "rrrr"],
    "regions": [{"name": "surface", "level": 0, "y0": 0, "y1": 2, "height": 2},
                {"name": "deep", "level": -1, "y0": 2, "y1": 3, "height": 1}],
    "objects": [{"id": "o1", "kind": "tree", "x": 1, "y": 0}, {"id": "o2", "kind": "rock", "x": 2, "y": 0}],
    "items": {"stick": "stick"}, "kinds": {"tree": {}}, "nature": {"seed": 1}, "landmarks": [], "buildings": [],
    "inventions": [{"name": "rope"}],
}
O1_MOVED = {"id": "o1", "kind": "tree", "x": 0, "y": 1}
O3 = {"id": "o3", "kind": "bush", "x": 3, "y": 1}
BASE = {
    "schema": 1, "type": "live", "boot": "b", "every": 3, "tick_seconds": 0.5, "clock": {"day": 1, "minute": 5},
    "static": "b-1", "objects_removed": ["o2"], "tiles": [[1, 1, "g"]], "buildings": [], "landmarks": [],
    "chronicle": [{"title": "t"}], "chronicle_version": "b-3", "society": {"groups": 1},
    "wishes": [{"id": "w1", "thing": "boat"}], "metrics": {"ticks": 7},
}
LIVE1 = {**BASE, "seq": 5, "tick": 103, "from_tick": 100, "objects_upsert": [O3],
         "creatures": [card(2, 1, path=[[0, 1], [1, 1], [2, 1]])], "events": [ev(1, 101), ev(2, 103)]}
LIVE2 = {**BASE, "seq": 6, "tick": 106, "from_tick": 103, "objects_upsert": [O1_MOVED, O3],
         "creatures": [card(4, 1, path=[[3, 1], [3, 1], [4, 1]])], "events": [ev(1, 101), ev(2, 103), ev(3, 105)]}
LIVE_STALE = {**LIVE1, "seq": 7, "static": "b-2"}
LIVE_NEWBOOT = {**LIVE1, "boot": "c", "seq": 1}
LIVE_SCHEMA2 = {**LIVE2, "schema": 2}
LONG = {**LIVE1, "seq": 9, "tick": 500, "from_tick": 0,
        "creatures": [card(20, 1, path=[[i, 1] for i in range(5, 21)])],
        "events": [ev(i, 380 + i) for i in range(1, 121)]}

HARNESS = r"""
const fs = require('fs');
global.window = global;
const D = JSON.parse(fs.readFileSync(0, 'utf8'));
eval(fs.readFileSync(process.argv[2], 'utf8'));
const SP = window.SwarmPublic;
const out = {};
const flush = async () => { for (let i = 0; i < 5; i++) await new Promise((r) => setImmediate(r)); };

function rig(lives, statics, extra) {
  const t = { now: 0, timers: [], urls: [], reloads: 0, liveN: 0, staticN: 0, hiddenNow: false };
  const respond = (body) => Promise.resolve({ ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(body)) });
  const fakeFetch = (url) => {
    t.urls.push(url);
    if (url.startsWith('/public/live.json')) {
      const item = lives[Math.min(t.liveN++, lives.length - 1)];
      return item === 'fail' ? Promise.reject(new Error('net')) : respond(item);
    }
    if (url.startsWith('/public/static.json')) {
      const s = statics[Math.min(t.staticN++, statics.length - 1)];
      return respond(s);
    }
    if (url.startsWith('/public/creature/')) return respond({ id: 'c1', detail: true });
    return respond({ url });
  };
  let id = 0;
  const opts = Object.assign({
    fetch: fakeFetch, random: () => 0.5, hidden: () => t.hiddenNow, reload: () => { t.reloads++; },
    setTimeout: (fn, ms) => { const h = ++id; t.timers.push({ h, at: t.now + ms, fn }); return h; },
    clearTimeout: (h) => { t.timers = t.timers.filter((x) => x.h !== h); },
  }, extra || {});
  t.opts = opts;
  t.msgs = [];
  t.advance = async (ms) => {
    const end = t.now + ms;
    for (;;) {
      await flush();
      const due = t.timers.filter((x) => x.at <= end).sort((a, b) => a.at - b.at || a.h - b.h)[0];
      if (!due) break;
      t.timers = t.timers.filter((x) => x !== due);
      t.now = due.at;
      due.fn();
    }
    t.now = end;
    await flush();
  };
  t.open = async () => {
    const s = SP.createSocket(opts);
    t.sock = s;
    s.onopen = () => t.msgs.push({ type: '_open' });
    s.onmessage = (e) => t.msgs.push(JSON.parse(e.data));
    s.onclose = () => t.msgs.push({ type: '_close' });
    await t.advance(0);
    return s;
  };
  t.types = () => t.msgs.map((m) => m.type);
  return t;
}

const LIVE1 = D.LIVE1, LIVE2 = D.LIVE2, STATIC = D.STATIC;
const view1 = SP.viewOf(STATIC, LIVE1), view2 = SP.viewOf(STATIC, LIVE2);

(async () => {
%s
  process.stdout.write(JSON.stringify(out));
})();
"""

SCENARIOS = {
    "init": "out.v = SP.initMessage(STATIC, LIVE1);",
    "frames": """
      const d = SP.diffViews(view1, view2);
      out.v = SP.tickFrames(LIVE2, { tick: 103, eventSeq: 2 }, d);""",
    "long_sleep": """
      const d = SP.diffViews(SP.viewOf(STATIC, {}), SP.viewOf(STATIC, D.LONG));
      out.v = SP.tickFrames(D.LONG, { tick: 10, eventSeq: 0 }, d);""",
    "diff": """
      out.v = { changed: SP.diffViews(view1, view2), same: SP.diffViews(view2, view2),
                from_static: SP.diffViews(SP.viewOf(STATIC, {}), view1) };""",
    "delays": """
      const r = () => 0.5;
      out.v = { normal: SP.pollDelay({ every: 3, hidden: false, sameSeq: false, failures: 0, rand: r }),
                hidden: SP.pollDelay({ every: 3, hidden: true, sameSeq: false, failures: 0, rand: r }),
                same: SP.pollDelay({ every: 3, hidden: false, sameSeq: true, failures: 0, rand: r }),
                failed: SP.pollDelay({ every: 3, hidden: false, sameSeq: false, failures: 1, rand: r }) };""",
    "socket": """
      const t = rig([LIVE1, LIVE2], [STATIC]);
      await t.open();
      const first = t.types();
      await t.advance(3000);
      await t.advance(3000);
      out.v = { first, types: t.types(), urls: t.urls, ticks: t.msgs.filter((m) => m.type === 'tick').map((m) => m.tick) };""",
    "pace": """
      const t = rig([LIVE1, LIVE2], [STATIC]);
      await t.open();
      const before = t.msgs.length;
      await t.advance(3000);                       // the poll: frame 0 arrives at once
      const at0 = t.msgs.slice(before).filter((m) => m.type === 'tick').length;
      await t.advance(1000);
      const at1 = t.msgs.slice(before).filter((m) => m.type === 'tick').length;
      await t.advance(1000);
      const at2 = t.msgs.slice(before).filter((m) => m.type === 'tick').length;
      out.v = { at0, at1, at2, last: t.types()[t.types().length - 1] };""",
    "hidden": """
      const t = rig([LIVE1, LIVE2], [STATIC]);
      await t.open();
      t.hiddenNow = true;
      const before = t.msgs.length;
      await t.advance(3000);                       // the next poll was set before the tab hid: 3 s
      const ticks = t.msgs.slice(before).filter((m) => m.type === 'tick').length;
      const live = t.urls.filter((u) => u.startsWith('/public/live.json')).length;
      await t.advance(20000);
      const live20 = t.urls.filter((u) => u.startsWith('/public/live.json')).length;
      out.v = { ticks, live, live20 };""",
    "visible": """
      const handlers = [];
      global.document = { hidden: false, addEventListener: (n, f) => handlers.push([n, f]), removeEventListener() {} };
      const t = rig([LIVE1, LIVE2], [STATIC]);
      await t.open();
      t.hiddenNow = true;
      await t.advance(3000);
      t.hiddenNow = false;
      const before = t.urls.length;
      for (const [n, f] of handlers) if (n === 'visibilitychange') f();
      await t.advance(0);
      out.v = { polled: t.urls.length > before, names: handlers.map((h) => h[0]) };""",
    "stale_static": """
      const t = rig([D.LIVE_STALE], [Object.assign({}, STATIC, { version: 'b-1' }), Object.assign({}, STATIC, { version: 'b-2' })]);
      await t.open();
      const before = t.msgs.filter((m) => m.type === 'tick').length;
      await t.advance(1000);
      out.v = { ticks_before_retry: before, ticks_after_retry: t.msgs.filter((m) => m.type === 'tick').length };""",
    "stale_forever": """
      const t = rig([D.LIVE_STALE], [STATIC]);
      await t.open();
      await t.advance(10000);
      out.v = { closed: t.sock.readyState === 3, opened: t.types().includes('_open'), statics: t.urls.filter((u) => u.startsWith('/public/static')).length };""",
    "no_dup_events": """
      const t = rig([LIVE1, LIVE2], [STATIC]);
      await t.open();
      await t.advance(3000);
      await t.advance(3000);
      out.v = t.msgs.filter((m) => m.type === 'tick').flatMap((m) => m.events.map((e) => e.seq));""",
    "new_boot": """
      const t = rig([LIVE1, D.LIVE_NEWBOOT], [STATIC]);
      await t.open();
      await t.advance(3000);
      out.v = { closed: t.sock.readyState === 3 };""",
    "schema": """
      const t = rig([LIVE1, D.LIVE_SCHEMA2], [STATIC]);
      await t.open();
      await t.advance(3000);
      await t.advance(5000);
      out.v = { reloads: t.reloads, closed: t.sock.readyState === 3 };""",
    "failures": """
      const t = rig([LIVE1, 'fail', 'fail'], [STATIC]);
      await t.open();
      await t.advance(3000);
      const open = t.sock.readyState === 1;
      await t.advance(1000);
      out.v = { open_after_one: open, closed: t.sock.readyState === 3 };""",
    "recovers": """
      const t = rig([LIVE1, 'fail', LIVE2], [STATIC]);
      await t.open();
      await t.advance(3000);
      await t.advance(1000);
      await t.advance(3000);
      out.v = { open: t.sock.readyState === 1, ticks: t.msgs.filter((m) => m.type === 'tick').length };""",
    "api": """
      const t = rig([LIVE1], [STATIC]);
      await t.open();
      const u0 = t.urls.length;
      out.v = {};
      await SP.api('/api/creature/c1');
      out.v.creature_url = t.urls[t.urls.length - 1];
      await SP.api('/api/history');
      out.v.history_url = t.urls[t.urls.length - 1];
      await SP.api('/api/chronicle');
      out.v.chronicle_url = t.urls[t.urls.length - 1];
      const fetched = t.urls.length;
      out.v.wishes = await SP.api('/api/wishes');
      out.v.society = await SP.api('/api/society');
      out.v.metrics = await SP.api('/api/metrics');
      out.v.inventions = await SP.api('/api/inventions');
      out.v.no_fetch_for_local = t.urls.length === fetched;
      const n = t.urls.length;
      try { await SP.api('/api/state'); } catch (e) { out.v.state_rejected = String(e.message); }
      try { await SP.post('/api/voice', { text: 'x' }); } catch (e) { out.v.post_status = e.status; }
      out.v.fetches_for_reject = t.urls.length - n;
      out.v.all_public = t.urls.every((u) => u.startsWith('/public/'));""",
}


def run_public(tmp_path, scenario: str):
    harness = tmp_path / "public_harness.js"
    harness.write_text(HARNESS % SCENARIOS[scenario])
    data = {"STATIC": STATIC, "LIVE1": LIVE1, "LIVE2": LIVE2, "LIVE_STALE": LIVE_STALE, "LIVE_NEWBOOT": LIVE_NEWBOOT,
            "LIVE_SCHEMA2": LIVE_SCHEMA2, "LONG": LONG}
    r = subprocess.run([NODE, str(harness), str(WEB / "public.js")], input=json.dumps(data), capture_output=True,
                       text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)["v"]


@needs_node
def test_init_patches_the_static_view(tmp_path):
    out = run_public(tmp_path, "init")
    assert out["type"] == "init" and sorted(o["id"] for o in out["objects"]) == ["o1", "o3"]
    assert out["tiles"][1] == "gggg" and out["regions"] == STATIC["regions"] and out["tick"] == 103
    assert all("path" not in c for c in out["creatures"])
    assert out["items"] == STATIC["items"] and out["nature"] == STATIC["nature"] and out["width"] == 4


@needs_node
def test_frames_replay_each_tick(tmp_path):
    frames = run_public(tmp_path, "frames")
    assert [f["tick"] for f in frames] == [104, 105, 106]
    assert [next(c for c in f["creatures"] if c["id"] == "c1")["x"] for f in frames] == [3, 3, 4]
    assert [[e["seq"] for e in f["events"]] for f in frames] == [[], [3], []]
    assert frames[0]["objects_upsert"] == [] and frames[0]["tiles"] is None and frames[-1]["objects_upsert"]
    assert all(f["type"] == "tick" and f["clock"] == LIVE2["clock"] for f in frames)
    assert all("path" not in c for f in frames for c in f["creatures"])


@needs_node
def test_waking_after_a_long_sleep_catches_up_in_one_bounded_batch(tmp_path):
    frames = run_public(tmp_path, "long_sleep")
    assert len(frames) == 16 and frames[-1]["tick"] == 500
    assert sum(len(f["events"]) for f in frames) <= 120
    assert frames[0]["events"] and len(frames[0]["events"]) > 100   # events before the window land in frame 0


@needs_node
def test_diff_views(tmp_path):
    d = run_public(tmp_path, "diff")
    assert [o["id"] for o in d["changed"]["objects_upsert"]] == ["o1"] and d["changed"]["objects_removed"] == []
    assert d["changed"]["tiles"] is None and d["changed"]["buildings"] is None
    assert d["same"] == {"objects_upsert": [], "objects_removed": [], "tiles": None, "buildings": None, "landmarks": None}
    assert d["from_static"]["objects_removed"] == ["o2"] and d["from_static"]["tiles"] == [[1, 1, "g"]]


@needs_node
def test_poll_delays(tmp_path):
    assert run_public(tmp_path, "delays") == {"normal": 3000, "hidden": 30000, "same": 1000, "failed": 1000}


@needs_node
def test_the_socket_lifecycle(tmp_path):
    out = run_public(tmp_path, "socket")
    assert out["first"] == ["_open", "init", "metrics", "tick"]
    assert out["types"][1:4] == ["init", "metrics", "tick"] and out["types"].count("tick") == 4
    assert out["ticks"] == [103, 104, 105, 106]
    assert out["urls"] and all(u.startswith("/public/") for u in out["urls"])
    assert sum(u.startswith("/public/static.json") for u in out["urls"]) == 1


@needs_node
def test_frames_arrive_one_interval_behind_at_tick_pace(tmp_path):
    out = run_public(tmp_path, "pace")
    assert out == {"at0": 1, "at1": 2, "at2": 3, "last": "metrics"}


@needs_node
def test_a_hidden_tab_gets_the_frames_all_at_once_and_polls_slowly(tmp_path):
    out = run_public(tmp_path, "hidden")
    assert out["ticks"] == 3 and out["live"] == 2 and out["live20"] == 2   # no poll within 30 s of the hidden one


@needs_node
def test_becoming_visible_polls_at_once(tmp_path):
    out = run_public(tmp_path, "visible")
    assert out["polled"] and "visibilitychange" in out["names"]


@needs_node
def test_a_stale_static_is_not_used(tmp_path):
    out = run_public(tmp_path, "stale_static")
    assert out["ticks_before_retry"] == 0 and out["ticks_after_retry"] >= 1


@needs_node
def test_a_static_that_never_catches_up_closes_the_socket(tmp_path):
    out = run_public(tmp_path, "stale_forever")
    assert out == {"closed": True, "opened": False, "statics": 4}


@needs_node
def test_events_are_replayed_once(tmp_path):
    assert run_public(tmp_path, "no_dup_events") == [1, 2, 3]


@needs_node
def test_a_new_boot_reconnects_from_scratch(tmp_path):
    assert run_public(tmp_path, "new_boot") == {"closed": True}


@needs_node
def test_a_new_schema_reloads_once(tmp_path):
    assert run_public(tmp_path, "schema") == {"reloads": 1, "closed": True}


@needs_node
def test_two_failures_close_the_socket(tmp_path):
    assert run_public(tmp_path, "failures") == {"open_after_one": True, "closed": True}


@needs_node
def test_one_failure_is_forgiven(tmp_path):
    assert run_public(tmp_path, "recovers") == {"open": True, "ticks": 4}


@needs_node
def test_api_maps_to_public_documents(tmp_path):
    out = run_public(tmp_path, "api")
    assert out["creature_url"] == "/public/creature/c1.json" and out["history_url"] == "/public/history.json"
    assert out["chronicle_url"] == f"/public/chronicle.json?v={LIVE1['chronicle_version']}"
    assert out["wishes"] == {"can_answer": False, "wishes": LIVE1["wishes"]} and out["society"] == LIVE1["society"]
    assert out["metrics"] == LIVE1["metrics"] and out["inventions"] == STATIC["inventions"]
    assert out["no_fetch_for_local"] and out["all_public"]
    assert out["state_rejected"] == "HTTP 404" and out["post_status"] == 403 and out["fetches_for_reject"] == 0
