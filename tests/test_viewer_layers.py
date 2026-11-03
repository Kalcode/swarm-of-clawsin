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
