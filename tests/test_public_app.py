"""The public app: /public/app/ serves an allowlisted copy of web/ in public mode (versioned scripts and styles, the page
for 60 s), and never the licensed LimeZu art or the sound samples, whatever is on this disk."""

import os

import pytest

from swarmworld.server.app import WEB_DIR, create_app
from swarmworld.server.public_app import PUBLIC_APP, PublicApp

from .test_public_http import PROXIED, raw_get

LIMEZU_BYTES = b"LIMEZU-LICENSED-ART"
SFX_BYTES = b"SFX-LICENSED-SAMPLE"


class Clock:
    t = 1000.0

    def __call__(self):
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
        "assets/sfx/chop/a.ogg": SFX_BYTES + b" chop",
    }
    for rel, body in files.items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body if isinstance(body, bytes) else body.encode())
    (tmp_path / "secret.txt").write_text("outside web/")
    return d


def test_only_the_allowlist_is_served(web):
    app = PublicApp(web)
    assert app.paths() == ["assets/fonts/f.woff2", "assets/kenney-1bit/sheet.png", "index.html", "style.css", "viewer.js"]


def test_traversal_and_licensed_paths_are_404(web):
    app = PublicApp(web)
    for rel in ("assets/limezu/manifest.json", "assets/limezu/world2.png", "assets/sfx/manifest.json", "assets/sfx/chop/a.ogg",
                "demo.js", "notes.md", "../pyproject.toml", "assets/../demo.js", "%2e%2e/x", "/etc/passwd", "assets/kenney-1bit/../../demo.js"):
        assert app.get(rel) is None, rel


def test_odd_names_are_404_too(web):
    app = PublicApp(web)
    for rel in ("../secret.txt", "assets/kenney-1bit/../../../secret.txt", str(web / "index.html"), "./index.html",
                "assets//kenney-1bit/sheet.png", "assets/LIMEZU/manifest.json", "Assets/limezu/world2.png",
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
    (web / "demo.js").write_text("// changed"); (web / "assets/limezu/manifest.json").write_text("{}")
    clock.t += 11; assert app.version == v1
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
    assert app.paths() == ["assets/fonts/f.woff2", "assets/fonts/g.woff2", "assets/kenney-1bit/sheet.png", "index.html",
                           "viewer.js"]
    html = app.get("index.html")[0].decode()
    assert f'src="viewer.js?v={app.version}"' in html  # the page names the new version


def test_links_never_reach_licensed_or_outside_files(web, tmp_path):
    """Only real files inside the allowlisted folders are served: a symbolic link (on a disk that ignores case, a link
    can name assets/LIMEZU/ and still land in the licensed folder) is never followed."""
    links = {
        "assets/kenney-1bit/art.png": "../limezu/world2.png",
        "assets/kenney-1bit/ART2.png": "../LIMEZU/world2.png",
        "assets/fonts/sfx": "../sfx",
        "assets/fonts/out.txt": str(tmp_path / "secret.txt"),
        "leak.js": "assets/limezu/manifest.json",
        "outside.css": str(tmp_path / "secret.txt"),
    }
    for rel, target in links.items():
        os.symlink(target, web / rel)
    (web / "assets/kenney-1bit/.DS_Store").write_bytes(b"finder")
    app = PublicApp(web)
    assert app.paths() == ["assets/fonts/f.woff2", "assets/kenney-1bit/sheet.png", "index.html", "style.css", "viewer.js"]
    for rel in (*links, "assets/fonts/sfx/manifest.json", "assets/fonts/sfx/chop/a.ogg", "assets/kenney-1bit/.DS_Store"):
        assert app.get(rel) is None, rel


def test_a_linked_folder_is_never_followed(tmp_path, web):
    (web / "assets/kenney-1bit/sheet.png").unlink()
    (web / "assets/kenney-1bit").rmdir()
    os.symlink("limezu", web / "assets/kenney-1bit")
    app = PublicApp(web)
    assert not any("kenney" in p or "limezu" in p for p in app.paths())
    assert app.get("assets/kenney-1bit/world2.png") is None and app.get("assets/kenney-1bit/manifest.json") is None


def test_the_real_web_folder_serves_no_licensed_file():
    app = PublicApp(WEB_DIR)
    paths = app.paths()
    assert {"index.html", "almanac.html", "viewer.js", "style.css", "assets/kenney-1bit/colored_transparent_packed.png",
            "assets/fonts/Jersey10-Regular.woff2"} <= set(paths)
    assert "demo.js" not in paths
    assert not any(p.startswith(("assets/limezu", "assets/sfx", "assets/audio")) for p in paths)


async def test_routes_and_cache_headers(aiohttp_client):
    c = await aiohttp_client(create_app(seed=7, tick_seconds=0.02, public_every=3600))
    page = await c.get("/public/app/")
    v = c.app[PUBLIC_APP].version
    assert page.headers["Cache-Control"] == "public, max-age=60" and f'viewer.js?v={v}' in await page.text()  # public.js?v= from Task 6
    js = await c.get(f"/public/app/viewer.js?v={v}")
    assert js.headers["Cache-Control"] == "public, max-age=31536000, immutable" and js.headers["Content-Type"].startswith("text/javascript")
    assert (await c.get("/public/app/viewer.js?v=old")).headers["Cache-Control"] == "public, max-age=60"
    lz = await c.get("/public/app/assets/limezu/manifest.json")        # present on this disk or not, never served
    assert lz.status == 404 and lz.headers["Cache-Control"] == "public, max-age=300"
    assert (await c.get("/public/app/assets/sfx/manifest.json")).status == 404
    assert (await c.get("/public/app/assets/kenney-1bit/colored_transparent_packed.png")).status == 200
    assert not any(p.startswith(("assets/limezu", "assets/sfx")) for p in c.app[PUBLIC_APP].paths())


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
                             ("/public/app/assets/fonts/Jersey10-Regular.woff2?v=old", "font/woff2", "public, max-age=86400"),
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


async def test_licensed_files_are_404_under_public_app_locally_and_proxied(aiohttp_client, web):
    """Direct, encoded and dot-segment requests for the licensed files (present on this disk, in the fixture), from this
    machine and through every kind of proxy: always a 404, never their bytes."""
    app = create_app(seed=7, tick_seconds=0.02, public_every=3600)
    app[PUBLIC_APP] = PublicApp(web)
    c = await aiohttp_client(app)
    v = app[PUBLIC_APP].version
    targets = (
        "/public/app/assets/limezu/manifest.json", "/public/app/assets/limezu/world2.png",
        "/public/app/assets/sfx/manifest.json", "/public/app/assets/sfx/chop/a.ogg",
        f"/public/app/assets/limezu/manifest.json?v={v}",
        "/public/app/assets%2Flimezu%2Fmanifest.json", "/public/app/assets/limezu%2Fworld2.png",
        "/public/app/assets%2fsfx%2fchop%2fa.ogg", "/public/app/assets/%6Cimezu/manifest.json",
        "/public/app/%61ssets/sfx/manifest.json", "/public/app/assets/LIMEZU/manifest.json",
        "/public/app/assets/Sfx/manifest.json", "/public/app/assets%5Climezu%5Cmanifest.json",
        "/public/app/assets/limezu/manifest.json%00", "/public/app/assets/limezu/world2.png%00.png",
        "/public/app/assets/kenney-1bit/../limezu/manifest.json", "/public/app/assets/kenney-1bit/%2e%2e/limezu/world2.png",
        "/public/app/assets/kenney-1bit/..%2Flimezu%2Fworld2.png", "/public/app/assets/fonts/%2E%2E%2Fsfx%2Fchop%2Fa.ogg",
        "/public/app/assets/kenney-1bit/..%2F..%2Fassets%2Fsfx%2Fmanifest.json",
        "/public/app/./assets/limezu/manifest.json", "/public/app/assets/./limezu/manifest.json",
        "/public/app//assets/limezu/manifest.json", "/public/app/assets//sfx/manifest.json",
        "/public/app/../app/assets/limezu/manifest.json", "/public/app/%2e%2e/web/assets/limezu/manifest.json",
        "/public/app/%2e%2e%2f%2e%2e%2fweb%2fassets%2fsfx%2fmanifest.json",
        "/public%2Fapp%2Fassets%2Flimezu%2Fmanifest.json", "/public/app%2Fassets%2Fsfx%2Fmanifest.json",
    )
    for headers in (b"", *(f"{name}: {value}\r\n".encode() for name, value in PROXIED.items())):
        for target in targets:
            status, body = await raw_get(c, target, headers)
            assert status == 404, (target, headers)
            assert LIMEZU_BYTES not in body and SFX_BYTES not in body, (target, headers)
    status, body = await raw_get(c, "/public/app/assets/kenney-1bit/sheet.png", b"CF-Connecting-IP: 203.0.113.9\r\n")
    assert status == 200 and body == b"\x89PNG kenney"


async def test_licensed_files_on_this_disk_are_never_served(aiohttp_client):
    """Whatever of the LimeZu art and the samples this checkout holds (the main one holds both): a 404 for each."""
    c = await aiohttp_client(create_app(seed=7, tick_seconds=0.02, public_every=3600))
    present = [p.relative_to(WEB_DIR).as_posix() for folder in ("limezu", "sfx")
               for p in sorted((WEB_DIR / "assets" / folder).rglob("*")) if p.is_file()]
    for rel in present:
        for headers in ({}, {"CF-Connecting-IP": "203.0.113.9"}):
            r = await c.get(f"/public/app/{rel}", headers=headers)
            assert r.status == 404, (rel, headers)
