"""The public build of web/: the files a watcher's browser may load from /public/app/, the pages rewritten to public
mode, and a content version for the scripts' and styles' URLs.

Served: the top-level pages, styles and scripts (not demo.js), and the Kenney sheet and the fonts under assets/. Never
the licensed LimeZu art (assets/limezu/) or the sound samples (assets/sfx/), whatever is on this disk. The set is found
by walking those folders, and a request only ever names a key of it: a request path never becomes a file path. Links
are never followed: one could bring in a file from elsewhere, and on a disk that ignores case a link to
assets/LIMEZU/... lands in the licensed folder under a name that doesn't look like it."""

from __future__ import annotations

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

TOP_LEVEL = (".html", ".css", ".js")
NOT_SERVED = ("demo.js",)
ASSET_FOLDERS = ("assets/kenney-1bit", "assets/fonts")
LICENSED = ("assets/limezu", "assets/sfx")
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css", ".js": "text/javascript",
                 ".png": "image/png", ".woff2": "font/woff2", ".txt": "text/plain"}

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
        self._licensed = tuple(self._root / part for part in LICENSED)
        self._link = link if link and _LINK.match(link) else None
        self._every = check_every
        self._clock = clock
        self._checked = 0.0
        self._sig: tuple | None = None  # None until the first look at the disk (on first use, not at start)
        self._files: dict[str, tuple[bytes, str]] = {}
        self._version = ""

    # ------------------------------------------------------------------ what is served
    def _servable(self, path: Path) -> bool:
        """A real file (not a link, not hidden) inside web/ and outside the licensed folders."""
        if path.name.startswith(".") or path.is_symlink() or not path.is_file():
            return False
        resolved = path.resolve()
        return resolved.is_relative_to(self._root) and not any(resolved.is_relative_to(d) for d in self._licensed)

    def _scan(self) -> dict[str, Path]:
        if not self._root.is_dir():
            return {}
        found = {p.name: p for p in self._root.iterdir() if p.name.endswith(TOP_LEVEL) and p.name not in NOT_SERVED}
        for folder in ASSET_FOLDERS:
            base = self._root / folder
            if base.is_symlink() or base.parent.is_symlink():  # a linked folder is never followed
                continue
            for dirpath, dirnames, filenames in os.walk(base):  # os.walk doesn't descend into linked folders
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]
                for name in filenames:
                    path = Path(dirpath) / name
                    found[path.relative_to(self._root).as_posix()] = path
        return {rel: path for rel, path in found.items()
                if self._servable(path) and not any(PurePosixPath(rel.casefold()).is_relative_to(d) for d in LICENSED)}

    def _fresh(self) -> None:
        """Look at the disk at most every check_every seconds; re-read everything when a served file's stat changes,
        or one appears or goes."""
        now = self._clock()
        if self._sig is not None and now - self._checked < self._every:
            return
        self._checked = now
        files = self._scan()
        sig = []
        for rel in sorted(files):
            try:
                st = files[rel].stat()
            except OSError:
                continue
            sig.append((rel, st.st_mtime_ns, st.st_size))
        sig = tuple(sig)
        if sig != self._sig:
            self._load(files, sig)

    def _load(self, files: dict[str, Path], sig: tuple) -> None:
        raw: dict[str, bytes] = {}
        for rel, *_ in sig:
            try:
                raw[rel] = files[rel].read_bytes()
            except OSError:  # gone or unreadable since the scan: left out until the next look
                continue
        digest = hashlib.sha1()
        for rel in sorted(raw):
            digest.update(rel.encode() + b"\0" + str(len(raw[rel])).encode() + b"\0")
            digest.update(raw[rel])
        version = digest.hexdigest()[:10]
        self._files = {rel: (self._rewrite(body, version) if rel.endswith(".html") else body, _content_type(rel))
                       for rel, body in raw.items()}
        self._version = version
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
        return sorted(self._files)

    @property
    def version(self) -> str:
        self._fresh()
        return self._version

    def get(self, rel: str) -> tuple[bytes, str] | None:
        """The body and content type of a served file, by its exact relative path; anything else (another file,
        a licensed one, .., %2e%2e, an absolute path, an odd spelling) is None."""
        self._fresh()
        return self._files.get(rel)


PUBLIC_APP = web.AppKey("public_app", PublicApp)
