"""The viewer's art (stream S7): what the init message gives it, and that every kind gets drawn."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from swarmworld.server.persistence import restore
from swarmworld.server.state import ServerState
from swarmworld.world import registry
from swarmworld.world.catalog import Catalog
from swarmworld.world.model import World
from swarmworld.world.terrain import BIOMES, generate_world

WEB = Path(__file__).resolve().parent.parent / "web"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed")


def small_world(n=8):
    """A hand-built world: no packs have populated it, so it has no land data."""
    return World(n, n, [["g"] * n for _ in range(n)], Catalog.load())


def test_init_carries_biomes_and_flow():
    w = generate_world(7)
    init = w.to_init()
    land = init["nature"]
    _, y0, _, y1 = w.region_bounds("surface")  # one row per row of the surface (the deep has neither)
    assert len(land["biomes"]) == y1 - y0 and all(len(r) == w.width for r in land["biomes"])
    assert len(land["flow"]) == y1 - y0 and all(len(r) == w.width for r in land["flow"])
    assert set("".join(land["biomes"])) <= set(BIOMES)
    assert set("".join(land["flow"])) <= set(".01234567") and set("".join(land["flow"])) != {"."}  # rivers flow
    json.dumps(init)  # it goes over the socket


def test_init_names_every_kind_with_its_look_and_glyph():
    with registry.sandbox():
        registry.register_kinds({"test_hut": {"name": "test hut", "look": "hut", "glyph": {"char": "⌂", "color": "#c8a070"}}})
        kinds = small_world().to_init()["kinds"]
        assert set(kinds) == set(registry.KINDS)
    assert kinds["test_hut"] == {"name": "test hut", "look": "hut", "glyph": {"char": "⌂", "color": "#c8a070"}}
    assert kinds["firefly"]["glow"] == 2 and kinds["deer"]["look"] == "deer"


def test_init_without_nature_still_loads(prepack_save):
    w = small_world()  # a hand-built world has no land data: the viewer just draws its tiles
    assert "nature" not in w.to_init()
    st = ServerState(seed=1)
    restore(st, prepack_save)  # an old save: the pack derives the land when it loads
    init = st.world.to_init()
    assert len(init["nature"]["biomes"]) == 64 and init["width"] == 64
    del st.world.ext["nature"]
    assert "nature" not in st.world.to_init()


@needs_node
def test_every_js_file_parses():
    for js in sorted(WEB.glob("*.js")):
        r = subprocess.run([NODE, "--check", str(js)], capture_output=True, text=True)
        assert r.returncode == 0, f"{js.name}: {r.stderr}"


# A browser just good enough for tiles.js: canvases whose 2D context records what is drawn.
HARNESS = r"""
const fs = require('fs');
const calls = [];
// Each canvas remembers the text drawn on it, so a cached glyph canvas drawn later (drawImage) still counts.
function ctx2d(el) {
  return new Proxy({ calls }, {
    get(t, k) {
      if (k in t) return t[k];
      if (k === 'measureText') return (s) => ({ width: String(s).length * 8 });
      return (...a) => {
        if (k === 'fillText') { calls.push(String(a[0])); if (el) el._chars.push(String(a[0])); }
        if (k === 'drawImage' && a[0] && a[0]._chars) calls.push(...a[0]._chars);
        return { addColorStop() {} };
      };
    },
    set(t, k, v) { t[k] = v; return true; },
  });
}
global.document = { createElement: () => ({ getContext() { return ctx2d(this); }, _chars: [], width: 0, height: 0, style: {} }),
                    documentElement: { style: { setProperty() {} }, classList: { add() {} } } };
global.window = global;
global.getComputedStyle = () => ({ getPropertyValue: () => '' });
eval(fs.readFileSync(process.argv[2], 'utf8'));
const T = window.SwarmTiles;
const kinds = JSON.parse(fs.readFileSync(0, 'utf8'));
T.setKinds(kinds);
const out = {};
for (const kind of Object.keys(kinds)) {
  calls.length = 0;
  T.drawObject(ctx2d(), { id: 'o1', kind, x: 3, y: 4 }, 0, 0, 32, 1000);
  const look = T.kenneyLook(kind);
  out[kind] = { look, drawn: calls.slice() };
}
process.stdout.write(JSON.stringify(out));
"""


@needs_node
def test_every_installed_kind_renders_without_a_question_mark_in_the_kenney_skin(tmp_path):
    harness = tmp_path / "harness.js"
    harness.write_text(HARNESS)
    kinds = small_world().to_init()["kinds"]
    r = subprocess.run([NODE, str(harness), str(WEB / "tiles.js")], input=json.dumps(kinds),
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    drawn = json.loads(r.stdout)
    assert set(drawn) == set(kinds)
    for kind, d in drawn.items():
        look = d["look"]
        assert look["type"] in ("sprite", "glyph"), (kind, look)
        if look["type"] == "glyph":  # no Kenney art: a roguelike glyph, drawn on the tile
            assert look["char"] and look["char"] != "?", (kind, look)
            assert look["char"] in d["drawn"], (kind, d)
        assert "?" not in d["drawn"], (kind, d)
    # the glyph table covers the new kinds by hand; anything else falls back to the first letter of its name
    assert drawn["deer"]["look"]["char"] == "d" and drawn["well"]["look"]["char"] == "O"
    assert drawn["tree"]["look"]["type"] == "sprite"


# ------------------------------------------------------------------------------------------ roofs (stream S7b)
# A browser just good enough for roofs.js and the skins' drawRoof: a recording 2D context and fake canvases.
ROOF_HARNESS = r"""
const fs = require('fs');
const path = require('path');
const WEB = process.argv[2];
let calls = [];
function ctx2d(el) {
  const state = { globalAlpha: 1 };
  return new Proxy(state, {
    get(t, k) {
      if (k in t) return t[k];
      if (k === 'measureText') return (s) => ({ width: String(s).length * 8 });
      return (...a) => {
        calls.push({ fn: k, a, alpha: t.globalAlpha, el });
        if (k === 'fillText' && el) el._chars.push(String(a[0]));
        if (k === 'drawImage' && a[0] && a[0]._chars) for (const c of a[0]._chars) calls.push({ fn: 'fillText', a: [c], alpha: t.globalAlpha });
        return { addColorStop() {} };
      };
    },
    set(t, k, v) { t[k] = v; return true; },
  });
}
const mkCanvas = () => { const el = { _chars: [], width: 0, height: 0, style: {}, toDataURL: () => '' }; el.getContext = () => ctx2d(el); return el; };
global.document = { createElement: mkCanvas, documentElement: { style: { setProperty() {} }, classList: { add() {} } } };
global.window = global;
global.getComputedStyle = () => ({ getPropertyValue: () => '' });
global.performance = { now: () => 0 };
const load = (f) => (0, eval)(fs.readFileSync(path.join(WEB, f), 'utf8'));
const count = (fn) => calls.filter((c) => c.fn === fn).length;
const reset = () => { calls = []; };
const view = (o) => Object.assign({ ox: 0, oy: 0, ts: 32, x0: 0, y0: 0, x1: 40, y1: 40, dt: 1, zoom: 1, now: 0 }, o);
const B = (id, roof, x0 = 5, y0 = 5, x1 = 8, y1 = 8, design = 'hut') => ({ id, design, x0, y0, x1, y1, door: [x0 + 1, y1], roof });
const out = {};
"""

ROOF_FADE = ROOF_HARNESS + r"""
load('tiles.js'); load('roofs.js');
const R = window.SwarmRoofs;
const drawn = [];
const skin = { drawRoof: (ctx, b, x, y, w, h, ts, now) => { drawn.push([b.id, x, y, w, h]); } };
const ctx = ctx2d();
const frame = (v, fx, fy) => { drawn.length = 0; R.draw(ctx, skin, v, fx, fy); return drawn.map((d) => d[0]); };

R.set([B('roofed', true), B('open', false, 20, 5, 22, 7, 'well')]);
out.roofOnly = frame(view(), -1, -1);
R.set(null);                                   // no change
out.keptOnNull = frame(view(), -1, -1);
R.set('nonsense'); R.set([{ id: 'bad' }, null, B('roofed', true)]);   // old or odd data never breaks the draw
out.oddData = frame(view(), -1, -1);
R.set([B('roofed', true)]);
out.offscreen = frame(view({ x0: 30, x1: 60 }), -1, -1);
// the rectangle handed to the skin is the building's, in pixels
frame(view({ ox: 10, oy: 20 }), -1, -1);
out.rect = drawn[0].slice(1);
// outside (the floor is 6..7), at the door, and inside
out.outside = frame(view(), 3, 3);
out.onWall = frame(view(), 5, 6);              // a wall tile is not inside
out.insideAfter = frame(view(), 6, 6);          // dt = 1: the fade has finished
out.insideTarget = R.target(R.list[0], 1, 6, 6);
out.outsideTarget = R.target(R.list[0], 1, 3, 3);
out.doorTarget = R.target(R.list[0], 1, R.list[0].door[0], R.list[0].door[1]);
out.zoomedTarget = R.target(R.list[0], 4, -1, -1);
out.farTarget = R.target(R.list[0], 1, -1, -1);
// a short fade, not a cut: one small step leaves the roof partly there
R.set([B('roofed', true)]);
frame(view(), 3, 3);
const alphas = [];
for (let i = 0; i < 4; i++) { calls = []; frame(view({ dt: 0.03 }), 6, 6); alphas.push(drawn.length ? 1 : 0); }
out.fadeSteps = alphas;
R.set([B('roofed', true)]);
out.zoomedIn = frame(view({ zoom: 5 }), -1, -1);
process.stdout.write(JSON.stringify(out));
"""

ROOF_SKINS = ROOF_HARNESS + r"""
load('tiles.js');
const K = window.SwarmTiles;
const roofy = (fn) => { reset(); fn(); return { draws: count('drawImage'), fills: count('fillRect') + count('fill'), text: count('fillText') }; };
const ctx = ctx2d();
const b = B('b1', true, 5, 5, 9, 8, 'hut');
out.kenney = roofy(() => K.drawRoof(ctx, b, 160, 160, 160, 128, 32, 0));
out.kenneyAgain = roofy(() => K.drawRoof(ctx, b, 160, 160, 160, 128, 32, 0));     // cached: nothing is rebuilt
out.kenneyColors = ['tent', 'hut', 'storehouse', 'workshop', 'shed-unknown'].map((d) => K.roofColor(d));
load('ascii.js');
const A = window.SwarmASCII;
out.ascii = roofy(() => A.drawRoof(ctx, b, 160, 160, 160, 128, 32, 0));
out.asciiChars = [...new Set(calls.filter((c) => c.fn === 'fillText').map((c) => c.a[0]))];
out.hasRoofFns = [K.drawRoof, A.drawRoof].every((f) => typeof f === 'function');
process.stdout.write(JSON.stringify(out));
"""

ROOF_LIMEZU = ROOF_HARNESS + r"""
load('tiles.js');
const manifest = JSON.parse(fs.readFileSync(path.join(WEB, 'assets/limezu/manifest.json'), 'utf8'));
global.fetch = async () => ({ ok: true, json: async () => manifest });
global.Image = class { set src(v) { this.width = 64; this.height = 64; setTimeout(() => this.onload && this.onload(), 0); } };
load('limezu.js');
(async () => {
  const L = window.SwarmLimeZu;
  const ctx = ctx2d();
  const b = B('b1', true, 5, 5, 9, 8, 'workshop');
  reset(); L.drawRoof(ctx, b, 160, 160, 160, 128, 32, 0);
  out.beforeLoad = count('drawImage');          // sheets not loaded: the Kenney roof stands in
  out.loaded = await L.load();
  reset(); L.drawRoof(ctx, b, 160, 160, 160, 128, 32, 0);
  out.drawn = count('drawImage');
  out.fromSheet = calls.some((c) => c.fn === 'drawImage' && c.a[0] instanceof Image);   // painted from the roof sheet, not Kenney's
  out.slice = manifest.roofs.slice;
  out.designs = Object.keys(manifest.roofs.designs);
  process.stdout.write(JSON.stringify(out));
})();
"""


def run_roof_harness(tmp_path, script, name):
    harness = tmp_path / name
    harness.write_text(script)
    r = subprocess.run([NODE, str(harness), str(WEB)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@needs_node
def test_roofs_follow_the_data_and_fade_when_a_followed_creature_is_inside(tmp_path):
    out = run_roof_harness(tmp_path, ROOF_FADE, "roof_fade.js")
    assert out["roofOnly"] == ["roofed"]          # roof: true draws a roof; the well (roof: false) draws none
    assert out["keptOnNull"] == ["roofed"]        # buildings: null on a tick means no change
    assert out["oddData"] == ["roofed"]           # junk entries are ignored, not fatal
    assert out["offscreen"] == []                 # only buildings on screen are drawn
    assert out["rect"] == [10 + 5 * 32, 20 + 5 * 32, 4 * 32, 4 * 32]
    assert out["outside"] == ["roofed"] and out["onWall"] == ["roofed"]
    assert out["insideAfter"] == []               # a followed creature on the floor: the roof is gone
    assert out["insideTarget"] == 0 and out["outsideTarget"] == 1 and out["farTarget"] == 1
    assert out["doorTarget"] == 0                 # stepping in through the door starts the fade
    assert out["zoomedTarget"] == 0               # zoomed in past where interiors read
    assert out["zoomedIn"] == []
    assert out["fadeSteps"][0] == 1               # a short transition, not a cut


@needs_node
def test_roofs_are_drawn_by_the_kenney_and_ascii_skins(tmp_path):
    out = run_roof_harness(tmp_path, ROOF_SKINS, "roof_skins.js")
    assert out["hasRoofFns"]
    assert out["kenney"]["draws"] >= 1 and out["kenneyAgain"]["draws"] >= 1
    assert out["kenneyAgain"]["fills"] == 0 and out["kenneyAgain"]["text"] == 0   # a cached sprite: one drawImage
    assert len(set(out["kenneyColors"])) == 5     # each design its own color, and an unknown design still gets one
    assert out["ascii"]["text"] >= 12             # characters, a glyph per tile
    assert "^" in out["asciiChars"] and any(c in out["asciiChars"] for c in "▒▓")


@needs_node
@pytest.mark.skipif(not (WEB / "assets/limezu/manifest.json").exists(), reason="the LimeZu art is not installed")
def test_limezu_roofs_come_from_the_roof_sheet(tmp_path):
    if "roofs" not in json.loads((WEB / "assets/limezu/manifest.json").read_text()):
        pytest.skip("the LimeZu build has no roofs yet")
    out = run_roof_harness(tmp_path, ROOF_LIMEZU, "roof_limezu.js")
    assert out["beforeLoad"] >= 1                 # without its sheets the Kenney roof stands in
    assert out["loaded"] is True and out["drawn"] >= 1 and out["fromSheet"]
    assert {"tent", "hut", "storehouse", "workshop"} <= set(out["designs"])


# Moving things (wild game, farm animals) slide between ticks. Each move keeps its own clock: a later tick must
# not restart an earlier, finished move, or every animal snaps back a tile and slides again (rubber banding).
MOTION_HARNESS = r"""
const fs = require('fs');
global.window = global;
eval(fs.readFileSync(process.argv[2], 'utf8'));
const M = window.SwarmMotion;
const move = { fx: 10, fy: 5, tx: 11, ty: 5, at: 0 };   // a deer steps east on the tick at t=0
const out = { mid: M.slide(move, 500, 1000), later: M.slide(move, 1010, 1000), much_later: M.slide(move, 5000, 1000),
              before: M.slide(move, -50, 1000) };
process.stdout.write(JSON.stringify(out));
"""


@needs_node
def test_a_finished_move_stays_finished_when_the_next_tick_arrives(tmp_path):
    harness = tmp_path / "motion.js"
    harness.write_text(MOTION_HARNESS)
    r = subprocess.run([NODE, str(harness), str(WEB / "motion.js")], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    p = json.loads(r.stdout)
    assert p["mid"]["x"] == pytest.approx(10.5) and p["mid"]["t"] == pytest.approx(0.5)
    assert p["later"]["x"] == 11 and p["later"]["t"] == 1          # the next tick doesn't send it back to 10
    assert p["much_later"]["x"] == 11 and p["before"]["x"] == 10


def test_the_viewer_times_each_object_move_from_its_own_start():
    src = (WEB / "viewer.js").read_text()
    html = (WEB / "index.html").read_text()
    assert html.index('src="motion.js"') < html.index('src="viewer.js"')
    assert "SwarmMotion.slide(a, now, S.tickMs)" in src            # objPos uses the move's own clock, not S.tickAt
