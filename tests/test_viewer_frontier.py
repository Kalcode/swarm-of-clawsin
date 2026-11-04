"""The private viewer follows a growth (web/layers.js, tiles.js, the skins, viewer.js): `grow` then a fresh init from
the server, tile looks hashed on x - origin, terrain drawn in 32-column chunks, the camera kept on its spot."""

import json
import subprocess

import pytest

from swarmworld.server.public_view import public_static
from swarmworld.server.state import ServerState
from swarmworld.world.model import FrontierSettings
from swarmworld.world.packs.frontier import grow
from tests.test_viewer_layers import LZ_PLAIN, NODE, WEB, needs_node, run_layers, run_skin  # noqa: F401  (run_layers: fixture use)
from tests.test_viewer_layers import default_map  # noqa: F401  (fixture)

# Both tests below render the same rows (the default map: 128 surface rows with their nature rows, 128 deep rows) with
# each skin and group what is drawn by the tile its destination falls in.
PRELUDE = r"""
load('tiles.js'); load('ascii.js');
const K = window.SwarmTiles, A = window.SwarmASCII;
const manifest = %s;
global.fetch = async () => ({ ok: true, json: async () => JSON.parse(JSON.stringify(manifest)) });
global.Image = class { set src(v) { this.width = 512; this.height = 512; setTimeout(() => this.onload && this.onload(), 0); } };
load('limezu.js');
const Z = window.SwarmLimeZu;
const init = %s;
const SURFACE = init.tiles.slice(0, 128), DEEP = init.tiles.slice(160, 288);
const NATURE = { biomes: init.nature.biomes, flow: init.nature.flow };
const SKINS = { kenney: [K, 16], ascii: [A, 1], limezu: [Z, 16] };
// the calls on a canvas, grouped by the tile their destination falls in: "column,row" (the column counted as
// col + x0 - back) -> [fn, offset inside the tile, the other arguments, fill (of a fillRect), alpha]
function perTile(cv, T, x0, back) {
  const out = {};
  for (const c of calls) {
    if (c.el !== cv || c.fn === 'char') continue;
    let dx, dy, rest;
    if (c.fn === 'fillRect') { [dx, dy] = c.a; rest = c.a.slice(2); }
    else if (c.fn === 'drawImage' && c.a.length === 9) { dx = c.a[5]; dy = c.a[6]; rest = [c.a[1], c.a[2], c.a[3], c.a[4], c.a[7], c.a[8]]; }
    else continue;                                   // the smoothed tint passes cover many tiles at once
    const tx = Math.floor(dx / T), ty = Math.floor(dy / T);
    (out[(tx + x0 - back) + ',' + ty] = out[(tx + x0 - back) + ',' + ty] || []).push(JSON.stringify([c.fn, dx - tx * T, dy - ty * T, rest, c.fn === 'fillRect' ? c.fill : null, c.alpha === undefined ? 1 : c.alpha]));
  }
  return out;
}
// one render of the surface's rows then the deep's, with a span; returns the per-tile calls of both
function render(skin, surface, deep, nature, span, back) {
  const [S, T] = SKINS[skin];
  const res = {};
  for (const [name, rows, land, y0] of [['surface', surface, nature, 0], ['deep', deep, null, 128]]) {
    reset();
    const cv = S.renderTerrain(rows, rows[0].length, rows.length, land, span);
    const tiles = perTile(cv, T, span ? span.x0 : 0, back || 0);
    for (const k of Object.keys(tiles)) { const [x, y] = k.split(',').map(Number); res[x + ',' + (y + y0)] = tiles[k]; }
  }
  return res;
}
"""


def _prelude(init: dict) -> str:
    return PRELUDE % (json.dumps(LZ_PLAIN), json.dumps({"tiles": init["tiles"], "nature": init["nature"]}))


@pytest.fixture(scope="module")
def default_init():
    return ServerState(seed=7).world.to_init()


@needs_node
def test_chunked_terrain_matches_the_whole_map_in_every_skin(tmp_path, default_init):
    out = run_skin(tmp_path, _prelude(default_init) + """
      (async () => {
        await Z.load();
        for (const skin of Object.keys(SKINS)) {
          const whole = render(skin, SURFACE, DEEP, NATURE, null);
          const merged = {};
          for (const x0 of [0, 32, 64, 96]) {
            const part = render(skin, SURFACE, DEEP, NATURE, { x0, x1: x0 + 32, hx: 0 });
            for (const [k, v] of Object.entries(part)) merged[k] = v;
          }
          const keys = Object.keys(whole);
          out[skin] = { tiles: keys.length, columns: Math.max(...keys.map((k) => +k.split(',')[0])) + 1,
                         same: keys.length === Object.keys(merged).length && keys.every((k) => JSON.stringify(whole[k]) === JSON.stringify(merged[k])),
                        calls: keys.reduce((n, k) => n + whole[k].length, 0) };
        }
        process.stdout.write(JSON.stringify(out));
      })();
    """, "chunks.js", done=False)
    for skin in ("kenney", "ascii", "limezu"):
        assert out[skin]["same"], skin
        assert out[skin]["columns"] == 128 and out[skin]["tiles"] == 128 * 256, skin
        assert out[skin]["calls"] >= out[skin]["tiles"], skin      # something was drawn for every tile


@needs_node
def test_a_west_growth_keeps_the_old_map_looking_the_same(tmp_path, default_init):   # Review Focus 5
    out = run_skin(tmp_path, _prelude(default_init) + """
      (async () => {
        await Z.load();
        // 32 columns laid down west of the map: each row's first tile again, so the edge looks as it did
        const wider = (rows) => rows.map((r) => r[0].repeat(32) + r);
        for (const skin of Object.keys(SKINS)) {
          const before = render(skin, SURFACE, DEEP, NATURE, null);
          const nature = { biomes: wider(NATURE.biomes), flow: wider(NATURE.flow) };
          const after = render(skin, wider(SURFACE), wider(DEEP), nature, { x0: 32, x1: 160, hx: 32 }, 32);
          const bad = Object.keys(before).filter((k) => +k.split(',')[0] >= 1 && JSON.stringify(before[k]) !== JSON.stringify(after[k]));
          out[skin] = { bad: bad.slice(0, 5), compared: Object.keys(before).length };
        }
        K.setOrigin(32);
        out.origin = K.origin();
        out.hashes = [[0, 0, 3], [5, 9, 1], [127, 255, 44]].map(([x, y, s]) => [K.hashAt(x + 32, y, s), K.hash2(x, y, s)]);
        K.setOrigin(0);
        out.plain = K.hashAt(7, 3, 2) === K.hash2(7, 3, 2);
        process.stdout.write(JSON.stringify(out));
      })();
    """, "west.js", done=False)
    for skin in ("kenney", "ascii", "limezu"):
        assert out[skin]["bad"] == [] and out[skin]["compared"] == 128 * 256, skin
    assert out["origin"] == 32 and out["plain"]
    assert all(a == b for a, b in out["hashes"])


@needs_node
def test_chunk_spans_dirty_chunks_and_the_grow_shift(tmp_path, default_map):
    out = run_layers(tmp_path, default_map, """
      const R = L.regionsFrom(init);
      out.spans = L.chunkSpans(130);
      out.chunk = L.CHUNK;
      out.dirty = L.applyTiles(init.tiles, [[70, 5, 'w'], [3, 200, 'R']], R);
      delete out.dirty.tiles;
      out.none = L.applyTiles(init.tiles, [[999, 5, 'w']], R).chunks;
      out.sameChunk = L.applyTiles(init.tiles, [[64, 5, 'w'], [95, 6, 'w'], [96, 6, 'w']], R).chunks;
      out.edges = [63, 64, 0, 127, 96].map((x) => L.applyTiles(init.tiles, [[x, 5, 'w']], R).chunks);
      out.shift = [L.growShift({ side: 'west', columns: 32 }), L.growShift({ side: 'east', columns: 32 }), L.growShift(null)];
    """)
    assert out["spans"] == [[0, 32], [32, 64], [64, 96], [96, 128], [128, 130]] and out["chunk"] == 32
    assert out["dirty"] == {"dirty": ["surface", "deep"], "chunks": ["surface:64", "deep:0"]}
    assert out["none"] == []
    assert out["sameChunk"] == ["surface:32", "surface:64", "surface:96"]
    # a tile's neighbours (shorelines, wall rims, autotiles) are read across a chunk edge: both chunks are redrawn
    assert out["edges"] == [["surface:32", "surface:64"], ["surface:32", "surface:64"], ["surface:0"], ["surface:96"], ["surface:64", "surface:96"]]
    assert out["shift"] == [32, 0, 0]


def test_growth_reaches_viewers_as_grow_then_init():
    st = ServerState(seed=7, frontier=FrontierSettings(on=True, pace=0))
    assert [json.loads(p)["type"] for p in st.viewer_payloads(st.tick_dict([]))] == ["tick"]
    grow(st.world, "west")
    out = [json.loads(p) for p in st.viewer_payloads(st.tick_dict([]))]
    assert [m["type"] for m in out] == ["grow", "init", "tick"]
    assert out[0] == {"type": "grow", "side": "west", "columns": 32, "width": 160, "origin_x": 32}
    assert out[1]["origin_x"] == 32 and all(len(r) == 160 for r in out[1]["tiles"])
    assert [json.loads(p)["type"] for p in st.viewer_payloads(st.tick_dict([]))] == ["tick"]   # once


def test_two_strips_in_one_tick_send_two_grows_and_one_init():
    st = ServerState(seed=7, frontier=FrontierSettings(on=True, pace=0))
    grow(st.world, "west")
    grow(st.world, "east")
    out = [json.loads(p) for p in st.viewer_payloads(st.tick_dict([]))]
    assert [m["type"] for m in out] == ["grow", "grow", "init", "tick"] and out[2]["width"] == 192


def test_init_and_static_carry_the_origin():
    st = ServerState(seed=7)
    init = st.world.to_init()
    assert init["origin_x"] == 0 and public_static(init)["origin_x"] == 0
    st2 = ServerState(seed=7, frontier=FrontierSettings(on=True, pace=0))
    grow(st2.world, "west")
    assert public_static(st2.world.to_init())["origin_x"] == 32


def test_the_viewer_wires_growth():
    src = (WEB / "viewer.js").read_text()
    assert "case 'grow'" in src and "setOrigin(" in src and "chunkSpans(" in src
    assert "m.origin_x | 0) - T.origin()" in src   # the camera shifts with the init, not with the notice


@needs_node
def test_an_init_with_a_new_origin_keeps_the_camera_on_its_spot(tmp_path):
    """A viewer that reconnects after a west growth gets no `grow`, only the init: the shift comes with it."""
    out = run_viewer_init(tmp_path)
    assert out["cam"] == [10, 42] and out["voice"] == 42 and out["same"] == [5, 37]   # cam, voice target, an event's x
    assert out["noShift"] == 10                                                          # the same origin: nothing moves
    assert out["first"] == 32                                                            # the first init fits the map
    assert out["meadow"] == 70 and out["noMeadow"] == 48   # a fresh page centres on the meadow, else on the map's middle


def run_viewer_init(tmp_path) -> dict:
    """Loads viewer.js against a stub page (a Proxy for the DOM) and feeds it inits; returns what it did to the camera."""
    harness = tmp_path / "viewer_init.js"
    harness.write_text(VIEWER_HARNESS)
    r = subprocess.run([NODE, str(harness), str(WEB)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


VIEWER_HARNESS = r"""
const fs = require('fs'), path = require('path');
const WEB = process.argv[2];
const el = () => new Proxy(function () {}, {
  get(t, k) {
    if (k === Symbol.toPrimitive) return () => '';
    if (k === 'dataset') return {};
    if (k === 'style') return new Proxy({}, { get: () => () => '', set: () => true });
    if (k === 'classList') return { add() {}, remove() {}, toggle() {}, contains: () => false };
    if (k === 'children' || k === 'childNodes') return [];
    if (k === 'getContext') return () => new Proxy({}, { get: (a, b) => (b === 'measureText' ? () => ({ width: 0 }) : () => ({ addColorStop() {} })), set: () => true });
    if (k === 'getBoundingClientRect') return () => ({ left: 0, top: 0, width: 800, height: 600 });
    if (k === 'width' || k === 'height' || k === 'clientWidth' || k === 'clientHeight') return 800;
    if (k === 'length') return 0;
    return el();
  },
  set() { return true; },
  apply() { return el(); },
});
global.window = global;
global.document = new Proxy({}, { get: (t, k) => (k === 'readyState' ? 'loading' : k === 'fonts' ? undefined : k === 'documentElement' || k === 'body' ? el() : () => el()) });
document.addEventListener = () => {};
global.addEventListener = () => {};
global.localStorage = { getItem: () => null, setItem() {} };
global.location = { search: '', hostname: 'x', href: 'http://x/', protocol: 'http:', host: 'x' };
global.performance = { now: () => 1000 };
global.requestAnimationFrame = () => 0;
global.matchMedia = () => ({ matches: false, addEventListener() {} });
global.getComputedStyle = () => ({ getPropertyValue: () => '' });
global.Image = class {};
global.innerWidth = 800; global.innerHeight = 600;
global.fetch = async () => ({ ok: false, json: async () => ({}) });
global.WebSocket = class { constructor() {} close() {} };
global.ResizeObserver = class { observe() {} };
for (const f of ['tiles.js', 'layers.js', 'viewer.js']) {
  try { (0, eval)(fs.readFileSync(path.join(WEB, f), 'utf8')); } catch (e) { process.stderr.write(f + ': ' + e.stack + '\\n'); process.exit(2); }
}
const S = window.SwarmViewer.state;
const init = (width, origin) => ({ type: 'init', width, height: 64, origin_x: origin, tiles: Array.from({ length: 64 }, () => 'g'.repeat(width)),
  objects: [], creatures: [], regions: [], tick: 1 });
const out = {};
window.SwarmViewer.onMessage(init(64, 0));
out.first = S.cam.x;
S.cam.x = 10; S.cam.y = 20; S.voice.target = { x: 10, y: 3 }; S.events.push({ x: 5, y: 1 });
window.SwarmViewer.onMessage(init(64, 0));
out.noShift = S.cam.x;
window.SwarmViewer.onMessage(init(96, 32));        // a west strip: no `grow` first, as on a reconnect
out.cam = [10, S.cam.x]; out.voice = S.voice.target.x; out.same = [5, S.events[0].x];
S.loaded = false;                                  // a fresh page on a map grown unevenly: the meadow is not the middle
window.SwarmViewer.onMessage(Object.assign(init(96, 32), { landmarks: [{ kind: 'lake', x: 3, y: 4, name: 'l' }, { kind: 'meadow', x: 70, y: 40, name: 'm' }] }));
out.meadow = S.cam.x;
S.loaded = false;
window.SwarmViewer.onMessage(init(96, 32));
out.noMeadow = S.cam.x;
process.stdout.write(JSON.stringify(out), () => process.exit(0));   // the viewer's timers would keep it running
"""

