"""The public viewer's snapshot feed (web/public.js): polls /public/live.json, fetches static.json on a version change and
replays each snapshot's per-tick paths and events as socket-shaped messages. Runs in node with a fake fetch and clock.
Then the viewer's public mode (web/viewer.js, index.html): it reads that feed instead of the socket, hides every steward
control and shows the banner and the About panel."""

import json
import re
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
      return s === 'fail' ? Promise.reject(new Error('net')) : respond(s);
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
    "static_fails": """
      const t = rig([LIVE1, Object.assign({}, LIVE2, { static: 'b-2' })], [STATIC, 'fail']);
      await t.open();
      await t.advance(3000);
      const open = t.sock.readyState === 1;
      await t.advance(1000);
      out.v = { open_after_one: open, closed: t.sock.readyState === 3, statics: t.urls.filter((u) => u.startsWith('/public/static')).length };""",
    "static_wedged": """
      const t = rig([LIVE1, Object.assign({}, LIVE2, { static: 'b-2' })], [STATIC]);
      await t.open();
      await t.advance(3000);
      await t.advance(30000);
      out.v = { closed: t.sock.readyState === 3, statics: t.urls.filter((u) => u.startsWith('/public/static')).length,
                ticks: t.msgs.filter((m) => m.type === 'tick').length };""",
    "reload_twice": """
      const store = new Map();
      global.sessionStorage = { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, v), removeItem: (k) => store.delete(k) };
      let reloads = 0;
      const extra = { reload: () => { reloads++; } };
      const a = rig([LIVE1, D.LIVE_SCHEMA2], [STATIC], extra);
      await a.open();
      await a.advance(3000);
      const after_first = reloads;
      const b = rig([LIVE1, D.LIVE_SCHEMA2], [STATIC], extra);
      await b.open();
      await b.advance(3000);
      out.v = { after_first, reloads };""",
    "close_in_retry": """
      const t = rig([D.LIVE_STALE], [STATIC]);
      await t.open();
      const n = t.urls.length;
      t.sock.close();
      await t.advance(10000);
      out.v = { more: t.urls.length - n, timers: t.timers.length };""",
    "one_timer": """
      const t = rig([LIVE1], [STATIC]);
      for (let i = 0; i < 3; i++) { await t.open(); t.sock.close(); }
      const closed = t.timers.length;
      await t.open();
      out.v = { closed, open: t.timers.length };""",
    "bad_id": """
      const t = rig([LIVE1], [STATIC]);
      await t.open();
      let p, threw = false;
      try { p = SP.api('/api/creature/%E0%A4%A'); } catch (e) { threw = true; }
      let msg = null;
      if (p) await p.catch((e) => { msg = e.message; });
      out.v = { threw, msg };""",
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


@needs_node
def test_a_persistent_static_failure_closes_the_socket_after_two_polls(tmp_path):
    out = run_public(tmp_path, "static_fails")
    assert out == {"open_after_one": True, "closed": True, "statics": 3}


@needs_node
def test_a_static_that_keeps_naming_an_older_version_closes_after_the_retries(tmp_path):
    out = run_public(tmp_path, "static_wedged")
    assert out["closed"] and out["statics"] == 1 + 4 and out["ticks"] == 1   # the open, then more than STATIC_TRIES skips


@needs_node
def test_a_later_schema_bump_in_the_same_tab_reloads_again(tmp_path):
    assert run_public(tmp_path, "reload_twice") == {"after_first": 1, "reloads": 2}


@needs_node
def test_closing_during_the_static_retry_window_fetches_nothing_more(tmp_path):
    assert run_public(tmp_path, "close_in_retry") == {"more": 0, "timers": 0}


@needs_node
def test_sockets_opened_and_closed_in_a_row_leave_one_timer(tmp_path):
    assert run_public(tmp_path, "one_timer") == {"closed": 0, "open": 1}


@needs_node
def test_a_malformed_creature_id_rejects_instead_of_throwing(tmp_path):
    assert run_public(tmp_path, "bad_id") == {"threw": False, "msg": "HTTP 404"}


# ------------------------------------------------------------------ the viewer's public mode (viewer.js, index.html)

BANNER = "Live from a world running on one Mac: AI creatures think with local models. Updates every few seconds."


def function_body(src: str, name: str) -> str:
    """The text between the braces of `function name(...) { ... }` in a script (braces counted, as the viewer's
    functions keep any braces in their strings balanced)."""
    m = re.search(rf"\bfunction\s+{re.escape(name)}\s*\(", src)
    assert m, f"no function {name}"
    depth, i = 1, m.end()
    while depth:                                       # past the parameter list
        depth += {"(": 1, ")": -1}.get(src[i], 0)
        i += 1
    start = src.index("{", i) + 1
    depth, i = 1, start
    while depth:
        depth += {"{": 1, "}": -1}.get(src[i], 0)
        i += 1
    return src[start:i - 1]


def test_the_viewer_reads_snapshots_in_public_mode():
    src = (WEB / "viewer.js").read_text()
    assert "window.SwarmPublic.createSocket()" in src
    assert "window.SwarmPublic.api(path)" in src and "window.SwarmPublic.post(path, body)" in src
    assert "document.documentElement.dataset.public === '1'" in src and "params.has('public')" in src
    assert "PUBLIC ? 3000 : 1000" in src


def test_public_mode_hides_every_steward_control():
    src = (WEB / "viewer.js").read_text()
    body = function_body(src, "enterPublicMode")
    assert "S.voice.disabled = true" in body and ".voice" in body and "public-banner" in body
    assert "enterPublicMode()" in function_body(src, "boot")
    assert function_body(src, "boot").index("enterPublicMode()") < function_body(src, "boot").index("connect()")
    assert "PUBLIC" in function_body(src, "renderWishes")


def test_the_banner_and_about():
    html = (WEB / "index.html").read_text()
    assert BANNER in html and re.search(r'id="public-banner"[^>]*\bhidden\b', html)
    assert re.search(r'<dialog[^>]*id="about"', html) and "What you’re watching" in html and 'id="about-link"' in html
    assert html.index('src="layers.js"') < html.index('src="public.js"') < html.index('src="viewer.js"')


ABOUT = [
    ("Every creature here is a small AI model running on a computer at home. Each turn it reads what it senses as plain "
     "text, then decides what to do and says why. Nothing is scripted: what they make, say and build comes from those turns."),
    ("<b>Models.</b> The badge on a creature names the model thinking for it. Different models share the world, and the "
     "Swarm tab counts what each one does."),
    ("<b>The harness.</b> Some creatures get extra help, chosen at random: a plan they keep, tips that appear when they "
     "fit, and memories that come back when they matter. The tags on a creature’s card say which."),
    ("<b>Wishes.</b> When a creature wishes for something the world doesn’t have, the Wishes tab collects it. The people "
     "running the world read them and sometimes answer from the sky. You can read them, not answer them."),
    ("<b>The deep.</b> Under the meadow lie dark caves with ore, coal and crystal. Creatures climb down at cave mouths and "
     "see only by torchlight. Switch to Underground at the top to look."),
    "What you see is a few seconds behind the world.",
]


def test_the_banner_and_about_read_as_written():
    html = (WEB / "index.html").read_text()
    banner = re.search(r'<p class="public-banner" id="public-banner" hidden>.*?</p>', html, re.S)
    assert banner and banner.group(0) == (
        f'<p class="public-banner" id="public-banner" hidden><span class="pb-long">{BANNER}</span>'
        '<span class="pb-short" aria-hidden="true">Live from one Mac</span> '
        '<button type="button" class="pill-btn" id="about-btn" aria-haspopup="dialog">About</button></p>')
    assert html.index('class="hstats"') < banner.start() < html.index('id="layer-switch"')   # in the top bar, after the stats
    about = re.search(r'<dialog class="about" id="about" aria-labelledby="about-title">(.*?)</dialog>', html, re.S)
    assert about and html.index("</dialog>") < html.index("</body>") and about.start() > html.index("</main>")
    paras = re.findall(r"<p>(.*?)</p>", about.group(1), re.S)
    assert '<h2 id="about-title">What you’re watching</h2>' in about.group(1) and paras == ABOUT
    tail = about.group(1)[about.group(1).index(ABOUT[-1]):]
    assert re.search(r'<p id="about-more" hidden><a id="about-link" target="_blank" rel="noopener">More about this project</a></p>'
                     r'\s*<form method="dialog"><button class="pill-btn" id="about-close">Close</button></form>', tail)


def test_the_short_banner_takes_over_at_900px():
    css = (WEB / "style.css").read_text()
    narrow = re.search(r"@media \(max-width: 900px\) \{(.*?)\n\}", css, re.S).group(1)
    # the long form is only hidden from sight (the short one is aria-hidden), so a screen reader still reads it
    assert re.search(r"\.pb-long\s*\{[^}]*position:\s*absolute;[^}]*clip:", narrow) and re.search(r"\.pb-short\s*\{[^}]*display:\s*(inline|block)", narrow)
    assert not re.search(r"\.pb-long\s*\{[^}]*display:\s*none", css)
    assert re.search(r"\.pb-short\s*\{[^}]*display:\s*none", css[:css.index("@media (max-width: 900px)")])
    assert re.search(r"\.about::backdrop\s*\{", css)


VIEWER_HARNESS = r"""
const fs = require('fs');
global.window = global;
const D = JSON.parse(fs.readFileSync(0, 'utf8'));
const t = { now: 0, timers: [], fetches: [], msgs: [], ws: [], serve: () => Promise.reject(new Error('net')) };
let hid = 0;
global.setTimeout = (fn, ms) => { const h = ++hid; t.timers.push({ h, at: t.now + (ms || 0), fn }); return h; };
global.clearTimeout = (h) => { t.timers = t.timers.filter((x) => x.h !== h); };
Object.defineProperty(globalThis, 'performance', { value: { now: () => t.now }, configurable: true, writable: true });
Math.random = () => 0.5;
const flush = async () => { for (let i = 0; i < 5; i++) await new Promise((r) => setImmediate(r)); };
async function advance(ms) {
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
}
const ok = (body) => Promise.resolve({ ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(body)) });
global.fetch = (url, init) => { t.fetches.push([t.now, String(url)]); return t.serve(String(url), init); };
global.WebSocket = function (url) { const s = { url }; t.ws.push(s); return s; };
global.location = { search: D.search || '', host: 'example.org', protocol: 'https:', reload() {} };

const els = new Map();
function el(id) {
  if (!els.has(id)) {
    const cls = new Set();
    els.set(id, {
      id, hidden: id === 'public-banner' || id === 'about-more', dataset: {}, style: {}, textContent: '', innerHTML: '',
      title: '', href: id === 'almanac-link' ? 'almanac.html' : '', listeners: {}, opened: 0,
      classList: { add: (c) => cls.add(c), remove: (c) => cls.delete(c), contains: (c) => cls.has(c) },
      addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); },
      setAttribute(k, v) { this['@' + k] = String(v); },
      showModal() { this.opened++; },
    });
  }
  return els.get(id);
}
const meta = D.link == null ? null : { content: D.link, getAttribute: (k) => (k === 'content' ? D.link : null) };
global.document = {
  hidden: false, documentElement: el('html'), addEventListener() {}, removeEventListener() {},
  getElementById: el,
  querySelector: (sel) => (sel === '.voice' ? el('.voice') : sel === 'meta[name="swarm-public-link"]' ? meta : null),
  querySelectorAll: () => [],
};
if (D.dataset) el('html').dataset.public = '1';
const $ = el;
const S = { loaded: false, voice: { disabled: false }, selected: null, detail: null, detailAt: 0, detailErr: null };
const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ESC[c]);
function setText(e, text) { const s = text == null ? '' : String(text); if (e.textContent !== s) e.textContent = s; }
eval(fs.readFileSync(process.argv[2], 'utf8'));   // public.js
const out = {};
(async () => {
/*VIEWER*/
function onMessage(msg) {   // the viewer's, cut down: the clock of the last message and the first init
  lastMsgAt = performance.now();
  if (connState === 'connecting') setConn(DEMO ? 'demo' : 'live');
  t.msgs.push(msg.type);
  if (msg.type === 'init') { S.loaded = true; renderVeil(); }
}
const conn = () => ({ state: $('conn').dataset.state, label: $('conn-label').textContent, title: $('conn').title });
const veil = () => ({ title: $('veil-title').textContent, sub: $('veil-sub').textContent || $('veil-sub').innerHTML });
const lives = () => t.fetches.filter(([, u]) => u.startsWith('/public/live.json')).map(([at]) => at);
/*SCENARIO*/
  process.stdout.write(JSON.stringify(out));
})().catch((e) => { console.error(e); process.exit(1); });
"""

VIEWER_SCENARIOS = {
    "flag": "out.v = { PUBLIC, DEMO, poll: DETAIL_POLL_MS };",
    "down": """
      connect();
      out.connecting = { conn: conn(), veil: veil() };
      await advance(1200);                          // the feed gave up at 1 s (two failed opens)
      out.offline = { conn: conn(), veil: veil() };
      await advance(60000 - 1200);
      out.v = { lives: lives(), ws: t.ws.length, all_public: t.fetches.every(([, u]) => u.startsWith('/public/')) };""",
    "drops": """
      t.serve = (url) => (t.now >= 5000 ? Promise.reject(new Error('net'))
        : url.startsWith('/public/live.json') ? ok(D.LIVE1) : url.startsWith('/public/static.json') ? ok(D.STATIC) : ok({}));
      connect();
      await advance(100);
      out.live = conn();
      out.loaded = S.loaded;
      out.wishes = await api('/api/wishes');
      try { await apiPost('/api/voice', { text: 'hello' }); out.post = 'sent'; } catch (e) { out.post = e.status; }
      await advance(40000 - 100);
      out.v = { lives: lives(), inits: t.msgs.filter((m) => m === 'init').length, ws: t.ws.length,
                all_public: t.fetches.every(([, u]) => u.startsWith('/public/')) };""",
    "quiet": """
      t.serve = (url) => url.startsWith('/public/live.json') ? ok(D.LIVE1) : ok(D.STATIC);   // the same snapshot forever
      connect();
      await advance(10000);
      renderConn();
      out.at10 = conn();
      await advance(6000);
      renderConn();
      out.at16 = conn();""",
    "private": """
      connect();
      out.ws = t.ws.map((s) => s.url);
      out.connecting = { conn: conn(), veil: veil() };
      t.ws[0].onopen();
      out.live = conn();
      await advance(6000);
      renderConn();
      out.at6 = conn();
      t.ws[0].onclose();
      out.offline = { conn: conn(), veil: veil() };
      out.fetches = t.fetches.length;""",
    "enter": """
      enterPublicMode();
      const about = $('about-btn').listeners.click || [];
      about.forEach((f) => f({}));
      out.v = { is_public: $('html').classList.contains('is-public'), voice_hidden: $('.voice').hidden,
                voice_disabled: S.voice.disabled, banner_shown: !$('public-banner').hidden, about_opened: $('about').opened,
                more_shown: !$('about-more').hidden, link: $('about-link').href,
                almanac: { href: $('almanac-link').href, title: $('almanac-link').title } };""",
    "foot": """
      const txt = () => $('cre-foot').textContent;
      S.selected = 'c1';
      S.detailErr = 'HTTP 503'; renderDetailFoot(); const err = txt();
      S.detailErr = null; S.detailAt = 0; renderDetailFoot(); const loading = txt();
      S.detailAt = Date.now() - 2600; renderDetailFoot(); const fresh = txt();
      S.detailAt = Date.now() - 5200; renderDetailFoot(); const old = txt();
      S.detailAt = Date.now() - 1200; renderDetailFoot(); const one = txt();
      out.v = { err, loading, fresh, old, one, poll: DETAIL_POLL_MS };""",
}


def viewer_code() -> str:
    """The viewer's own code for the harness: its flags, the whole connection section, enterPublicMode and
    renderDetailFoot, cut from viewer.js as they are."""
    src = (WEB / "viewer.js").read_text()
    flags = [re.search(rf"^ *const {n} = [^;]*;", src, re.M).group(0) for n in ("params", "DEMO", "PUBLIC", "DETAIL_POLL_MS")]
    a = src.index("/* ============================================================ connection */")
    b = src.index("/* ============================================================== messages */")
    funcs = [f"function {n}() {{{function_body(src, n)}}}" for n in ("enterPublicMode", "renderDetailFoot")]
    return "\n".join(flags + [src[a:b]] + funcs)


def run_viewer(tmp_path, scenario: str, **data):
    harness = tmp_path / "viewer_harness.js"
    harness.write_text(VIEWER_HARNESS.replace("/*VIEWER*/", viewer_code()).replace("/*SCENARIO*/", VIEWER_SCENARIOS[scenario]))
    data = {"STATIC": STATIC, "LIVE1": LIVE1, "dataset": True, **data}
    r = subprocess.run([NODE, str(harness), str(WEB / "public.js")], input=json.dumps(data), capture_output=True,
                       text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@needs_node
@pytest.mark.parametrize("search,dataset,public", [
    ("", True, True),               # /public/app/: the server marks the page
    ("?public", False, True),       # the local preview of the private page
    ("?public=1&skin=ascii", False, True),
    ("", False, False),             # the private viewer
    ("?demo=1&public", False, False),
    ("?demo=1", True, False),       # the demo world never reads the feed
])
def test_public_mode_is_on_for_the_public_page_and_the_preview_only(tmp_path, search, dataset, public):
    v = run_viewer(tmp_path, "flag", search=search, dataset=dataset)["v"]
    assert v["PUBLIC"] is public and v["poll"] == (3000 if public else 1000)


@needs_node
def test_with_the_world_down_the_viewer_backs_off_and_says_so(tmp_path):
    out = run_viewer(tmp_path, "down")
    assert out["connecting"]["veil"] == {"title": "Connecting to the world…", "sub": "Fetching the latest snapshot."}
    assert out["offline"]["conn"]["state"] == "offline" and out["offline"]["conn"]["label"] == "Offline · retrying in 1s"
    assert out["offline"]["veil"] == {"title": "Can’t reach the world right now",
                                      "sub": "It runs on one Mac at home and may be restarting. Retrying in 1s."}
    # each attempt is the feed's open and its one retry a second later; between attempts the viewer's backoff
    expected, at = [], 0
    for gap in (500, 1000, 2000, 4000, 8000) + (15000,) * 3:
        expected += [at, at + 1000]
        at += 1000 + gap
    assert out["v"]["lives"] == [x for x in expected if x <= 60000]
    assert out["v"]["ws"] == 0 and out["v"]["all_public"]


@needs_node
def test_a_feed_that_drops_after_opening_gets_the_backoff_too(tmp_path):
    out = run_viewer(tmp_path, "drops")
    assert out["live"] == {"state": "live", "label": "Live, a few seconds behind",
                           "title": "Snapshots of the world, refreshed every few seconds"}
    assert out["loaded"] and out["wishes"] == {"can_answer": False, "wishes": LIVE1["wishes"]} and out["post"] == 403
    # opened at 0; polls at 3 s and 4 s (the same snapshot); the drop at 5 s: two failed polls close the feed at 6 s
    assert out["v"]["lives"] == [0, 3000, 4000, 5000, 6000, 6500, 7500, 8500, 9500, 11500, 12500, 16500, 17500,
                                 25500, 26500]
    assert out["v"]["inits"] == 1 and out["v"]["ws"] == 0 and out["v"]["all_public"]


@needs_node
def test_a_quiet_feed_is_stalled_after_15_seconds_not_5(tmp_path):
    out = run_viewer(tmp_path, "quiet")
    assert out["at10"]["state"] == "live" and out["at10"]["label"] == "Live, a few seconds behind"
    assert out["at16"] == {"state": "stalled", "label": "No ticks for 16s",
                           "title": "Snapshots of the world, refreshed every few seconds"}


@needs_node
def test_the_private_viewer_still_uses_the_socket_and_its_own_words(tmp_path):
    out = run_viewer(tmp_path, "private", dataset=False)
    assert out["ws"] == ["wss://example.org/ws/view"] and out["fetches"] == 0
    assert out["connecting"]["veil"]["title"] == "Connecting to the world…"
    assert "Waiting for the world server at" in out["connecting"]["veil"]["sub"]
    assert out["live"] == {"state": "live", "label": "Live", "title": "wss://example.org/ws/view"}
    assert out["at6"]["state"] == "stalled" and out["at6"]["label"] == "No ticks for 6s"
    assert out["offline"]["veil"]["title"] == "Can’t reach the world server"
    assert "python -m swarmworld.server" in out["offline"]["veil"]["sub"] and "?demo=1" in out["offline"]["veil"]["sub"]


@needs_node
def test_entering_public_mode_hides_the_voice_and_shows_the_banner(tmp_path):
    v = run_viewer(tmp_path, "enter", link="https://example.com/swarm?from=public&x=1")["v"]
    assert v == {"is_public": True, "voice_hidden": True, "voice_disabled": True, "banner_shown": True, "about_opened": 1,
                 "more_shown": True, "link": "https://example.com/swarm?from=public&x=1",
                 "almanac": {"href": "/public/app/almanac.html",
                             "title": "Almanac: the tech tree, every kind of thing and verb, and the census (opens in a new tab)"}}


@needs_node
@pytest.mark.parametrize("link", [None, "", "javascript:alert(1)", "data:text/html,hi", "/relative"])
def test_without_a_web_link_the_about_panel_keeps_its_more_line_hidden(tmp_path, link):
    v = run_viewer(tmp_path, "enter", link=link)["v"]
    assert v["more_shown"] is False and v["link"] == "" and v["banner_shown"] and v["voice_disabled"]


@needs_node
def test_the_detail_footer_speaks_of_a_few_seconds_in_public_mode(tmp_path):
    v = run_viewer(tmp_path, "foot")["v"]
    assert v == {"err": "Couldn’t load details (HTTP 503). Retrying every few seconds.", "loading": "Loading details…",
                 "fresh": "Details refresh every few seconds.", "old": "Details last updated 5s ago.",
                 "one": "Details refresh every few seconds.", "poll": 3000}
    private = run_viewer(tmp_path, "foot", dataset=False)["v"]
    assert private == {"err": "Couldn’t load details (HTTP 503). Retrying every second.", "loading": "Loading details…",
                       "fresh": "Details last updated 3s ago.", "old": "Details last updated 5s ago.",
                       "one": "Details refresh every second.", "poll": 1000}


def test_the_token_never_rewrites_the_public_almanac_link():
    html = (WEB / "index.html").read_text()
    inline = re.search(r"<script>\(function \(\) \{(.*?)\}\)\(\);</script>", html, re.S).group(1)
    assert "is-public" in inline and "almanac.html?token=" in inline


def test_keys_typed_in_a_dialog_stay_in_it():
    src = (WEB / "viewer.js").read_text()
    keydown = src[src.index("window.addEventListener('keydown', (e) => {"):]
    first = keydown[:keydown.index("if (e.metaKey || e.ctrlKey) return;")]
    assert "closest('dialog')" in first
