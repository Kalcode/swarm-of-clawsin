"""The public app: /public/app/ serves an allowlisted copy of web/ in public mode (versioned scripts and styles, the page
for 60 s), with the user's LimeZu sheets and sound samples (manifest.json, *.png / *.ogg and nothing else in those folders),
and never the original packs (inbox/, docs/media/), whatever is on this disk."""

import gzip
import os
import shutil

import pytest

from swarmworld.server.app import WEB_DIR, create_app
from swarmworld.server.public_app import PUBLIC_APP, PublicApp

from .test_public_http import PROXIED, raw_get, raw_head

LIMEZU_BYTES = b"LIMEZU-LICENSED-ART"
SFX_BYTES = b"SFX-LICENSED-SAMPLE"
PACK_BYTES = b"ORIGINAL-PACK"
PUBLIC_ASSETS = ["assets/limezu/manifest.json", "assets/limezu/sheets/s.png", "assets/limezu/world2.png",
                 "assets/sfx/chop/a.ogg", "assets/sfx/manifest.json"]
BASE = ["assets/fonts/f.woff2", "assets/kenney-1bit/sheet.png", "index.html", "style.css", "viewer.js"]
ALL = sorted(BASE + PUBLIC_ASSETS)


class Clock:
    t = 1000.0

    def __call__(self):
        return self.t


class Ticking:
    """A clock that moves 11 s each time it's read (so every look at the disk rescans), and can run something on its
    n-th next reading: the disk changing between two lookups in one request."""

    def __init__(self):
        self.t, self.pending = 1000.0, []

    def after(self, n, action):
        self.pending.append([n, action])

    def __call__(self):
        self.t += 11
        for item in list(self.pending):
            item[0] -= 1
            if item[0] == 0:
                self.pending.remove(item)
                item[1]()
        return self.t


@pytest.fixture
def web(tmp_path):
    d = tmp_path / "web"
    files = {
        "index.html": ('<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
                       '<link rel="stylesheet" href="style.css">\n</head>\n<body>\n'
                       '<a href="almanac.html">Almanac</a> <a href="./">Home</a>\n'
                       '<script src="viewer.js"></script>\n</body>\n</html>\n'),
        "style.css": "body { color: #222; }\n",
        "viewer.js": "// the viewer, as it is today\n",
        "demo.js": "// the demo feed\n",
        "notes.md": "notes\n",
        "assets/kenney-1bit/sheet.png": b"\x89PNG kenney",
        "assets/fonts/f.woff2": b"wOF2 font",
        "assets/limezu/manifest.json": LIMEZU_BYTES + b" manifest",
        "assets/limezu/world2.png": LIMEZU_BYTES + b" world2",
        "assets/sfx/manifest.json": SFX_BYTES + b" manifest",
        "assets/limezu/sheets/s.png": LIMEZU_BYTES + b" sheet",
        "assets/limezu/CATALOG.md": LIMEZU_BYTES + b" catalog",
        "assets/limezu/build_limezu.py": LIMEZU_BYTES + b" build",
        "assets/sfx/chop/a.ogg": SFX_BYTES + b" chop",
        "assets/sfx/readme.txt": SFX_BYTES + b" readme",
    }
    for rel, body in files.items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body if isinstance(body, bytes) else body.encode())
    (tmp_path / "secret.txt").write_text("outside web/")
    for rel in ("inbox/pack.zip", "docs/media/shot.png"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_bytes(PACK_BYTES)
    return d


def test_only_the_allowlist_is_served(web):
    app = PublicApp(web)
    assert app.paths() == ALL


def test_art_and_sounds_are_served_with_their_types_and_nothing_else_in_their_folders(web):
    app = PublicApp(web)
    assert app.get("assets/limezu/manifest.json") == (LIMEZU_BYTES + b" manifest", "application/json")
    assert app.get("assets/limezu/world2.png") == (LIMEZU_BYTES + b" world2", "image/png")
    assert app.get("assets/limezu/sheets/s.png")[1] == "image/png"
    assert app.get("assets/sfx/manifest.json") == (SFX_BYTES + b" manifest", "application/json")
    assert app.get("assets/sfx/chop/a.ogg") == (SFX_BYTES + b" chop", "audio/ogg")
    assert app.serve_full("assets/sfx/chop/a.ogg")[1] is None and app.serve_full("assets/limezu/world2.png")[1] is None  # no gzip
    for rel in ("assets/limezu/CATALOG.md", "assets/limezu/build_limezu.py", "assets/sfx/readme.txt",
                "inbox/pack.zip", "docs/media/shot.png", "../inbox/pack.zip", "../docs/media/shot.png"):
        assert app.get(rel) is None, rel


def test_stray_files_of_the_wrong_kind_in_the_art_folders_are_not_served(web):
    for rel in ("assets/limezu/a.js", "assets/limezu/a.ogg", "assets/limezu/b.PNG", "assets/limezu/other.json",
                "assets/limezu/sheets/manifest.json.bak", "assets/sfx/a.png", "assets/sfx/x.OGG", "assets/sfx/z/other.json",
                "assets/limezu/.hidden.png"):
        (web / rel).parent.mkdir(parents=True, exist_ok=True)
        (web / rel).write_bytes(b"stray")
    assert PublicApp(web).paths() == ALL


def test_traversal_and_other_paths_are_404(web):
    app = PublicApp(web)
    for rel in ("demo.js", "notes.md", "../pyproject.toml", "assets/../demo.js", "%2e%2e/x", "/etc/passwd", "assets/kenney-1bit/../../demo.js"):
        assert app.get(rel) is None, rel


def test_odd_names_are_404_too(web):
    app = PublicApp(web)
    for rel in ("../secret.txt", "assets/kenney-1bit/../../../secret.txt", str(web / "index.html"), "./index.html",
                "assets//kenney-1bit/sheet.png", "assets/LIMEZU/manifest.json", "Assets/limezu/world2.png", "assets/SFX/manifest.json",
                "assets\\limezu\\manifest.json", "assets/limezu/manifest.json\x00", "index.html\x00.png", "", ".",
                "assets", "assets/", "assets/kenney-1bit", "assets/kenney-1bit/", "VIEWER.JS"):
        assert app.get(rel) is None, rel
    assert app.get("viewer.js") == (b"// the viewer, as it is today\n", "text/javascript")
    assert app.get("assets/kenney-1bit/sheet.png") == (b"\x89PNG kenney", "image/png")
    assert app.get("assets/fonts/f.woff2")[1] == "font/woff2" and app.get("style.css")[1] == "text/css"
    assert app.get("index.html")[1] == "text/html; charset=utf-8"


def test_html_is_rewritten_to_public_mode(web):
    app = PublicApp(web, link="https://example.com/a?b=1&c=2")
    html = app.get("index.html")[0].decode()
    assert '<html data-public="1" lang="en">' in html
    assert f'href="style.css?v={app.version}"' in html and f'src="viewer.js?v={app.version}"' in html
    assert 'href="almanac.html"' in html and 'href="./"' in html
    assert '<meta name="swarm-public-link" content="https://example.com/a?b=1&amp;c=2">' in html
    assert "swarm-public-link" not in PublicApp(web, link="javascript:alert(1)").get("index.html")[0].decode()


def test_only_relative_scripts_and_styles_are_versioned(web):
    (web / "almanac.html").write_text(
        '<!DOCTYPE html>\n<html lang="en"><head><link rel="icon" href="data:,">'
        '<link rel="stylesheet" href="https://cdn.example/x.css"><link rel="stylesheet" href="//cdn.example/y.css">'
        '<link rel="stylesheet" href="/abs.css"><link rel="stylesheet" href="almanac.css?x=1">'
        '<link rel="stylesheet" href="style.css"></head><body><p>Not an <html tag</p>'
        '<script src="https://cdn.example/x.js"></script><script src="data:text/javascript,1;x.js"></script>'
        '<script src="tiles.js"></script></body></html>\n')
    app = PublicApp(web, link='https://example.com/"><script>alert(1)</script>')
    v = app.version
    html = app.get("almanac.html")[0].decode()
    assert html.count('data-public="1"') == 1 and "<p>Not an <html tag</p>" in html
    assert f'href="style.css?v={v}"' in html and f'src="tiles.js?v={v}"' in html
    for kept in ('href="data:,"', 'href="https://cdn.example/x.css"', 'href="//cdn.example/y.css"', 'href="/abs.css"',
                 'href="almanac.css?x=1"', 'src="https://cdn.example/x.js"', 'src="data:text/javascript,1;x.js"'):
        assert kept in html, kept
    assert ('<meta name="swarm-public-link" content="https://example.com/&quot;&gt;&lt;script&gt;alert(1)&lt;/script&gt;">'
            '</head>') in html
    assert "<script>alert(1)" not in html
    for link in (None, "", "ftp://example.com/", "data:text/html,hi", " javascript:alert(1)", "example.com", "/relative",
                 "https:", "http:/x"):
        assert "swarm-public-link" not in PublicApp(web, link=link).get("index.html")[0].decode(), link
    assert "swarm-public-link" in PublicApp(web, link="HTTP://Example.com/").get("index.html")[0].decode()


def test_the_version_follows_served_content_only(web):
    clock = Clock(); app = PublicApp(web, clock=clock); v1 = app.version
    (web / "demo.js").write_text("// changed"); (web / "assets/limezu/CATALOG.md").write_text("changed")
    clock.t += 11; assert app.version == v1
    (web / "assets/limezu/manifest.json").write_text("{}"); clock.t += 11; assert app.version != v1  # served art counts
    v1 = app.version
    (web / "viewer.js").write_text("// changed"); clock.t += 11
    assert app.version != v1 and app.get("viewer.js")[0] == b"// changed"


def test_the_disk_is_checked_at_most_every_check_every(web):
    clock = Clock()
    app = PublicApp(web, check_every=10.0, clock=clock)
    v1 = app.version
    (web / "viewer.js").write_text("// edited")
    (web / "assets/fonts/g.woff2").write_bytes(b"wOF2 another")
    (web / "style.css").unlink()
    clock.t += 9
    assert app.version == v1 and app.get("viewer.js")[0] == b"// the viewer, as it is today\n"
    assert app.get("assets/fonts/g.woff2") is None and app.get("style.css") is not None
    clock.t += 1
    assert app.version != v1 and app.get("viewer.js")[0] == b"// edited"
    v2 = app.version
    (web / "viewer.js").write_text("// EDITED")  # the same size: the version follows the bytes, not just the sizes
    clock.t += 10
    assert app.version != v2 and app.get("viewer.js")[0] == b"// EDITED"
    assert app.paths() == sorted(set(ALL) - {"style.css"} | {"assets/fonts/g.woff2"})
    html = app.get("index.html")[0].decode()
    assert f'src="viewer.js?v={app.version}"' in html  # the page names the new version


def test_a_same_size_same_time_replacement_or_a_chmod_is_seen(web):
    clock = Clock()
    app = PublicApp(web, clock=clock)
    v1 = app.version
    viewer = web / "viewer.js"
    old = viewer.stat()
    viewer.write_text("// the viewer, AS it is today\n")  # same size; then the old modification time put back
    os.utime(viewer, ns=(old.st_atime_ns, old.st_mtime_ns))
    clock.t += 10
    assert app.get("viewer.js")[0] == b"// the viewer, AS it is today\n" and app.version != v1
    v2 = app.version
    other = web / "other.tmp"  # a new file (another inode) of the same size and time, moved over it
    other.write_text("// THE viewer, AS it is today\n")
    os.utime(other, ns=(old.st_atime_ns, old.st_mtime_ns))
    os.replace(other, viewer)
    clock.t += 10
    assert app.get("viewer.js")[0] == b"// THE viewer, AS it is today\n" and app.version != v2
    viewer.chmod(0o000)  # unreadable: left out at the next look, back when it can be read again
    try:
        clock.t += 10
        assert app.get("viewer.js") is None and "viewer.js" not in app.paths()
    finally:
        viewer.chmod(0o644)
    clock.t += 10
    assert app.get("viewer.js")[0] == b"// THE viewer, AS it is today\n"


def test_art_added_later_appears_stray_files_do_not_and_a_file_swapped_for_a_link_goes(web):
    clock = Clock()
    app = PublicApp(web, clock=clock)
    v1, before = app.version, app.paths()
    (web / "assets/limezu/late.js").write_bytes(LIMEZU_BYTES + b" late")
    (web / "assets/sfx/late.txt").write_bytes(SFX_BYTES + b" late")
    clock.t += 10
    assert app.paths() == before and app.version == v1
    (web / "assets/limezu/late.png").write_bytes(LIMEZU_BYTES + b" late")
    (web / "assets/sfx/late.ogg").write_bytes(SFX_BYTES + b" late")
    clock.t += 10
    assert app.get("assets/limezu/late.png") is not None and app.get("assets/sfx/late.ogg") is not None
    assert app.version != v1
    v1 = app.version
    sheet = web / "assets/kenney-1bit/sheet.png"
    sheet.unlink()
    os.symlink("../limezu/world2.png", sheet)
    assert app.get("assets/kenney-1bit/sheet.png") == (b"\x89PNG kenney", "image/png")  # not looked at again yet
    clock.t += 10
    assert app.get("assets/kenney-1bit/sheet.png") is None and "assets/kenney-1bit/sheet.png" not in app.paths()
    assert app.version != v1


def test_a_hard_link_to_a_private_file_is_never_served(web, tmp_path):
    """Whatever is linked to something that stays private: the catalog, the build script, a pack file, a screenshot."""
    os.link(web / "assets/limezu/CATALOG.md", web / "assets/kenney-1bit/copy.png")
    os.link(web / "assets/limezu/build_limezu.py", web / "leak.js")
    os.link(web / "assets/sfx/readme.txt", web / "assets/fonts/a.woff2")
    os.link(tmp_path / "inbox/pack.zip", web / "assets/limezu/pack.png")
    os.link(tmp_path / "inbox/pack.zip", web / "assets/sfx/pack.ogg")
    os.link(tmp_path / "docs/media/shot.png", web / "assets/limezu/shot.png")
    os.link(tmp_path / "docs/media/shot.png", web / "assets/kenney-1bit/shot.png")
    app = PublicApp(web)
    assert app.paths() == ALL
    for rel in ("assets/kenney-1bit/copy.png", "leak.js", "assets/fonts/a.woff2", "assets/limezu/pack.png",
                "assets/sfx/pack.ogg", "assets/limezu/shot.png", "assets/kenney-1bit/shot.png"):
        assert app.get(rel) is None, rel


def test_a_sheet_and_a_sound_sharing_a_file_are_neither_served_from_the_wrong_folder(web):
    os.link(web / "assets/sfx/chop/a.ogg", web / "assets/limezu/sound.png")
    os.link(web / "assets/limezu/world2.png", web / "assets/sfx/sheet.ogg")
    app = PublicApp(web)
    assert app.get("assets/limezu/sound.png") is None and app.get("assets/sfx/sheet.ogg") is None


def test_links_never_reach_licensed_or_outside_files(web, tmp_path):
    """Only real files inside the allowlisted folders are served: a symbolic link (on a disk that ignores case, a link
    can name assets/LIMEZU/ and still land in the licensed folder) is never followed."""
    links = {
        "assets/kenney-1bit/art.png": "../limezu/world2.png",
        "assets/kenney-1bit/ART2.png": "../LIMEZU/world2.png",
        "assets/fonts/sfx": "../sfx",
        "assets/limezu/link.png": "../kenney-1bit/sheet.png",
        "assets/sfx/link.ogg": "../../../secret.txt",
        "assets/limezu/linked": "../sfx",
        "assets/fonts/out.txt": str(tmp_path / "secret.txt"),
        "leak.js": "assets/limezu/manifest.json",
        "outside.css": str(tmp_path / "secret.txt"),
    }
    for rel, target in links.items():
        os.symlink(target, web / rel)
    (web / "assets/kenney-1bit/.DS_Store").write_bytes(b"finder")
    app = PublicApp(web)
    assert app.paths() == ALL
    for rel in (*links, "assets/fonts/sfx/manifest.json", "assets/fonts/sfx/chop/a.ogg", "assets/kenney-1bit/.DS_Store"):
        assert app.get(rel) is None, rel


def test_a_linked_folder_is_never_followed(tmp_path, web):
    (web / "assets/kenney-1bit/sheet.png").unlink()
    (web / "assets/kenney-1bit").rmdir()
    os.symlink("limezu", web / "assets/kenney-1bit")
    app = PublicApp(web)
    assert not any("kenney" in p for p in app.paths())
    assert app.get("assets/kenney-1bit/world2.png") is None and app.get("assets/kenney-1bit/manifest.json") is None


def test_a_linked_art_folder_is_never_followed(web, tmp_path):
    shutil.rmtree(web / "assets/sfx")
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / "elsewhere/manifest.json").write_text("{}")
    os.symlink(tmp_path / "elsewhere", web / "assets/sfx")
    assert not any(p.startswith("assets/sfx") for p in PublicApp(web).paths())


def test_the_real_web_folder_serves_exactly_these_files():
    """Pinned: every file added to the public build is a deliberate change here (Task 5 added public.js)."""
    paths = [p for p in PublicApp(WEB_DIR).paths() if not p.startswith(ART)]  # the art and sounds are on this disk or not
    assert paths == [
        "almanac.css", "almanac.html", "almanac.js", "ascii.js",
        "assets/fonts/Jersey10-Regular.woff2", "assets/fonts/OFL-Jersey10.txt",
        "assets/kenney-1bit/License.txt", "assets/kenney-1bit/colored_transparent_packed.png",
        "effects.js", "index.html", "layers.js", "limezu.js", "motion.js", "public.js", "roofs.js", "sound.js", "style.css",
        "tiles.js", "viewer.js",
    ]


ART = ("assets/limezu/", "assets/sfx/")


def test_the_real_web_folder_serves_exactly_the_manifests_pngs_and_oggs_of_the_art_folders():
    """Whatever of the art and sounds this checkout holds (the main one holds all): each manifest.json, *.png and *.ogg,
    and nothing else from those folders; never the catalog, the build script or the packs."""
    app = PublicApp(WEB_DIR)
    paths = app.paths()
    on_disk = {p.relative_to(WEB_DIR).as_posix() for folder in ("limezu", "sfx") for p in (WEB_DIR / "assets" / folder).rglob("*")
               if p.is_file() and not p.is_symlink() and not p.name.startswith(".")}
    want = {r for r in on_disk if r in ("assets/limezu/manifest.json", "assets/sfx/manifest.json")
            or r.startswith("assets/limezu/") and r.endswith(".png") or r.startswith("assets/sfx/") and r.endswith(".ogg")}
    assert {p for p in paths if p.startswith(ART)} == want
    assert not any(p.startswith(("assets/audio", "inbox", "docs")) for p in paths)
    assert {"index.html", "almanac.html", "viewer.js", "style.css", "assets/kenney-1bit/colored_transparent_packed.png",
            "assets/fonts/Jersey10-Regular.woff2"} <= set(paths)
    assert "demo.js" not in paths


async def test_routes_and_cache_headers(aiohttp_client):
    c = await aiohttp_client(create_app(seed=7, tick_seconds=0.02, public_every=3600))
    page = await c.get("/public/app/")
    v = c.app[PUBLIC_APP].version
    html = await page.text()
    assert page.headers["Cache-Control"] == "public, max-age=60" and f'src="public.js?v={v}"' in html
    assert html.index(f'src="public.js?v={v}"') < html.index(f'src="viewer.js?v={v}"')
    js = await c.get(f"/public/app/viewer.js?v={v}")
    assert js.headers["Cache-Control"] == "public, max-age=31536000, immutable" and js.headers["Content-Type"].startswith("text/javascript")
    assert (await c.get("/public/app/viewer.js", allow_redirects=False)).headers["Cache-Control"] == "public, max-age=60"
    lz = await c.get("/public/app/assets/limezu/manifest.json")        # present on this disk or not
    if "assets/limezu/manifest.json" in c.app[PUBLIC_APP].paths():
        assert lz.status == 200 and lz.headers["Content-Type"] == "application/json"
        assert lz.headers["Cache-Control"] == "public, max-age=60"  # no ?v=: not pinned
        lzv = await c.get(f"/public/app/assets/limezu/manifest.json?v={v}")
        assert lzv.headers["Cache-Control"] == "public, max-age=31536000, immutable"
    else:
        assert lz.status == 404 and lz.headers["Cache-Control"] == "public, max-age=300"
    assert (await c.get("/public/app/assets/kenney-1bit/colored_transparent_packed.png")).status == 200


async def test_the_page_scripts_images_and_fonts_cache_as_ruled(aiohttp_client):
    """The page 60 s (even with a v: it names the versions and the link); versioned scripts and styles for good;
    images and fonts a day; anything not served a 5-minute 404."""
    c = await aiohttp_client(create_app(seed=7, tick_seconds=0.02, public_every=3600, public_link="https://example.com/"))
    v = c.app[PUBLIC_APP].version
    for url in ("/public/app/", "/public/app/index.html", f"/public/app/index.html?v={v}", "/public/app/almanac.html"):
        r = await c.get(url)
        assert r.status == 200 and r.headers["Cache-Control"] == "public, max-age=60", url
        assert r.headers["Content-Type"] == "text/html; charset=utf-8" and r.headers["X-Content-Type-Options"] == "nosniff"
        body = await r.text()
        assert '<html data-public="1"' in body and '<meta name="swarm-public-link" content="https://example.com/">' in body
    css = await c.get(f"/public/app/style.css?v={v}")
    assert css.headers["Cache-Control"] == "public, max-age=31536000, immutable" and css.headers["Content-Type"] == "text/css"
    assert (await c.get("/public/app/style.css")).headers["Cache-Control"] == "public, max-age=60"
    for url, kind, cache in (("/public/app/assets/kenney-1bit/colored_transparent_packed.png", "image/png", "public, max-age=86400"),
                             ("/public/app/assets/fonts/Jersey10-Regular.woff2", "font/woff2", "public, max-age=86400"),
                             (f"/public/app/assets/fonts/Jersey10-Regular.woff2?v={v}", "font/woff2",
                              "public, max-age=31536000, immutable")):
        r = await c.get(url)
        assert r.status == 200 and r.headers["Content-Type"] == kind and r.headers["Cache-Control"] == cache, url
    assert await (await c.get("/public/app/assets/kenney-1bit/colored_transparent_packed.png")).read() == \
        (WEB_DIR / "assets/kenney-1bit/colored_transparent_packed.png").read_bytes()
    for url in ("/public/app/demo.js", "/public/app/nope.js", "/public/app/assets/", "/public/app/assets/audio/CREDITS.md"):
        r = await c.get(url)
        assert r.status == 404 and r.headers["Cache-Control"] == "public, max-age=300", url
    head = await c.head(f"/public/app/viewer.js?v={v}")
    assert head.status == 200 and await head.read() == b""
    bare = await c.get("/public/app", allow_redirects=False)
    assert bare.status == 301 and bare.headers["Location"] == "/public/app/"
    assert (await c.post("/public/app/index.html")).status == 405


async def test_a_body_is_never_marked_immutable_under_another_version(aiohttp_client, web, tmp_path):
    """The body and the version a request is answered with come from one look at the disk: were the disk to change
    between looking up the body and the version, the old body would be pinned for good under the new version's URL."""
    edited = tmp_path / "edited"
    shutil.copytree(web, edited)
    (edited / "viewer.js").write_text("// the viewer, edited\n")
    v2 = PublicApp(edited).version  # the version the edit will have (the hash doesn't depend on the folder)
    clock = Ticking()
    app = create_app(seed=7, tick_seconds=0.02, public_every=3600)
    app[PUBLIC_APP] = PublicApp(web, clock=clock)
    c = await aiohttp_client(app)
    v1 = app[PUBLIC_APP].version
    assert v1 != v2
    clock.after(2, lambda: (web / "viewer.js").write_text("// the viewer, edited\n"))  # the request's second look
    r = await c.get(f"/public/app/viewer.js?v={v2}")
    body = await r.read()
    assert r.status == 200
    if r.headers["Cache-Control"] == "public, max-age=31536000, immutable":
        assert body == b"// the viewer, edited\n"
    else:
        assert body == b"// the viewer, as it is today\n" and r.headers["Cache-Control"] == "public, max-age=60"
    found = app[PUBLIC_APP].serve("viewer.js")
    assert found == (b"// the viewer, edited\n", "text/javascript", v2)
    assert app[PUBLIC_APP].serve("demo.js") is None and app[PUBLIC_APP].serve("assets/limezu/CATALOG.md") is None


async def test_art_and_sounds_are_served_and_the_rest_is_404_locally_and_proxied(aiohttp_client, web):
    """The served art and sounds answer 200 with their own bytes, and the catalog, the build script, stray files, the
    packs and every odd spelling of a path (encoded or dot segments) a 404, from this machine and through every kind
    of proxy."""
    app = create_app(seed=7, tick_seconds=0.02, public_every=3600)
    app[PUBLIC_APP] = PublicApp(web)
    c = await aiohttp_client(app)
    v = app[PUBLIC_APP].version
    served = {
        "assets/limezu/manifest.json": (b"application/json", LIMEZU_BYTES + b" manifest"),
        "assets/limezu/world2.png": (b"image/png", LIMEZU_BYTES + b" world2"),
        "assets/limezu/sheets/s.png": (b"image/png", LIMEZU_BYTES + b" sheet"),
        "assets/sfx/manifest.json": (b"application/json", SFX_BYTES + b" manifest"),
        "assets/sfx/chop/a.ogg": (b"audio/ogg", SFX_BYTES + b" chop"),
    }
    targets = (
        "/public/app/assets/limezu/CATALOG.md", "/public/app/assets/limezu/build_limezu.py", "/public/app/assets/sfx/readme.txt",
        "/public/app/inbox/pack.zip", "/public/app/docs/media/shot.png", "/public/app/../../inbox/pack.zip",
        "/public/app/%2e%2e/%2e%2e/inbox/pack.zip", "/public/app/assets/%2e%2e/%2e%2e/docs/media/shot.png",
        "/public/app/assets/LIMEZU/manifest.json",
        "/public/app/assets/Sfx/manifest.json", "/public/app/assets%5Climezu%5Cmanifest.json",
        "/public/app/assets/limezu/manifest.json%00", "/public/app/assets/limezu/world2.png%00.png",
        "/public/app/assets/kenney-1bit/../limezu/CATALOG.md", "/public/app/assets/kenney-1bit/%2e%2e/limezu/CATALOG.md",
        "/public/app/assets/kenney-1bit/..%2Flimezu%2Fworld2.png", "/public/app/assets/fonts/%2E%2E%2Fsfx%2Fchop%2Fa.ogg",
        "/public/app/assets/kenney-1bit/..%2F..%2Fassets%2Fsfx%2Fmanifest.json",
        "/public/app/assets//limezu/manifest.json", "/public/app/assets//sfx/manifest.json",
        "/public/app/%2e%2e/web/assets/limezu/manifest.json",
        "/public/app/%2e%2e%2f%2e%2e%2fweb%2fassets%2fsfx%2fmanifest.json",
        "/public%2Fapp%2Fassets%2Flimezu%2Fmanifest.json", "/public/app%2Fassets%2Fsfx%2Fmanifest.json",
    )
    for headers in (b"", *(f"{name}: {value}\r\n".encode() for name, value in PROXIED.items())):
        for target in targets:
            status, body = await raw_get(c, target, headers)
            assert status == 404, (target, headers)
            assert PACK_BYTES not in body and b"catalog" not in body and b"build" not in body, (target, headers)
        for rel, (kind, body) in served.items():
            status, got = await raw_get(c, f"/public/app/{rel}", headers)
            assert status == 200 and got == body, (rel, headers)
            status, got = await raw_get(c, f"/public/app/{rel}?v={v}", headers)
            assert status == 200 and got == body, (rel, headers)
    r = await c.get("/public/app/assets/sfx/chop/a.ogg", headers={"Accept-Encoding": "gzip"})
    assert r.headers["Content-Type"] == "audio/ogg" and "Content-Encoding" not in r.headers
    assert r.headers["Cache-Control"] == "public, max-age=86400"
    r = await c.get(f"/public/app/assets/sfx/chop/a.ogg?v={v}")
    assert r.headers["Cache-Control"] == "public, max-age=31536000, immutable"
    status, body = await raw_get(c, "/public/app/assets/kenney-1bit/sheet.png", b"CF-Connecting-IP: 203.0.113.9\r\n")
    assert status == 200 and body == b"\x89PNG kenney"


async def test_every_art_and_sound_file_on_this_disk_is_served_and_nothing_else_there(aiohttp_client):
    """Whatever of the LimeZu art and the samples this checkout holds (the main one holds both): the manifests, pngs and
    oggs get 200 with the right type; the catalog, the build script and the packs get 404."""
    c = await aiohttp_client(create_app(seed=7, tick_seconds=0.02, public_every=3600))
    kinds = {".png": "image/png", ".ogg": "audio/ogg", ".json": "application/json"}
    for folder in ("limezu", "sfx"):
        for p in sorted((WEB_DIR / "assets" / folder).rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(WEB_DIR).as_posix()
            r = await c.get(f"/public/app/{rel}")
            if p.name == "manifest.json" and p.parent.name == folder or p.suffix == (".png" if folder == "limezu" else ".ogg"):
                assert r.status == 200 and r.headers["Content-Type"] == kinds[p.suffix], rel
            else:
                assert r.status == 404, rel
    for rel in ("assets/limezu/CATALOG.md", "assets/limezu/build_limezu.py", "inbox/x.zip", "docs/media/x.png"):
        assert (await c.get(f"/public/app/{rel}")).status == 404, rel


async def test_other_versions_and_unknown_queries_are_redirected(aiohttp_client):
    c = await aiohttp_client(create_app(seed=7, tick_seconds=0.02, public_every=3600))
    v = c.app[PUBLIC_APP].version
    short = "public, max-age=60"
    font = "assets/fonts/Jersey10-Regular.woff2"
    enc = f"%76={v}"
    for name in ("viewer.js", "style.css", font):
        for q in ("v=bogus", "x=1", f"v={v}&x=1", "v=bogus&x=1", f"v={v}&", f"&v={v}", enc, f"v={v[:3]}%{ord(v[3]):02X}{v[4:]}",
                  f"v={v}&v={v}", "&", "v="):
            status, h, body = await raw_head(c, f"/public/app/{name}?{q}")
            assert status == 302 and h["location"] == f"/public/app/{name}?v={v}" and body == b"", (name, q)
            assert h["cache-control"] == short
        for q in ("", f"?v={v}"):
            assert (await c.get(f"/public/app/{name}{q}", allow_redirects=False)).status == 200, (name, q)
    # the pages take any query (?skin= among them), serve the page with its 60 s cache, and never redirect
    for page in ("", "index.html", "almanac.html"):
        for q in ("", "?skin=ascii", "?v=bogus", f"?v={v}", "?x=1&", "?%76=1"):
            r = await c.get(f"/public/app/{page}{q}", allow_redirects=False)
            assert r.status == 200 and r.headers["Cache-Control"] == short, (page, q)
    status, h, _ = await raw_head(c, "/%70ublic/app/viewer.js?v=bogus")
    assert status == 404 or (status == 302 and h["location"] == f"/public/app/viewer.js?v={v}")
    assert (await c.get("/public/app/nope.js?v=bogus", allow_redirects=False)).status == 404  # nothing to redirect to
    r = await c.get("/public/app/viewer.js?v=bogus", headers={"CF-Connecting-IP": "203.0.113.9"}, allow_redirects=False)
    assert r.status == 302


async def test_app_files_are_gzipped_once_and_served_gzipped(aiohttp_client):
    app = create_app(seed=7, tick_seconds=0.02, public_every=3600)
    c = await aiohttp_client(app)
    v = app[PUBLIC_APP].version
    plain = (WEB_DIR / "viewer.js").read_bytes()
    r = await c.get(f"/public/app/viewer.js?v={v}", headers={"Accept-Encoding": "gzip"}, auto_decompress=False)
    assert r.headers["Content-Encoding"] == "gzip" and "Accept-Encoding" in r.headers["Vary"]
    raw = await r.read()
    assert gzip.decompress(raw) == plain and len(raw) < len(plain) / 2
    assert r.headers["Content-Type"].startswith("text/javascript")
    r = await c.get(f"/public/app/viewer.js?v={v}", headers={"Accept-Encoding": "identity"}, auto_decompress=False)
    assert "Content-Encoding" not in r.headers and await r.read() == plain
    page = await c.get("/public/app/", headers={"Accept-Encoding": "gzip"}, auto_decompress=False)
    assert page.headers["Content-Encoding"] == "gzip" and b'data-public="1"' in gzip.decompress(await page.read())
    png = await c.get("/public/app/assets/kenney-1bit/colored_transparent_packed.png", headers={"Accept-Encoding": "gzip"},
                      auto_decompress=False)
    assert "Content-Encoding" not in png.headers  # already compressed formats stay as they are
    # the same bytes object each time: gzipped at load, not per request
    assert app[PUBLIC_APP].serve_full("viewer.js")[1] is app[PUBLIC_APP].serve_full("viewer.js")[1]


async def test_the_about_link_reaches_the_page_without_an_app_key(aiohttp_client):
    import swarmworld.server.public as public
    assert not hasattr(public, "PUBLIC_LINK")
    c = await aiohttp_client(create_app(seed=7, tick_seconds=0.02, public_every=3600, public_link="https://example.com/x"))
    assert 'content="https://example.com/x"' in await (await c.get("/public/app/")).text()
