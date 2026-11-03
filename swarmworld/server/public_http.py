"""The /public/* handlers: each serves a document the Publisher already built (its bytes and its gzip, encoded once per
interval) with the spec's cache headers, an ETag (304 when the client has it) and gzip when the client takes it, or a
file of the public app that PublicApp already holds, looked up by its allowlisted name. Nothing here reads a file or
builds a document from request data; an unknown creature or path is a short-cached 404."""

from __future__ import annotations

import json
import logging
import re
import time

from urllib.parse import quote

from aiohttp import web

from .public import PUBLISHER, Doc
from .public_app import APP_ASSET, APP_MISSING, APP_SHORT, PUBLIC_APP

log = logging.getLogger("swarmworld.server")

LIVE_CACHE = "public, max-age=2, s-maxage=3, stale-while-revalidate=10"
IMMUTABLE = "public, max-age=31536000, immutable"
MINUTE = "public, max-age=60"
MISSING = "public, max-age=3"
REDIRECT_CACHE = "public, max-age=2, s-maxage=3"


def _names_etag(if_none_match: str | None, etag: str) -> bool:
    """If-None-Match uses the weak comparison (RFC 9110), so W/"x" names "x": the edge may weaken an ETag when it
    recompresses."""
    for tag in (if_none_match or "").split(","):
        tag = tag.strip().removeprefix("W/")
        if tag == "*" or tag == etag:
            return True
    return False


def _takes_gzip(accept_encoding: str | None) -> bool:
    """gzip, or *, with a q-value above 0; in doubt (an odd q) the plain body, which every client takes."""
    q = {}
    for part in (accept_encoding or "").lower().split(","):
        coding, _, params = part.partition(";")
        weight = 1.0
        for p in params.split(";"):
            name, _, value = p.strip().partition("=")
            if name == "q":
                try:
                    weight = float(value)
                except ValueError:
                    weight = 0.0
        q[coding.strip()] = weight
    return q.get("gzip", q.get("*", 0.0)) > 0


def doc_response(request: web.Request, doc: Doc, cache: str) -> web.Response:
    etag = f'"{doc.etag}"'
    headers = {"Cache-Control": cache, "ETag": etag, "Vary": "Accept-Encoding", "X-Content-Type-Options": "nosniff"}
    if _names_etag(request.headers.get("If-None-Match"), etag):
        return web.Response(status=304, headers=headers)
    body = doc.body
    if _takes_gzip(request.headers.get("Accept-Encoding")):
        headers["Content-Encoding"] = "gzip"
        body = doc.gz
    return web.Response(body=body, headers=headers, content_type="application/json", charset="utf-8")


def missing(status: int = 404) -> web.Response:
    return web.Response(status=status, text="not found" if status == 404 else "not ready yet",
                        headers={"Cache-Control": MISSING, "X-Content-Type-Options": "nosniff"})


def _serve(request: web.Request, doc: Doc | None, cache: str) -> web.Response:
    return doc_response(request, doc, cache) if doc is not None else missing(503)  # the first publish failed


async def to_app(request: web.Request) -> web.Response:
    raise web.HTTPFound("/public/app/")


def redirect(to: str, cache: str) -> web.Response:
    return web.Response(status=302, headers={"Location": to, "Cache-Control": cache, "X-Content-Type-Options": "nosniff"})


def versioned(request: web.Request, path: str, version: str) -> web.Response | None:
    """A versioned document is served for exactly the raw query v=<current> (no padding, no percent-encoding: another
    spelling is another edge key); anything else is sent, with a short cache, to the canonical URL."""
    if request.rel_url.raw_query_string == f"v={version}":
        return None
    return redirect(f"{path}?v={version}", REDIRECT_CACHE)


async def live_json(request: web.Request) -> web.Response:
    return _serve(request, request.app[PUBLISHER].live_doc(), LIVE_CACHE)


async def static_json(request: web.Request) -> web.Response:
    pub = request.app[PUBLISHER]
    return versioned(request, "/public/static.json", pub.static_version) or _serve(request, pub.static_doc(), IMMUTABLE)


_last_log = [-60.0]


def failed() -> web.Response:
    """A short-cached 503 with a small JSON body (no traceback text); the cause is logged at most once a minute."""
    now = time.monotonic()
    if now - _last_log[0] >= 60.0:
        _last_log[0] = now
        log.exception("public creature document failed to build")
    return web.Response(status=503, body=b'{"error":"not ready"}', content_type="application/json",
                        headers={"Cache-Control": REDIRECT_CACHE, "X-Content-Type-Options": "nosniff"})


async def creature_json(request: web.Request) -> web.Response:
    try:
        doc = request.app[PUBLISHER].creature_doc(request.match_info["cid"])
    except Exception:
        return failed()
    return doc_response(request, doc, LIVE_CACHE) if doc is not None else missing()


async def almanac_json(request: web.Request) -> web.Response:
    return doc_response(request, request.app[PUBLISHER].almanac_doc(), MINUTE)


async def history_json(request: web.Request) -> web.Response:
    return doc_response(request, request.app[PUBLISHER].history_doc(), MINUTE)


async def chronicle_json(request: web.Request) -> web.Response:
    pub = request.app[PUBLISHER]
    return versioned(request, "/public/chronicle.json", pub.chronicle_version) or doc_response(request, pub.chronicle_doc(), IMMUTABLE)


HERE_MAX_BYTES = 256
HERE_ID = re.compile(r"[0-9a-f]{16,32}")


async def _here_body(request: web.Request) -> bytes | None:
    """The request body, or None when it is longer than HERE_MAX_BYTES (never read past one byte more)."""
    if (request.content_length or 0) > HERE_MAX_BYTES:
        return None
    body = b""
    while len(body) <= HERE_MAX_BYTES:
        chunk = await request.content.read(HERE_MAX_BYTES + 1 - len(body))
        if not chunk:
            return body
        body += chunk
    return None


async def here(request: web.Request) -> web.Response:
    """A page's check-in: {"id": "<16-32 hex>"}. Answers 204 (never cached), 400 for anything else, 405 for any method
    but POST. Neither the id nor the address is logged."""
    if request.method != "POST":
        return web.Response(status=405, headers={"Allow": "POST", "Cache-Control": "no-store"})
    raw = await _here_body(request)
    try:
        wid = json.loads(raw)["id"] if raw is not None else None
    except (ValueError, TypeError, KeyError):  # not JSON (or not UTF-8), not an object, or no id
        wid = None
    if not isinstance(wid, str) or not HERE_ID.fullmatch(wid):
        return web.Response(status=400, headers={"Cache-Control": "no-store"})
    address = request.headers.get("CF-Connecting-IP") or request.remote or ""
    request.app[PUBLISHER].watching.note(wid, address)
    return web.Response(status=204, headers={"Cache-Control": "no-store"})


async def not_public(request: web.Request) -> web.Response:
    return missing()


async def to_app_folder(request: web.Request) -> web.Response:
    raise web.HTTPMovedPermanently("/public/app/")


def app_cache(rel: str, content_type: str, v: str | None, version: str) -> str:
    """The page for 60 s, always: it names the versions and the link, so it never pins. A script, style, image or font
    asked for at the current version: for good. Images and fonts otherwise a day; scripts and styles 60 s."""
    if rel.endswith(".html"):
        return APP_SHORT
    if v == version:
        return IMMUTABLE
    return APP_ASSET if content_type.startswith(("image/", "font/", "audio/")) else APP_SHORT


async def app_file(request: web.Request) -> web.Response:
    """A file of the public build, by its exact allowlisted name; anything else is a 404 the edge keeps for 5 minutes
    (the viewer's probes for art and sound files that aren't installed among them, so it falls back as without them)."""
    rel = request.match_info["path"] or "index.html"
    found = request.app[PUBLIC_APP].serve_full(rel)  # body and version from one look at the disk
    if found is None:
        return web.Response(status=404, text="not found",
                            headers={"Cache-Control": APP_MISSING, "X-Content-Type-Options": "nosniff"})
    body, gz, content_type, version = found
    raw = request.rel_url.raw_query_string
    if rel.endswith(".html"):  # a page ignores its query (?skin= among it): the same bytes and 60 s whatever it is
        v = None
    elif raw in ("", f"v={version}"):
        v = version if raw else None
    else:  # another spelling is another edge key: sent to the canonical URL
        return redirect(f"/public/app/{quote(rel)}?v={version}", APP_SHORT)
    headers = {"Content-Type": content_type, "Cache-Control": app_cache(rel, content_type, v, version),
               "Vary": "Accept-Encoding", "X-Content-Type-Options": "nosniff"}
    if gz is not None and _takes_gzip(request.headers.get("Accept-Encoding")):
        headers["Content-Encoding"] = "gzip"
        body = gz
    return web.Response(body=body, headers=headers)


def add_public_routes(app: web.Application) -> None:
    """GET (and HEAD) routes under /public/: the documents and the public app when this world publishes, and in every
    case a 404 for anything else under /public, so nothing there is ever a file from web/. Every route registered here
    is one a tunnel may reach (app.proxied_reach_only_public goes by the matched route), so nothing private goes under
    /public; the app's files come from PublicApp's allowlist, never a folder."""
    r = app.router
    if PUBLISHER in app:
        r.add_get("/public", to_app)
        r.add_get("/public/", to_app)
        r.add_get("/public/live.json", live_json)
        r.add_get("/public/static.json", static_json)
        r.add_get("/public/creature/{cid}.json", creature_json)
        r.add_get("/public/almanac.json", almanac_json)
        r.add_get("/public/history.json", history_json)
        r.add_get("/public/chronicle.json", chronicle_json)
        r.add_route("*", "/public/here", here)  # every method, so a GET is a 405 and not the catch-all's 404
        if PUBLIC_APP in app:
            r.add_get("/public/app", to_app_folder)
            r.add_get("/public/app/{path:.*}", app_file)
    else:
        r.add_get("/public", not_public)
    r.add_get("/public/{tail:.*}", not_public)  # last: anything else under /public/ is a 404, never a file in web/
