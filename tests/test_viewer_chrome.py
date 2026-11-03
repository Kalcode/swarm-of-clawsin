"""The viewer's chrome in the LimeZu skin (stream UI): it is dressed in pieces of LimeZu's Modern User Interface
pack, which is licensed and gitignored, so every rule that uses them must be gated on the class limezu.js sets when
the pieces loaded, and the viewer must come up with today's chrome when they are missing."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parent.parent / "web"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed")
MANIFEST = WEB / "assets/limezu/manifest.json"
GATE = 'html.lz-ui[data-skin="limezu"]'


def css_rules(text):
    """(selector, body) for every style rule in the sheet, at any depth of @media/@supports nesting."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    rules, stack, start = [], [], 0
    for i, ch in enumerate(text):
        if ch == "{":
            stack.append((text[start:i].strip(), i + 1))
            start = i + 1
        elif ch == "}":
            head, body_start = stack.pop()
            body = text[body_start:i]
            if not head.startswith("@") and "{" not in body:
                rules.append((head, body))
            start = i + 1
        elif ch == ";" and not stack:
            start = i + 1
    return rules


def selectors(head):
    return [s.strip() for s in head.split(",") if s.strip()]


def test_every_rule_that_uses_the_pack_is_gated_on_the_limezu_ui_class():
    sheet = (WEB / "style.css").read_text()
    rules = css_rules(sheet)
    assert len(rules) > 300                       # the parser saw the whole sheet
    lz_rules = [(h, b) for h, b in rules if "--lz-" in b]
    assert len(lz_rules) > 40                     # the chrome really is dressed in the pack
    for head, body in lz_rules:
        for sel in selectors(head):
            assert sel.startswith(GATE), f"{sel!r} uses the pack's pieces outside {GATE}"
    # nothing reaches into the licensed folder directly; the pieces arrive only as the variables limezu.js publishes
    assert "assets/limezu" not in re.sub(r"/\*.*?\*/", "", sheet, flags=re.S)
    assert "assets/limezu" not in (WEB / "index.html").read_text()


def test_the_pixel_face_is_committed_and_only_the_limezu_chrome_uses_it():
    sheet = (WEB / "style.css").read_text()
    faces = re.findall(r"@font-face\s*{([^}]*)}", sheet)
    srcs = [m for f in faces for m in re.findall(r"url\(([^)]+)\)", f)]
    assert srcs, "the pixel face is declared"
    for src in srcs:
        assert (WEB / src.strip("'\"")).is_file(), src
    assert (WEB / "assets/fonts/OFL-Jersey10.txt").is_file()   # its licence travels with it
    for head, body in css_rules(sheet):
        if "--px" in body and "--px:" not in body.replace(" ", ""):
            for sel in selectors(head):
                assert sel.startswith(GATE), f"{sel!r} uses the pixel face outside {GATE}"


@pytest.mark.skipif(not MANIFEST.exists(), reason="the LimeZu art is not installed")
def test_every_piece_the_chrome_names_is_one_the_manifest_publishes():
    ui = json.loads(MANIFEST.read_text()).get("ui") or {}
    kebab = lambda n: "--lz-" + re.sub(r"[A-Z]", lambda m: "-" + m.group(0).lower(), n)
    published = {kebab(n) for n, p in ui.items() if isinstance(p, dict) and "rect" in p}
    sheet = (WEB / "style.css").read_text()
    defined = set(re.findall(r"(--lz-[a-z0-9-]+)\s*:", sheet))
    assert not (defined & published), "a palette variable shadows a piece"
    used = set(re.findall(r"var\((--lz-[a-z0-9-]+)", sheet))
    assert used - defined <= published, sorted(used - defined - published)
    # and limezu.js sets the class only once every piece the chrome names has loaded
    needs = re.search(r"const UI_NEEDS = \[([^\]]*)\]", (WEB / "limezu.js").read_text()).group(1)
    needed = {kebab(n) for n in re.findall(r"'(\w+)'", needs)}
    assert used - defined == needed, (sorted(used - defined - needed), sorted(needed - (used - defined)))


# A browser just good enough for limezu.js to load its manifest and publish the UI pieces.
CHROME_HARNESS = r"""
const fs = require('fs');
const path = require('path');
const [WEB, mode] = process.argv.slice(2);
const mkCanvas = () => ({ width: 0, height: 0, style: {}, toDataURL: () => 'data:,', getContext: () => new Proxy({}, { get: () => () => ({}) }) });
const classes = new Set(), props = {};
const root = { classList: { toggle: (c, on) => (on ? classes.add(c) : classes.delete(c)), add: (c) => classes.add(c), contains: (c) => classes.has(c) },
               style: { setProperty: (k, v) => { props[k] = v; } } };
global.document = { createElement: mkCanvas, documentElement: root };
global.window = global;
global.getComputedStyle = () => ({ getPropertyValue: () => '' });
console.info = () => {};
const load = (f) => (0, eval)(fs.readFileSync(path.join(WEB, f), 'utf8'));
let manifest = JSON.parse(fs.readFileSync(path.join(WEB, 'assets/limezu/manifest.json'), 'utf8'));
if (mode === 'no-ui') delete manifest.ui;
if (mode === 'old-ui') manifest.ui = Object.fromEntries(Object.entries(manifest.ui).filter(([k]) => /^(note|sheet|panel|button|buttonDown|slot|bar)/.test(k)));
global.fetch = async () => ({ ok: true, json: async () => manifest });
global.Image = class { set src(v) { this.naturalWidth = this.width = 256; this.naturalHeight = this.height = 256;
  setTimeout(() => (mode === 'no-sheet' && /ui\.png$/.test(v) ? this.onerror && this.onerror() : this.onload && this.onload()), 0); } };
load('tiles.js');
load('limezu.js');
(async () => {
  const L = window.SwarmLimeZu;
  const loaded = await L.load();
  L.applyUI(root, true);
  const on = classes.has('lz-ui');
  L.applyUI(root, false);
  process.stdout.write(JSON.stringify({ loaded, on, off: !classes.has('lz-ui'), props: Object.keys(props) }));
})();
"""


def run_chrome_harness(tmp_path, mode):
    harness = tmp_path / "chrome.js"
    harness.write_text(CHROME_HARNESS)
    r = subprocess.run([NODE, str(harness), str(WEB), mode], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@needs_node
@pytest.mark.skipif(not MANIFEST.exists(), reason="the LimeZu art is not installed")
def test_the_chrome_skin_turns_on_only_when_every_piece_it_needs_loaded(tmp_path):
    full = run_chrome_harness(tmp_path, "full")
    assert full["loaded"] and full["on"] and full["off"]       # the pieces publish, and another skin takes them back
    assert {"--lz-board", "--lz-tab-on", "--lz-ib-sound", "--lz-sky-frame"} <= set(full["props"])
    # without the pieces (no "ui" in the manifest, an older build that predates the chrome, or ui.png missing) the
    # class is never set, so index.html comes up with today's chrome in the LimeZu skin
    assert not run_chrome_harness(tmp_path, "no-ui")["on"]
    assert not run_chrome_harness(tmp_path, "old-ui")["on"]
    no_sheet = run_chrome_harness(tmp_path, "no-sheet")
    assert not no_sheet["on"]
