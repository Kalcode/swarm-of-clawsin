"""The public build of web/: the files a watcher's browser may load from /public/app/, the pages rewritten to public
mode, and a content version for the scripts' and styles' URLs.

Served: the top-level pages, styles and scripts (not demo.js), the Kenney sheet and the fonts under assets/, and the
user's own licensed art and sounds, credited in the viewer: under assets/limezu/ exactly manifest.json and the *.png
sheets, under assets/sfx/ exactly manifest.json and the *.ogg clips. Nothing else in those folders (the catalog, the
build script, any other extension), and never the original packs (inbox/, docs/media/), whatever is on this disk. The
set is found by walking those folders, and a request only ever names a key of it: a request path never becomes a file
path. Links are never followed: one could bring in a file from elsewhere, and on a disk that ignores case a link to
assets/LIMEZU/... lands in the art folder under a name that doesn't look like it. A hard link to a file that is not
served (the same device and inode), or one reachable from both art folders, is left out too."""

from __future__ import annotations

import gzip
import hashlib
import html
import os
import re
import time
from pathlib import Path, PurePosixPath

from aiohttp import web

APP_SHORT = "public, max-age=60"
APP_MISSING = "public, max-age=300"
APP_ASSET = "public, max-age=86400"  # images and fonts: a day (ruling P4)

COMPRESSIBLE = ("text/", "application/json")  # png, ogg and woff2 are compressed already
TOP_LEVEL = (".html", ".css", ".js")
NOT_SERVED = ("demo.js",)
ASSET_FOLDERS = ("assets/kenney-1bit", "assets/fonts")
ART_FOLDERS = {"assets/limezu": ".png", "assets/sfx": ".ogg"}  # folder -> the one extension served besides manifest.json
KEPT_BACK = ("inbox", "docs/media")  # the original packs, beside web/: never served, nor any link to a file in them
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css", ".js": "text/javascript",
                 ".png": "image/png", ".woff2": "font/woff2", ".txt": "text/plain", ".json": "application/json",
                 ".ogg": "audio/ogg"}

_HTML_TAG = re.compile(r"<html(?=[\s>])")
# relative references only: no scheme (http:, data:, ...), not absolute or protocol-relative, no query or fragment yet
_SCRIPT = re.compile(r'(?<![\w-])src="(?![/\\])([^":?#]+\.js)"')
_STYLE = re.compile(r'(?<![\w-])href="(?![/\\])([^":?#]+\.css)"')
_LINK = re.compile(r"https?://[^/\s]", re.IGNORECASE)


def _content_type(rel: str) -> str:
    return CONTENT_TYPES.get(PurePosixPath(rel).suffix, "application/octet-stream")


class PublicApp:
    def __init__(self, web_dir: Path, link: str | None = None, check_every: float = 10.0, clock=time.monotonic):
        self._root = Path(web_dir).resolve()
        self._link = link if link and _LINK.match(link) else None
        self._every = check_every
        self._clock = clock
        self._checked = 0.0
        self._sig: tuple | None = None  # None until the first look at the disk (on first use, not at start)
        self._snap: tuple[dict[str, tuple[bytes, str, bytes | None]], str] = ({}, "")  # files (body, type, gzip) and version, swapped as one

    # ------------------------------------------------------------------ what is served
    def _servable(self, path: Path) -> bool:
        """A real file (not a link, not hidden) inside web/."""
        if path.name.startswith(".") or path.is_symlink() or not path.is_file():
            return False
        return path.resolve().is_relative_to(self._root)

    @staticmethod
    def _art_name(rel: str) -> bool:
        """Whether rel (under an art folder) is one of the files that folder serves: its manifest or its media."""
        folder = next((f for f in ART_FOLDERS if rel.startswith(f + "/")), None)
        return folder is not None and (rel == folder + "/manifest.json" or rel.endswith(ART_FOLDERS[folder]))

    @staticmethod
    def _ids(folder: Path, keep=lambda rel: True) -> set[tuple[int, int]]:
        ids = set()
        for dirpath, _, filenames in os.walk(folder):
            for name in filenames:
                full = os.path.join(dirpath, name)
                try:
                    st = os.stat(full)
                except OSError:
                    continue
                if keep(full):
                    ids.add((st.st_dev, st.st_ino))
        return ids

    def _kept_back(self) -> set[tuple[int, int]]:
        """(device, inode) of every file that stays private: the packs, and whatever in the art folders is not served.
        A hard link to one, wherever it is, is that file."""
        ids = set()
        for part in KEPT_BACK:
            ids |= self._ids(self._root.parent / part)
        for folder in ART_FOLDERS:
            base = self._root / folder
            ids |= self._ids(base, lambda full: not self._art_name(Path(full).relative_to(self._root).as_posix()))
        return ids

    def _scan(self) -> dict[str, tuple[Path, os.stat_result]]:
        if not self._root.is_dir():
            return {}
        found = {p.name: p for p in self._root.iterdir() if p.name.endswith(TOP_LEVEL) and p.name not in NOT_SERVED}
        for folder in (*ASSET_FOLDERS, *ART_FOLDERS):
            base = self._root / folder
            if base.is_symlink() or base.parent.is_symlink():  # a linked folder is never followed
                continue
            for dirpath, dirnames, filenames in os.walk(base):  # os.walk doesn't descend into linked folders
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]
                for name in filenames:
                    path = Path(dirpath) / name
                    rel = path.relative_to(self._root).as_posix()
                    if folder in ART_FOLDERS and not self._art_name(rel):
                        continue  # exact names, lower case: the catalog, the build script, any other extension stay out
                    found[rel] = path
        private = self._kept_back()
        out = {}
        for rel in sorted(found):
            path = found[rel]
            if not self._servable(path):
                continue
            try:
                st = path.stat()
            except OSError:
                continue
            out[rel] = (path, st)
        # an inode that is private, or that is served from both art folders (a sheet linked to a sound), is not served
        by_folder: dict[tuple[int, int], set[str]] = {}
        for rel, (_, st) in out.items():
            folder = next((f for f in ART_FOLDERS if rel.startswith(f + "/")), "")
            by_folder.setdefault((st.st_dev, st.st_ino), set()).add(folder)
        return {rel: v for rel, v in out.items()
                if (v[1].st_dev, v[1].st_ino) not in private and len(by_folder[(v[1].st_dev, v[1].st_ino)] - {""}) < 2}

    def _fresh(self) -> None:
        """Look at the disk at most every check_every seconds; re-read everything when a served file appears, goes or
        changes: its inode (a file moved over it), its change time (a write, even one that keeps the size and puts
        the modification time back, or a chmod), its modification time or its size."""
        now = self._clock()
        if self._sig is not None and now - self._checked < self._every:
            return
        self._checked = now
        files = self._scan()
        sig = tuple((rel, st.st_ino, st.st_ctime_ns, st.st_mtime_ns, st.st_size) for rel, (_, st) in files.items())
        if sig != self._sig:
            self._load(files, sig)

    def _load(self, files: dict[str, tuple[Path, os.stat_result]], sig: tuple) -> None:
        raw: dict[str, bytes] = {}
        for rel, (path, _) in files.items():
            try:
                raw[rel] = path.read_bytes()
            except OSError:  # gone or unreadable since the scan: left out until it changes
                continue
        digest = hashlib.sha1()
        for rel in sorted(raw):
            digest.update(rel.encode() + b"\0" + str(len(raw[rel])).encode() + b"\0")
            digest.update(raw[rel])
        version = digest.hexdigest()[:10]
        served = {}
        for rel, body in raw.items():
            body = self._rewrite(body, version) if rel.endswith(".html") else body
            kind = _content_type(rel)
            served[rel] = (body, kind, gzip.compress(body, 6, mtime=0) if kind.startswith(COMPRESSIBLE) else None)  # once, here
        self._snap = (served, version)
        self._sig = sig

    def _rewrite(self, body: bytes, version: str) -> bytes:
        """A page in public mode: <html data-public="1">, its own scripts and styles at versioned URLs, and the link
        the user chose (http or https only) as a meta tag."""
        page = body.decode("utf-8", "surrogateescape")  # bytes it can't read pass through untouched
        page = _HTML_TAG.sub('<html data-public="1"', page, count=1)
        page = _SCRIPT.sub(lambda m: f'src="{m[1]}?v={version}"', page)
        page = _STYLE.sub(lambda m: f'href="{m[1]}?v={version}"', page)
        if self._link:
            meta = f'<meta name="swarm-public-link" content="{html.escape(self._link, quote=True)}">'
            page = page.replace("</head>", meta + "</head>", 1)
        return page.encode("utf-8", "surrogateescape")

    # ------------------------------------------------------------------ interface
    def paths(self) -> list[str]:
        self._fresh()
        return sorted(self._snap[0])

    @property
    def version(self) -> str:
        self._fresh()
        return self._snap[1]

    def get(self, rel: str) -> tuple[bytes, str] | None:
        """The body and content type of a served file, by its exact relative path; anything else (another file,
        a licensed one, .., %2e%2e, an absolute path, an odd spelling) is None."""
        found = self.serve_full(rel)
        return None if found is None else (found[0], found[2])

    def serve(self, rel: str) -> tuple[bytes, str, str] | None:
        """As get, plus the version of the same look at the disk: a request is answered from one snapshot, so a body
        is never sent as immutable under a version it isn't."""
        found = self.serve_full(rel)
        return None if found is None else (found[0], found[2], found[3])

    def serve_full(self, rel: str) -> tuple[bytes, bytes | None, str, str] | None:
        """(body, gzipped body or None, content type, version) from one snapshot."""
        self._fresh()
        files, version = self._snap
        found = files.get(rel)
        return None if found is None else (found[0], found[2], found[1], version)


PUBLIC_APP = web.AppKey("public_app", PublicApp)
