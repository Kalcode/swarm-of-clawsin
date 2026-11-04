"""The viewer's layers (web/layers.js): it shows one region at a time, the surface or the deep below it, and a switch
moves between them; following a creature that climbs switches with it. The pure logic runs in node harnesses."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from swarmworld.world.terrain import generate_world

WEB = Path(__file__).resolve().parent.parent / "web"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed")

# Loads layers.js as the browser does (a script that sets window.SwarmLayers), reads the init message from stdin,
# runs a test's body and prints its `out`.
HARNESS = r"""
const fs = require('fs');
global.window = global;
eval(fs.readFileSync(process.argv[2], 'utf8'));
const L = window.SwarmLayers;
const init = JSON.parse(fs.readFileSync(0, 'utf8'));
const out = {};
%s
process.stdout.write(JSON.stringify(out));
"""


def run_layers(tmp_path, init: dict, body: str) -> dict:
    harness = tmp_path / "layers_harness.js"
    harness.write_text(HARNESS % body)
    r = subprocess.run([NODE, str(harness), str(WEB / "layers.js")], input=json.dumps(init),
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@pytest.fixture
def default_map(two_levels) -> dict:
    """The init message of a world laid out like the default map: surface rows 0-127, rock 128-159, deep 160-287."""
    init = two_levels(128).to_init()
    return {k: init[k] for k in ("width", "height", "tiles", "regions")}


@needs_node
def test_regions_and_the_one_region_fallback(tmp_path, default_map):
    out = run_layers(tmp_path, default_map, """
      const R = L.regionsFrom(init);
      out.regions = R.map((r) => [r.name, r.level, r.y0, r.y1, r.height]);
      out.at = [20, 127, 128, 140, 159, 160, 287, 288, -1].map((y) => (L.regionAt(R, y) || { name: null }).name);
      out.deep = L.byName(R, 'deep').y0;
      out.nowhere = L.byName(R, 'nowhere');
      out.other = [L.otherLayer(R, 'surface'), L.otherLayer(R, 'deep')];
      const one = L.regionsFrom({ width: 64, height: 64, tiles: [] });          // an older server sends no regions
      out.one = one.map((r) => [r.name, r.level, r.y0, r.y1, r.height]);
      out.oneOther = L.otherLayer(one, 'surface');
      out.junk = L.regionsFrom({ height: 40, regions: [null, { name: 'x' }, { name: 'y', y0: 9, y1: 3 }] }).map((r) => r.name);
      const three = R.concat([{ name: 'deeper', level: -2, y0: 320, y1: 448, height: 128 }]);
      out.three = ['surface', 'deep', 'deeper'].map((n) => L.otherLayer(three, n));
    """)
    assert out["regions"] == [["surface", 0, 0, 128, 128], ["deep", -1, 160, 288, 128]]
    assert out["at"] == ["surface", "surface", None, None, None, "deep", "deep", None, None]
    assert out["deep"] == 160 and out["nowhere"] is None
    assert out["other"] == ["deep", "surface"]
    assert out["one"] == [["surface", 0, 0, 64, 64]] and out["oneOther"] == "surface"
    assert out["junk"] == ["surface"]                       # nothing usable: one surface region of the map's height
    assert out["three"] == ["deep", "deeper", "surface"]    # with more levels: the next one down, then back up


@needs_node
def test_switching_keeps_x_and_the_row_offset(tmp_path, default_map):
    out = run_layers(tmp_path, default_map, """
      const R = L.regionsFrom(init);
      const cam = { x: 40, y: 20 };
      out.down = L.moveCam(cam, R, 'surface', 'deep');
      out.up = L.moveCam(out.down, R, 'deep', 'surface');
      out.fraction = L.moveCam({ x: 12.5, y: 63.25 }, R, 'surface', 'deep');
      out.untouched = cam;
      const short = [R[0], { name: 'deep', level: -1, y0: 160, y1: 184, height: 24 }];
      out.short = L.moveCam({ x: 5, y: 100 }, short, 'surface', 'deep');   // past a shorter region's last row
      out.unknown = L.moveCam(cam, R, 'surface', 'nowhere');
    """)
    assert out["down"] == {"x": 40, "y": 180}
    assert out["up"] == {"x": 40, "y": 20}
    assert out["fraction"] == {"x": 12.5, "y": 223.25}
    assert out["untouched"] == {"x": 40, "y": 20}          # pure: the camera handed in is not moved
    assert out["short"] == {"x": 5, "y": 184}
    assert out["unknown"] == {"x": 40, "y": 20}


@needs_node
def test_the_camera_stays_in_the_shown_region(tmp_path, default_map):
    out = run_layers(tmp_path, default_map, """
      const R = L.regionsFrom(init), surface = L.byName(R, 'surface'), deep = L.byName(R, 'deep');
      const cam = { x: -5, y: 140 };
      out.intoDeep = L.clampCam(cam, deep, init.width);
      out.pastDeep = L.clampCam({ x: 300, y: 400 }, deep, init.width);
      out.inDeep = L.clampCam({ x: 40, y: 200.5 }, deep, init.width);
      out.surface = L.clampCam({ x: 40, y: 150 }, surface, init.width);
      out.above = L.clampCam({ x: 40, y: -9 }, surface, init.width);
      out.untouched = cam;
    """)
    assert out["intoDeep"] == {"x": 0, "y": 160}            # the band of rock above the deep is not shown with it
    assert out["pastDeep"] == {"x": 128, "y": 288}
    assert out["inDeep"] == {"x": 40, "y": 200.5}
    assert out["surface"] == {"x": 40, "y": 128}            # nor below the surface
    assert out["above"] == {"x": 40, "y": 0}
    assert out["untouched"] == {"x": -5, "y": 140}


@needs_node
def test_following_a_climber_switches_the_layer(tmp_path, default_map):
    out = run_layers(tmp_path, default_map, """
      const R = L.regionsFrom(init);
      out.down = L.followLayer(R, 'surface', 200);
      out.up = L.followLayer(R, 'deep', 20);
      out.bandFromSurface = L.followLayer(R, 'surface', 140);   // between regions: the view stays where it is
      out.bandFromDeep = L.followLayer(R, 'deep', 140);
      out.stays = L.followLayer(R, 'deep', 175);
      // a creature walks on the surface, climbs down at a cave mouth, walks below, and climbs back up
      let layer = 'surface';
      out.trip = [20, 21, 181, 182, 22].map((y) => (layer = L.followLayer(R, layer, y)));
    """)
    assert out["down"] == "deep" and out["up"] == "surface"
    assert out["bandFromSurface"] == "surface" and out["bandFromDeep"] == "deep"
    assert out["stays"] == "deep"
    assert out["trip"] == ["surface", "surface", "deep", "deep", "surface"]


@needs_node
def test_counts_by_region(tmp_path, default_map):
    out = run_layers(tmp_path, default_map, """
      const R = L.regionsFrom(init);
      const ys = [10, 127, 160, 200, 287, 140, 300];
      out.counts = L.counts(ys.map((y, i) => ({ id: 'c' + i, x: 4, y })).concat([{ id: 'nowhere' }, null]), R);
      out.none = L.counts([], R);
    """)
    assert out["counts"] == {"surface": 2, "deep": 3}        # the band and off the map count for neither
    assert out["none"] == {"surface": 0, "deep": 0}


@needs_node
def test_tile_changes_mark_their_region_dirty(tmp_path, default_map):
    out = run_layers(tmp_path, default_map, """
      const R = L.regionsFrom(init);
      const before = init.tiles[200];
      const one = L.applyTiles(init.tiles, [[5, 200, 't']], R);
      out.one = { dirty: one.dirty, row: one.tiles[200], same: one.tiles[199] === init.tiles[199],
                  untouched: init.tiles[200] === before, length: one.tiles.length };
      const many = L.applyTiles(init.tiles, [
        [1, 2, 'd'], [3, 170, 'u'], [4, 140, 'c'],                      // the surface, the deep, the band of rock
        [999, 5, 'x'], [5, 999, 'x'], [-1, 3, 'x'], ['a', 3, 'x'], [2, 3, 'ab'], [2, 3, ''], null, [7],
      ], R);
      out.many = { dirty: many.dirty, r2: many.tiles[2].slice(0, 3), r170: many.tiles[170][3], r140: many.tiles[140][4],
                   r3: many.tiles[3] === init.tiles[3], r5: many.tiles[5] === init.tiles[5] };
      const none = L.applyTiles(init.tiles, null, R);
      out.none = { dirty: none.dirty, same: none.tiles === init.tiles };
    """)
    row = default_map["tiles"][200]
    assert out["one"] == {"dirty": ["deep"], "row": row[:5] + "t" + row[6:], "same": True, "untouched": True,
                          "length": 288}
    assert out["many"]["dirty"] == ["surface", "deep"]          # in the regions' order; the band's change marks none
    assert out["many"]["r2"] == "gdg" and out["many"]["r170"] == "u" and out["many"]["r140"] == "c"
    assert out["many"]["r3"] and out["many"]["r5"]             # the out-of-range and malformed entries are ignored
    assert out["none"] == {"dirty": [], "same": True}


@pytest.fixture(scope="module")
def land_inits() -> dict:
    """Init messages of real generated worlds: with the deep (288 rows, land rows for the 128 of the surface) and
    without it (128 rows, 128 land rows)."""
    def pick(init):
        return {k: init[k] for k in ("width", "height", "regions", "nature")}
    return {"deep": pick(generate_world(7).to_init()), "flat": pick(generate_world(7, deep=False).to_init())}


@needs_node
def test_the_land_rows_are_the_surfaces(tmp_path, land_inits):
    deep, flat = land_inits["deep"], land_inits["flat"]
    assert deep["height"] == 288 and len(deep["nature"]["biomes"]) == 128           # the surface's rows only
    assert flat["height"] == 128 and len(flat["nature"]["biomes"]) == 128
    out = run_layers(tmp_path, land_inits, """
      const land = (i) => L.landFor(i.nature, i.width, L.regionsFrom(i));
      const used = (got, i) => got && [got.biomes === i.nature.biomes, got.flow === i.nature.flow];
      out.deep = used(land(init.deep), init.deep);
      out.flat = used(land(init.flat), init.flat);
      const n = init.deep.nature;
      out.short = land({ ...init.deep, nature: { biomes: n.biomes.slice(1), flow: n.flow.slice(1) } });
      const half = land({ ...init.deep, nature: { biomes: n.biomes, flow: n.flow.slice(1) } });
      out.half = half && [half.biomes === n.biomes, half.flow];
      out.narrow = land({ ...init.deep, nature: { biomes: n.biomes.map((r) => r.slice(1)) } });
      out.none = [land({ ...init.deep, nature: undefined }), land({ ...init.deep, nature: 'rows' })];
      out.noSurface = L.landFor(n, init.deep.width, L.regionsFrom(init.deep).filter((r) => r.name !== 'surface'));
    """)
    assert out["deep"] == [True, True]          # a world with a deep keeps its biomes and rivers
    assert out["flat"] == [True, True]          # a world without one, as before
    assert out["short"] is None                 # a row short of the surface: no land
    assert out["half"] == [True, None]          # the good rows are kept, the bad ones dropped
    assert out["narrow"] is None
    assert out["none"] == [None, None]
    assert out["noSurface"] is None


def test_the_viewer_wires_the_switch():
    src, html = (WEB / "viewer.js").read_text(), (WEB / "index.html").read_text()
    assert html.index('src="layers.js"') < html.index('src="viewer.js"') and 'id="layer-switch"' in html
    assert "SwarmLayers.followLayer" in src and "m.tiles" in src
    assert "SwarmLayers.landFor(m.nature" in src and "function landRows" not in src   # one rule for the land rows


# ------------------------------------------------------------------------------------------ the deep (Task 14)
@needs_node
def test_underground_lights_come_from_fires_glows_carried_lights_and_open_pits(tmp_path, default_map):
    out = run_layers(tmp_path, default_map, """
      const R = L.regionsFrom(init), surface = L.byName(R, 'surface'), deep = L.byName(R, 'deep');
      const tiles = init.tiles.slice();
      const put = (x, y, c) => { tiles[y] = tiles[y].slice(0, x) + c + tiles[y].slice(x + 1); };
      put(10, 20, 'O');                     // an open pit on the surface: daylight falls into the deep right below it
      put(0, 0, 'O');                       // one in the map's corner: only what lies inside the deep is lit
      const objects = [
        { id: 'f1', kind: 'campfire', x: 30, y: 200, lit: true },
        { id: 'f2', kind: 'campfire', x: 31, y: 200, lit: false },       // gone out: no light
        { id: 'k1', kind: 'crystal_cluster', x: 40, y: 210 },
        { id: 'r1', kind: 'rock', x: 41, y: 210 },
        { id: 'f3', kind: 'campfire', x: 5, y: 5, lit: true },           // on the surface
        { id: 'b1', kind: 'firefly', x: 6, y: 5 },
      ];
      const data = { crystal_cluster: { glow: 2 }, firefly: { glow: 2 }, rock: { name: 'rock' } };
      const kindInfo = (k) => data[k] || null;
      const creatures = [{ x: 50, y: 220, light: 4 }, { x: 51, y: 221 }, { x: 7, y: 7, light: 4 }];
      const pick = (ls) => ls.map((l) => [l.type, l.x, l.y, l.r, l.a]);
      out.deep = pick(L.lightsFor(deep, objects, creatures, kindInfo, tiles, R, 1));
      out.night = L.lightsFor(deep, objects, creatures, kindInfo, tiles, R, 0.25).filter((l) => l.type === 'sky').map((l) => l.a);
      out.surface = pick(L.lightsFor(surface, objects, creatures, kindInfo, tiles, R, 1));
      out.dark = L.lightsFor(deep, [], [], kindInfo, init.tiles, R, 1);
    """)
    deep = {tuple(x) for x in out["deep"]}
    sky = {t for t in deep if t[0] == "sky"}
    assert deep - sky == {("fire", 30, 200, 4.6, 1), ("glow", 40, 210, 2.5, 1), ("carried", 50, 220, 4, 1)}
    # under the pit at (10, 20): the tile right below it (10, 180) and its neighbours; under the corner pit only the
    # tiles inside the deep
    below = {(x, y) for x in (9, 10, 11) for y in (179, 180, 181)} | {(0, 160), (1, 160), (0, 161), (1, 161)}
    assert {(x, y) for _, x, y, _, _ in sky} == below and len(sky) == len(below)
    assert {(r, a) for _, _, _, r, a in sky} == {(1.2, 1)}      # as bright as the day above
    assert out["night"] == [0.25] * len(below)                  # at night, as dim as the night
    assert {t[0] for t in out["surface"]} == {"fire", "glow", "carried"}   # no skylight on the surface
    assert all(y < 128 for _, _, y, _, _ in out["surface"])     # none from the deep, and none from the surface below
    assert out["dark"] == []                                    # nothing lit: the deep is dark


@needs_node
def test_coordinates_below_are_counted_from_the_top_of_the_deep(tmp_path, default_map):
    out = run_layers(tmp_path, default_map, """
      const R = L.regionsFrom(init);
      out.text = [[40, 20], [40, 221], [3, 160], [40, 140]].map(([x, y]) => L.placeText(R, x, y));
      out.compact = L.placeText(R, 40, 221, ',');
    """)
    assert out["text"] == ["40, 20", "40, 61 below", "3, 0 below", "40, 140"]   # the band's rows stay as they are
    assert out["compact"] == "40,61 below"


# A browser just good enough for the skins' terrain: canvases whose 2D context records fills and the glyphs drawn.
SKIN_HARNESS = r"""
const fs = require('fs');
const path = require('path');
const WEB = process.argv[2];
let calls = [];
function ctx2d(el) {
  const state = {};
  return new Proxy(state, {
    get(t, k) {
      if (k in t) return t[k];
      if (k === 'measureText') return (s) => ({ width: String(s).length * 8 });
      return (...a) => {
        calls.push({ fn: k, a, fill: t.fillStyle, alpha: t.globalAlpha, el });
        if (k === 'fillText' && el) el._chars.push(String(a[0]));
        if (k === 'drawImage' && a[0] && a[0]._chars) for (const c of a[0]._chars) calls.push({ fn: 'char', a: [c] });
        return { addColorStop() {} };
      };
    },
    set(t, k, v) { t[k] = v; return true; },
  });
}
const mkCanvas = () => { const el = { _chars: [], width: 0, height: 0, style: {}, toDataURL: () => '' }; el.getContext = () => ctx2d(el); return el; };
global.document = { createElement: mkCanvas, documentElement: { style: { setProperty() {} }, classList: { add() {}, toggle() {} } } };
global.window = global;
global.getComputedStyle = () => ({ getPropertyValue: () => '' });
global.performance = { now: () => 0 };
const load = (f) => (0, eval)(fs.readFileSync(path.join(WEB, f), 'utf8'));
const reset = () => { calls = []; };
const chars = () => calls.filter((c) => c.fn === 'char').map((c) => c.a[0]);
const out = {};
"""

CODES = "gdswWrfRcuthO"


def run_skin(tmp_path, body: str, name: str, done: bool = True) -> dict:
    """Runs a body in SKIN_HARNESS and returns its `out` (a body that runs async writes it itself: done=False)."""
    harness = tmp_path / name
    harness.write_text(SKIN_HARNESS + body + ("\nprocess.stdout.write(JSON.stringify(out));" if done else ""))
    r = subprocess.run([NODE, str(harness), str(WEB)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@needs_node
def test_every_tile_code_renders_in_the_kenney_and_ascii_skins(tmp_path):
    out = run_skin(tmp_path, """
      load('tiles.js'); load('ascii.js');
      const K = window.SwarmTiles, A = window.SwarmASCII, CODES = '%s';
      out.names = Object.fromEntries([...CODES].map((c) => [c, K.terrainName(c)]));
      out.own = [...CODES].filter((c) => Object.prototype.hasOwnProperty.call(K.TERRAIN, c));
      out.water = [...CODES].filter((c) => K.isWater(c));
      // Kenney: each tile of the pre-rendered row is filled with its own ground's colors
      reset(); K.renderTerrain([CODES], CODES.length, 1, null);
      const base = (x, s) => (calls.find((c) => c.fn === 'fillRect' && c.a[0] === x * s && c.a[1] === 0 && c.a[2] === s) || {}).fill;
      out.kenney = Object.fromEntries([...CODES].map((c, x) => [c, [base(x, 16), K.TERRAIN[c] ? K.TERRAIN[c].base : null]]));
      out.lum = K.rgb(K.TERRAIN.O.base[0]).reduce((a, b) => a + b, 0) / 765;
      // ASCII: a background per tile, then its characters, drawn live
      reset(); A.renderTerrain([CODES], CODES.length, 1, null);
      out.asciiBg = [...CODES].map((c, x) => base(x, 1));
      out.ascii = {};
      for (const c of CODES) { reset(); A.drawGround(ctx2d(), [c + c, c + c], new Map(), 0, 0, 1, 1, 0, 0, 32, 1000); out.ascii[c] = [...new Set(chars())]; }
      // the surface's land held (biomes and flow for 2 rows): rows past it draw without biome or flow
      reset(); A.renderTerrain(['gw', 'gw'], 2, 2, { biomes: ['kk', 'kk'], flow: ['.0', '.0'] });
      reset(); A.drawGround(ctx2d(), ['gw', 'gw', 'cu', 'cu'], new Map(), 0, 2, 1, 3, 0, 0, 32, 1000);
      out.pastLand = [...new Set(chars())].sort();
    """ % CODES, "skins_tiles.js")
    names = out["names"]
    assert names["R"] == "rock wall" and names["c"] == "cave floor" and names["u"] == "cave water"
    assert names["t"] == "trench" and names["h"] == "pit" and names["O"] == "open pit"
    assert "unknown ground" not in names.values() and len(set(names.values())) == len(CODES)
    assert out["own"] == list(CODES)                          # no code falls back to grass
    assert out["water"] == ["w", "W", "u"]                    # cave water is water: glints and shorelines
    for code, (drawn, palette) in out["kenney"].items():
        assert drawn in palette, (code, drawn, palette)
    assert out["lum"] < 0.05                                  # an open pit is near black
    assert len(set(out["asciiBg"][CODES.index("R"):])) == 6   # each deep and dug code its own background
    assert out["ascii"]["R"] == ["#"] and out["ascii"]["c"] == ["."] and out["ascii"]["u"] == ["~"]
    assert out["ascii"]["t"] == ["="] and out["ascii"]["h"] == ["o"] and out["ascii"]["O"] == ["◎"]
    assert all("?" not in chars for chars in out["ascii"].values())
    assert out["pastLand"] == [".", "~"]                      # no river arrows or crest, no marsh grass, past the land


# A LimeZu build without art for the deep (flats for the surface's ground only), and one whose packs had some.
LZ_TERRAIN = {"sheet": "terrain", "tint": {"W": "rgba(8,30,70,0.38)"},
              "flats": {c: [[16 * i, 0, 16, 16]] for i, c in enumerate("gfdsrwW")},
              "autotiles": {"shore": {"set": [0, 16], "inner": [48, 16]}, "grassHole": {"set": [0, 64], "inner": [48, 64]}},
              "decor": {"sheet": "objects", "variants": [{"rect": [0, 0, 4, 4]}]},
              "pebbles": {"sheet": "objects", "variants": [{"rect": [4, 0, 4, 4]}]}}
LZ_PLAIN = {"sheets": {"terrain": "terrain.png", "objects": "objects.png"}, "characters": {"layers": []}, "animals": {},
            "objects": {}, "terrain": LZ_TERRAIN}
LZ_OWN = {**LZ_PLAIN, "terrain": {**LZ_TERRAIN, "flats": {**LZ_TERRAIN["flats"], "R": [[160, 0, 16, 16]], "c": [[176, 0, 16, 16]]}}}


@needs_node
def test_the_limezu_skin_draws_the_deep_from_its_flats_or_the_kenney_palette(tmp_path):
    out = run_skin(tmp_path, """
      load('tiles.js');
      const K = window.SwarmTiles, manifests = %s;
      let manifest = manifests.plain;
      global.fetch = async () => ({ ok: true, json: async () => JSON.parse(JSON.stringify(manifest)) });
      global.Image = class { set src(v) { this.width = 512; this.height = 512; setTimeout(() => this.onload && this.onload(), 0); } };
      load('limezu.js');
      const L = window.SwarmLimeZu, row = 'gRcuthO';
      const look = () => {
        reset(); L.renderTerrain([row], row.length, 1, null);
        return [...row].map((c, x) => {
          const flat = calls.find((k) => k.fn === 'drawImage' && k.a.length === 9 && k.a[3] === 16 && k.a[5] === x * 16);
          const fill = calls.find((k) => k.fn === 'fillRect' && k.a[0] === x * 16 && k.a[1] === 0 && k.a[2] === 16 && k.a[3] === 16);
          const edges = calls.filter((k) => k.fn === 'drawImage' && k.a.length === 9 && k.a[3] === 8 && k.a[5] >= x * 16 && k.a[5] < x * 16 + 16);
          return { flat: flat ? [flat.a[1], flat.a[2]] : null, fill: fill ? fill.fill : null, edges: edges.length };
        });
      };
      (async () => {
        out.loaded = await L.load();
        out.plain = look();
        out.masks = calls.filter((k) => k.fn === 'fillRect' && k.a[2] === 1 && k.a[3] === 1).map((k) => [k.a[0], k.fill]);
        out.palette = Object.fromEntries([...'RcthO'].map((c) => [c, K.TERRAIN[c].base]));
        manifest = manifests.own;
        await L.load();
        out.own = look();
        process.stdout.write(JSON.stringify(out));
      })();
    """ % json.dumps({"plain": LZ_PLAIN, "own": LZ_OWN}), "skins_limezu.js", done=False)
    assert out["loaded"] is True
    plain, own, palette = out["plain"], out["own"], out["palette"]
    assert plain[0]["flat"] == [0, 0]                         # grass: its flat
    for i, code in enumerate("Rc", start=1):                  # no flat for the deep: the Kenney palette, speckled
        assert plain[i]["flat"] is None and plain[i]["fill"] in palette[code], (code, plain[i])
    assert plain[3]["flat"] == [80, 0]                        # cave water: the pack's water...
    assert any(x == 3 and fill != "rgba(8,30,70,0.38)" for x, fill in out["masks"])   # ...darkened
    assert plain[2]["edges"] == 0                             # and no beach on the cave floor beside it
    for i, code in enumerate("thO", start=4):
        assert plain[i]["flat"] is None and plain[i]["fill"] in palette[code], (code, plain[i])
    assert own[1]["flat"] == [160, 0] and own[2]["flat"] == [176, 0]   # a build with flats of its own uses them
    assert own[4]["flat"] is None and own[4]["fill"] in palette["t"]


@needs_node
def test_no_weather_falls_in_the_deep(tmp_path):
    out = run_skin(tmp_path, """
      load('tiles.js'); load('effects.js');
      const FX = window.SwarmFX;
      const S = { clock: {}, tiles: ['cc', 'cc'], land: null, lit: [], objAt: new Map(), cres: new Map() };
      const V = (sky) => ({ S, skin: { name: 'kenney' }, ox: 0, oy: 0, ts: 32, x0: 0, y0: 0, x1: 1, y1: 1, vw: 400, vh: 300,
                            dpr: 1, now: 0, dt: 1, zoom: 2, sky });
      const frame = (sky) => {
        reset(); const ctx = ctx2d(); FX.under(ctx, V(sky)); FX.over(ctx, V(sky)); FX.sky(ctx, V(sky));
        return { lines: calls.filter((c) => c.fn === 'lineTo').length,
                 screen: calls.filter((c) => (c.fn === 'fillRect' && c.a[2] >= 400) || c.fn === 'drawImage').length };
      };
      for (const w of ['rain', 'storm', 'fog', 'heat']) {
        S.clock.weather = w;
        for (let i = 0; i < 10; i++) frame(true);            // the weather sets in
        out[w] = { surface: frame(true), deep: frame(false) };
      }
    """, "effects_deep.js")
    for w in ("rain", "storm", "fog", "heat"):
        assert out[w]["surface"]["lines"] + out[w]["surface"]["screen"] > 0, w    # above, it shows
        assert out[w]["deep"] == {"lines": 0, "screen": 0}, w                    # below, none of it


@needs_node
def test_rain_falls_through_an_open_pit_only(tmp_path):
    """Below, a creature on a tile open to the sky is told it rains: the viewer draws the rain there, clipped to those
    tiles, and nowhere else in the deep; fog and heat stay above."""
    out = run_skin(tmp_path, """
      load('tiles.js'); load('effects.js');
      const FX = window.SwarmFX;
      const S = { clock: {}, tiles: ['cc', 'cc'], land: null, lit: [], objAt: new Map(), cres: new Map() };
      const V = (skylit) => ({ S, skin: { name: 'kenney' }, ox: 0, oy: 0, ts: 32, x0: 0, y0: 0, x1: 1, y1: 1, vw: 400,
                               vh: 300, dpr: 1, now: 0, dt: 1, zoom: 2, sky: false, skylit });
      const frame = (skylit) => {
        reset(); const ctx = ctx2d(); FX.under(ctx, V(skylit)); FX.over(ctx, V(skylit)); FX.sky(ctx, V(skylit));
        return { lines: calls.filter((c) => c.fn === 'lineTo').length, clip: calls.filter((c) => c.fn === 'clip').length,
                 rects: calls.filter((c) => c.fn === 'rect').map((c) => c.a),
                 screen: calls.filter((c) => (c.fn === 'fillRect' && c.a[2] >= 400) || c.fn === 'drawImage').length };
      };
      for (const w of ['rain', 'fog', 'heat']) {
        S.clock.weather = w;
        for (let i = 0; i < 10; i++) frame(null);
        out[w] = { pit: frame([{ x: 1, y: 3 }]), none: frame([]), old: frame(undefined) };
      }
    """, "effects_pit.js")
    assert out["rain"]["pit"]["lines"] > 0 and out["rain"]["pit"]["clip"] == 1
    assert out["rain"]["pit"]["rects"] == [[32, 96, 32, 32]]          # just the tile under the open pit
    for w in ("rain", "fog", "heat"):
        assert out[w]["none"] == out[w]["old"] == {"lines": 0, "clip": 0, "rects": [], "screen": 0}, w
        assert out[w]["pit"]["screen"] == 0, w
    assert out["fog"]["pit"]["lines"] == out["heat"]["pit"]["lines"] == 0


@needs_node
def test_skylit_tiles_and_the_holes_round_unlit_creatures(tmp_path, default_map):
    out = run_layers(tmp_path, default_map, """
      const R = L.regionsFrom(init), deep = L.byName(R, 'deep'), surface = L.byName(R, 'surface');
      const tiles = init.tiles.slice();
      tiles[20] = tiles[20].slice(0, 10) + 'O' + tiles[20].slice(11);
      out.lit = L.skylitTiles(deep, tiles, R).map((t) => [t.x, t.y]);
      out.sky = L.lightsFor(deep, [], [], () => null, tiles, R, 1).filter((l) => l.type === 'sky').map((l) => [l.x, l.y]);
      out.none = L.skylitTiles(deep, init.tiles, R).length;
      out.top = L.skylitTiles(surface, tiles, R).length;
      out.holes = [{}, { asleep: true }, { sleeping: true }, { light: 4 }, { light: 4, asleep: true }, null].map(L.darkHole);
    """)
    assert sorted(map(tuple, out["lit"])) == sorted((x, y) for x in (9, 10, 11) for y in (179, 180, 181))
    assert out["sky"] == out["lit"] and out["none"] == 0 and out["top"] == 0
    awake, asleep, sleeping, lit, lit_asleep, none = out["holes"]
    assert awake == {"r": 1.5, "a": 0.5}                              # the step an unlit creature sees
    assert asleep == sleeping and 0 < asleep["r"] < awake["r"] and 0 < asleep["a"] < awake["a"]   # faint, but there
    assert lit is None and lit_asleep is None and none is None        # a light of its own lights it instead


def test_the_viewer_lights_the_deep_from_the_layers():
    src = (WEB / "viewer.js").read_text()
    assert "SwarmLayers.lightsFor(" in src and "DEEP_DARK = 0.92" in src
    assert "SwarmLayers.placeText(" in src                     # hover, Places and the voice count rows from the deep's top
    assert "sky: R.sky" in src                                 # effects.js is told when the region has no sky
    assert "SwarmLayers.skylitTiles(" in src                    # ...and which of its tiles lie open to the sky
    assert "SwarmLayers.darkHole(" in src                       # unlit creatures below, awake or asleep, stay visible
