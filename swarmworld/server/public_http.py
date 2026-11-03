"""The /public/* handlers: each serves a document the Publisher already built (its bytes and its gzip, encoded once per
interval) with the spec's cache headers, an ETag (304 when the client has it) and gzip when the client takes it, or a
file of the public app that PublicApp already holds, looked up by its allowlisted name. Nothing here reads a file or
builds a document from request data; an unknown creature or path is a short-cached 404."""

from __future__ import annotations

from aiohttp import web

from .public import PUBLISHER, Doc
from .public_app import APP_ASSET, APP_MISSING, APP_SHORT, PUBLIC_APP

LIVE_CACHE = "public, max-age=2, s-maxage=3, stale-while-revalidate=10"
IMMUTABLE = "public, max-age=31536000, immutable"
MINUTE = "public, max-age=60"
MISSING = "public, max-age=3"


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


async def live_json(request: web.Request) -> web.Response:
    return _serve(request, request.app[PUBLISHER].live_doc(), LIVE_CACHE)


async def static_json(request: web.Request) -> web.Response:
    pub = request.app[PUBLISHER]
    doc = pub.static_doc()
    return _serve(request, doc, IMMUTABLE if request.query.get("v") == pub.static_version else LIVE_CACHE)


async def creature_json(request: web.Request) -> web.Response:
    doc = request.app[PUBLISHER].creature_doc(request.match_info["cid"])
    return doc_response(request, doc, LIVE_CACHE) if doc is not None else missing()


async def almanac_json(request: web.Request) -> web.Response:
    return doc_response(request, request.app[PUBLISHER].almanac_doc(), MINUTE)


async def history_json(request: web.Request) -> web.Response:
    return doc_response(request, request.app[PUBLISHER].history_doc(), MINUTE)


async def chronicle_json(request: web.Request) -> web.Response:
    pub = request.app[PUBLISHER]
    doc = pub.chronicle_doc()
    return doc_response(request, doc, IMMUTABLE if request.query.get("v") == pub.chronicle_version else LIVE_CACHE)


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
    return APP_ASSET if content_type.startswith(("image/", "font/")) else APP_SHORT


async def app_file(request: web.Request) -> web.Response:
    """A file of the public build, by its exact allowlisted name; anything else is a 404 the edge keeps for 5 minutes
    (the viewer's LimeZu and sound-sample probes among them, so both fall back as they do without the files)."""
    rel = request.match_info["path"] or "index.html"
    found = request.app[PUBLIC_APP].serve(rel)  # body and version from one look at the disk
    if found is None:
        return web.Response(status=404, text="not found",
                            headers={"Cache-Control": APP_MISSING, "X-Content-Type-Options": "nosniff"})
    body, content_type, version = found
    cache = app_cache(rel, content_type, request.query.get("v"), version)
    return web.Response(body=body, headers={"Content-Type": content_type, "Cache-Control": cache,
                                            "X-Content-Type-Options": "nosniff"})


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
        if PUBLIC_APP in app:
            r.add_get("/public/app", to_app_folder)
            r.add_get("/public/app/{path:.*}", app_file)
    else:
        r.add_get("/public", not_public)
    r.add_get("/public/{tail:.*}", not_public)  # last: anything else under /public/ is a 404, never a file in web/
