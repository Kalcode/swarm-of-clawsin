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
    assert len(land["biomes"]) == w.height and all(len(r) == w.width for r in land["biomes"])
    assert len(land["flow"]) == w.height and all(len(r) == w.width for r in land["flow"])
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
