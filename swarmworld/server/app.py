"""aiohttp application: tick loop, brain-node and viewer WebSockets, REST, and the static viewer."""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import json
import logging
import secrets
from pathlib import Path

from aiohttp import WSMsgType, web

from ..mind.recall import embed_pending
from ..world.model import FrontierSettings
from .almanac import Almanac
from .harness import Harness
from .persistence import restore, save
from .public import PUBLIC_EVERY, PUBLISHER, Publisher
from .public_app import PUBLIC_APP, PublicApp
from .public_http import add_public_routes
from .state import ServerState

log = logging.getLogger("swarmworld.server")
WEB_DIR = Path(__file__).resolve().parent.parent.parent / "web"
STATE = web.AppKey("state", ServerState)
ALMANAC = web.AppKey("almanac", Almanac)
PROXY_HEADERS = ("CF-Connecting-IP", "CF-Ray", "X-Forwarded-For", "X-Real-IP", "Forwarded", "Cdn-Loop", "Via")


def is_direct_local(request: web.Request) -> bool:
    """True only for a request made on this machine itself, not one relayed by a tunnel or proxy running here."""
    return request.remote in ("127.0.0.1", "::1") and not any(h in request.headers for h in PROXY_HEADERS)


def home_network(remote: str | None, headers) -> bool:
    """A request straight from this machine or the home network (private or link-local addresses), never one relayed
    by a tunnel or proxy, even one running on this machine: the steward's actions work from a phone in bed, and a
    public tunnel can't reach them."""
    if any(h in headers for h in PROXY_HEADERS):
        return False
    try:
        addr = ipaddress.ip_address(remote or "")
    except ValueError:
        return False
    return addr.is_loopback or addr.is_private or addr.is_link_local


def is_home_network(request: web.Request) -> bool:
    return home_network(request.remote, request.headers)


def token_matches(given: str | None, token: str | None) -> bool:
    """The join token, compared in constant time as ASCII bytes: anything else (missing, empty, non-ASCII, the
    undecodable bytes a header can carry, a number or list from a node's JSON hello) is refused, never an error."""
    if not isinstance(given, str) or not isinstance(token, str) or not given or not token:
        return False
    try:
        return secrets.compare_digest(given.encode("ascii"), token.encode("ascii"))
    except UnicodeEncodeError:
        return False


def _matched_route(request: web.Request) -> str:
    """The canonical path of the route the router matched ("" when none did: a 404 or 405 to come)."""
    resource = request.match_info.route.resource
    return resource.canonical if resource is not None else ""


@web.middleware
async def proxied_reach_only_public(request: web.Request, handler):
    """A request relayed by a tunnel or proxy (any of PROXY_HEADERS) reaches the public viewer and nothing else: a
    route registered under /public/ (judged by the route the router matched, so an encoded slash such as
    /public%2F..%2Findex.html, which goes to the file server, can't pass), or GET /api/almanac with the join token.
    / sends it to the public app; everything else is a 404, as if it weren't there: no steward action, wish answer,
    voice, node or viewer socket, private viewer file or other API. The handlers' own checks stay as a second layer."""
    if not any(h in request.headers for h in PROXY_HEADERS):
        return await handler(request)
    route = _matched_route(request)
    if route == "/public" or route.startswith("/public/"):
        return await handler(request)
    if (request.method == "GET" and route == "/api/almanac"
            and token_matches(request.headers.get("X-Swarm-Token"), request.app[STATE].token)):
        return await handler(request)
    if request.method in ("GET", "HEAD") and request.path == "/":
        raise web.HTTPFound("/public/app/")
    raise web.HTTPNotFound()


async def tick_loop(app: web.Application) -> None:
    st = app[STATE]
    loop = asyncio.get_running_loop()
    last_pub_log = [-60.0]
    while True:
        started = loop.time()
        try:
            new_events = st.sim.tick()
            if st.world_path and st.world.tick % 240 == 0:
                save(st, st.world_path)
            st.expire_jobs()
            for node, job in st.plan_dispatch():
                try:
                    await node.ws.send_json(job)
                except Exception:  # node vanished mid-send; disconnect handler cleans up
                    pass
            msg = st.tick_dict(new_events)
            pub = app.get(PUBLISHER)
            if pub is not None:
                try:
                    pub.observe(msg, new_events)
                    if pub.due():
                        pub.publish()
                except Exception:
                    now = loop.time()
                    if now - last_pub_log[0] >= 60.0:
                        last_pub_log[0] = now
                        log.exception("publishing failed")
            if st.viewers:
                payload = json.dumps(msg)
                metrics = st.metrics_message() if st.world.tick % 10 == 0 else None
                for ws in list(st.viewers):
                    try:
                        await ws.send_str(payload)
                        if metrics:
                            await ws.send_str(metrics)
                    except Exception:
                        st.viewers.discard(ws)
        except Exception:
            log.exception("tick failed")
        st.record_tick((loop.time() - started) * 1000)
        await asyncio.sleep(max(0.0, st.tick_seconds - (loop.time() - started)))


EMBED_EVERY_S = 3.0
EMBED_MAX_WAIT_S = 300.0


async def embed_loop(app: web.Application, every: float = EMBED_EVERY_S, sleep=asyncio.sleep) -> None:
    """Embed what recall is waiting on, one batch at a time, off the tick loop. Failures just mean keyword search:
    each is logged on one line (HTTP status or error type, never the key) and the wait doubles, up to 5 minutes,
    until a batch succeeds. A refused key (401/403) turns embeddings off for the rest of the session."""
    st = app[STATE]
    wait = every
    while st.embedder is not None:
        try:
            await embed_pending(st.recall, st.embedder)
            wait = every
        except Exception as exc:
            status = getattr(exc, "status", None)
            what = f"HTTP {status}" if isinstance(status, int) else type(exc).__name__
            if status in (401, 403):
                log.warning("Voyage refused the API key (%s): recall search is keywords only for the rest of this "
                            "session", what)
                st.embedder = None
                return
            wait = min(EMBED_MAX_WAIT_S, wait * 2)
            log.warning("recall embedding failed (%s); keyword search continues, retrying in %.0f s", what, wait)
        await sleep(wait)


async def node_ws(request: web.Request) -> web.WebSocketResponse:
    st = request.app[STATE]
    ws = web.WebSocketResponse(heartbeat=20, max_msg_size=4 * 1024 * 1024)
    await ws.prepare(request)
    direct = is_direct_local(request) or request.remote not in ("127.0.0.1", "::1")  # LAN peers connect directly
    node = None
    try:
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            try:
                data = json.loads(msg.data)
            except json.JSONDecodeError:
                continue
            if not isinstance(data, dict):  # [1, 2], "x", 42, null: not a message
                continue
            kind = data.get("type")
            if node is None:
                if kind != "hello":
                    await ws.send_json({"type": "error", "message": "say hello first"})
                    continue
                if (st.token and not token_matches(data.get("token"), st.token)) or (not st.token and not direct):
                    msg = "bad join token" if st.token else "joining from outside this machine needs a join token (start the world with --token)"
                    await ws.send_json({"type": "error", "message": msg})
                    await ws.close()
                    break
                if st.name_in_use(str(data.get("node") or "")):
                    await ws.send_json({"type": "error", "message": f"a brain node named '{data.get('node')}' is already "
                                        "connected; give this one another name with --name"})
                    await ws.close()
                    break
                node, creatures = st.register_node(ws, data)
                log.info("node %s joined (%s slots) with %d creatures", node.name, node.slots, len(creatures))
                await ws.send_json({"type": "welcome", "node_id": node.id,
                                    "creatures": [{"id": c.id, "name": c.name, "model": c.model} for c in creatures]})
            elif kind == "result":
                try:
                    st.handle_result(node, data)
                except Exception:  # one bad reply costs one creature its turn, never the node its connection
                    log.exception("could not apply result %s from %s", data.get("job"), node.name)
            elif kind == "bye":
                break
    finally:
        if node is not None:
            st.unregister_node(node.id)
            log.info("node %s left", node.name)
    return ws


async def view_ws(request: web.Request) -> web.WebSocketResponse:
    st = request.app[STATE]
    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)
    await ws.send_json(st.world.to_init())
    await ws.send_str(st.metrics_message())
    st.viewers.add(ws)
    try:
        async for _ in ws:
            pass
    finally:
        st.viewers.discard(ws)
    return ws


async def api_state(request: web.Request) -> web.Response:
    return web.json_response(request.app[STATE].world.to_init())


async def api_creature(request: web.Request) -> web.Response:
    detail = request.app[STATE].creature_detail(request.match_info["cid"])
    if detail is None:
        raise web.HTTPNotFound()
    return web.json_response(detail)


async def api_metrics(request: web.Request) -> web.Response:
    return web.Response(text=request.app[STATE].metrics_message(), content_type="application/json")


async def api_chronicle(request: web.Request) -> web.Response:
    return web.json_response(request.app[STATE].chronicle)


async def api_inventions(request: web.Request) -> web.Response:
    return web.json_response(getattr(request.app[STATE].world.catalog, "inventions", []))


async def api_voice(request: web.Request) -> web.Response:
    """A voice from the sky: the human experimenter speaks into the world. Only from the home network, or with the join token."""
    st = request.app[STATE]
    if not is_home_network(request) and not token_matches(request.headers.get("X-Swarm-Token"), st.token):
        raise web.HTTPForbidden(text="the voice from the sky only speaks from the home network")
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("bad request")
        text = " ".join(str(body.get("text", "")).split())[:300]
        if not text:
            raise web.HTTPBadRequest(text="say something")
        heard = st.voice_from_the_sky(text, body.get("x"), body.get("y"), body.get("radius"))
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise web.HTTPBadRequest(text=str(exc) or "bad request")
    return web.json_response({"ok": True, "heard_by": heard})


async def api_wishes(request: web.Request) -> web.Response:
    return web.json_response({"can_answer": is_home_network(request), "wishes": request.app[STATE].wishes.ranked()})


async def api_wish_answer(request: web.Request) -> web.Response:
    """Answer a wish from the sky, grant it, or note it. Only from this machine, or with the join token."""
    st = request.app[STATE]
    if not is_home_network(request) and not token_matches(request.headers.get("X-Swarm-Token"), st.token):
        raise web.HTTPForbidden(text="wishes can only be answered from the home network")
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("bad request")
        out = st.answer_wish(request.match_info["wid"], reply=str(body.get("reply") or ""), grant=str(body.get("grant") or ""),
                             count=int(body.get("count") or 1), status=str(body.get("status") or ""))
    except KeyError:
        raise web.HTTPNotFound(text="no such wish")
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise web.HTTPBadRequest(text=str(exc) or "bad request")
    return web.json_response(out)


async def api_admin(request: web.Request) -> web.Response:
    """Steward actions (give, place, remove, move, weather, grow) for testing and managing the world. Home network
    only."""
    st = request.app[STATE]
    if not is_home_network(request):
        raise web.HTTPForbidden(text="steward actions only work from the home network")
    try:
        body = await request.json()
        out = st.admin(request.match_info["action"], body if isinstance(body, dict) else {})
    except KeyError:
        raise web.HTTPNotFound(text="unknown steward action; try give, place, remove, move, weather or grow")
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise web.HTTPBadRequest(text=str(exc) or "bad request")
    return web.json_response(out)


async def api_almanac(request: web.Request) -> web.Response:
    """Everything in the game, this world's discoveries and census, and the roadmap (web/almanac.html). For the
    user, not the creatures; only from this machine, or with the join token."""
    st = request.app[STATE]
    if not is_home_network(request) and not token_matches(request.headers.get("X-Swarm-Token"), st.token):
        raise web.HTTPForbidden(text="the almanac only opens on the home network, or with the join token")
    return web.Response(text=request.app[ALMANAC].text(st), content_type="application/json")


async def api_society(request: web.Request) -> web.Response:
    return web.json_response(request.app[STATE].society())


async def api_history(request: web.Request) -> web.Response:
    return web.json_response(request.app[STATE].history)


async def api_nodes(request: web.Request) -> web.Response:
    st = request.app[STATE]
    local = is_direct_local(request)
    return web.json_response([
        {"name": n.name, "slots": n.slots, "inflight": len(n.inflight), "models": n.models,
         "hardware": n.hardware if local else {}}
        for n in st.nodes.values()
    ])


async def static_file(request: web.Request) -> web.StreamResponse:
    """The private viewer's files: anything inside web/, never outside it (an absolute path segment, which would make
    WEB_DIR / rel drop WEB_DIR, is refused outright; containment is by path parts, so a sibling web*/ isn't inside)."""
    rel = request.match_info.get("path") or "index.html"
    root = WEB_DIR.resolve()
    try:
        if Path(rel).is_absolute():
            raise web.HTTPNotFound()
        target = (root / rel).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            raise web.HTTPNotFound()
    except (OSError, ValueError):  # a NUL byte, a name too long
        raise web.HTTPNotFound() from None
    return web.FileResponse(target, headers={"Cache-Control": "no-cache"})


def create_app(seed: int = 7, token: str | None = None, tick_seconds: float = 0.5,
               run_dir: Path | None = None, start_loop: bool = True, world_path: Path | None = None,
               resume: bool = True, harness: Harness | None = None, embedder=None,
               log_prompts: bool = False, public_every: float = PUBLIC_EVERY,
               public_link: str | None = None, frontier: FrontierSettings | None = None) -> web.Application:
    app = web.Application(middlewares=[proxied_reach_only_public])
    st = ServerState(seed=seed, token=token, tick_seconds=tick_seconds, run_dir=run_dir, harness=harness,
                     log_prompts=log_prompts, frontier=frontier)
    st.world_path = world_path
    st.embedder = embedder
    if world_path and resume and world_path.exists():
        restore(st, world_path)
        log.info("resumed world from %s at tick %d with %d creatures", world_path, st.world.tick, len(st.world.creatures))
    app[STATE] = st
    app[ALMANAC] = Almanac()
    if public_every > 0:
        app[PUBLISHER] = pub = Publisher(st, app[ALMANAC], every=public_every)
        app[PUBLIC_APP] = PublicApp(WEB_DIR, link=public_link)  # reads web/ on first use, not here
        try:
            pub.publish()  # the documents exist from the start
        except Exception:
            log.exception("publishing failed")
    app.router.add_get("/ws/node", node_ws)
    app.router.add_get("/ws/view", view_ws)
    app.router.add_get("/api/state", api_state)
    app.router.add_get("/api/creature/{cid}", api_creature)
    app.router.add_get("/api/metrics", api_metrics)
    app.router.add_get("/api/nodes", api_nodes)
    app.router.add_get("/api/chronicle", api_chronicle)
    app.router.add_get("/api/inventions", api_inventions)
    app.router.add_post("/api/voice", api_voice)
    app.router.add_get("/api/society", api_society)
    app.router.add_get("/api/wishes", api_wishes)
    app.router.add_post("/api/wishes/{wid}", api_wish_answer)
    app.router.add_post("/api/admin/{action}", api_admin)
    app.router.add_get("/api/history", api_history)
    app.router.add_get("/api/almanac", api_almanac)
    add_public_routes(app)  # before the catch-all, so nothing under /public/ is ever a file from web/
    app.router.add_get("/", static_file)
    app.router.add_get("/{path:.+}", static_file)

    async def _on_shutdown(app: web.Application) -> None:
        st = app[STATE]
        if st.world_path:
            save(st, st.world_path)  # first thing, before anything can be interrupted
        for ws in list(st.viewers) + [n.ws for n in st.nodes.values()]:
            with contextlib.suppress(Exception):
                await ws.close(code=1001, message=b"world is shutting down")

    app.on_shutdown.append(_on_shutdown)

    if start_loop:
        async def _start(app: web.Application):
            task = asyncio.create_task(tick_loop(app))
            embed_task = asyncio.create_task(embed_loop(app)) if app[STATE].embedder else None
            yield
            if app[STATE].world_path:  # save first, synchronously, so a second signal can't cut it short
                save(app[STATE], app[STATE].world_path)
            for t in (task, embed_task):
                if t:
                    t.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await t

        app.cleanup_ctx.append(_start)
    return app
