"""aiohttp application: tick loop, brain-node and viewer WebSockets, REST, and the static viewer."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from pathlib import Path

from aiohttp import WSMsgType, web

from .persistence import restore, save
from .state import ServerState

log = logging.getLogger("swarmworld.server")
WEB_DIR = Path(__file__).resolve().parent.parent.parent / "web"
STATE = web.AppKey("state", ServerState)


async def tick_loop(app: web.Application) -> None:
    st = app[STATE]
    loop = asyncio.get_running_loop()
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
            if st.viewers:
                payload = st.tick_message(new_events)
                metrics = st.metrics_message() if st.world.tick % 10 == 0 else None
                for ws in list(st.viewers):
                    try:
                        await ws.send_str(payload)
                        if metrics:
                            await ws.send_str(metrics)
                    except Exception:
                        st.viewers.discard(ws)
            else:
                st.tick_message(new_events)  # still log events and clear object deltas
        except Exception:
            log.exception("tick failed")
        await asyncio.sleep(max(0.0, st.tick_seconds - (loop.time() - started)))


async def node_ws(request: web.Request) -> web.WebSocketResponse:
    st = request.app[STATE]
    ws = web.WebSocketResponse(heartbeat=20, max_msg_size=4 * 1024 * 1024)
    await ws.prepare(request)
    node = None
    try:
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            try:
                data = json.loads(msg.data)
            except json.JSONDecodeError:
                continue
            kind = data.get("type")
            if node is None:
                if kind != "hello":
                    await ws.send_json({"type": "error", "message": "say hello first"})
                    continue
                if st.token and data.get("token") != st.token:
                    await ws.send_json({"type": "error", "message": "bad join token"})
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
    """A voice from the sky: the human experimenter speaks into the world. Only from this machine, or with the join token."""
    st = request.app[STATE]
    local = request.remote in ("127.0.0.1", "::1")
    if not local and not (st.token and request.headers.get("X-Swarm-Token") == st.token):
        raise web.HTTPForbidden(text="the voice from the sky only speaks from the world's own machine")
    body = await request.json()
    text = " ".join(str(body.get("text", "")).split())[:300]
    if not text:
        raise web.HTTPBadRequest(text="say something")
    heard = st.voice_from_the_sky(text, body.get("x"), body.get("y"), body.get("radius"))
    return web.json_response({"ok": True, "heard_by": heard})


async def api_society(request: web.Request) -> web.Response:
    return web.json_response(request.app[STATE].society())


async def api_history(request: web.Request) -> web.Response:
    return web.json_response(request.app[STATE].history)


async def api_nodes(request: web.Request) -> web.Response:
    st = request.app[STATE]
    return web.json_response([
        {"name": n.name, "slots": n.slots, "inflight": len(n.inflight), "models": n.models, "hardware": n.hardware}
        for n in st.nodes.values()
    ])


async def static_file(request: web.Request) -> web.StreamResponse:
    rel = request.match_info.get("path") or "index.html"
    target = (WEB_DIR / rel).resolve()
    if not str(target).startswith(str(WEB_DIR.resolve())) or not target.is_file():
        raise web.HTTPNotFound()
    return web.FileResponse(target, headers={"Cache-Control": "no-cache"})


def create_app(seed: int = 7, token: str | None = None, tick_seconds: float = 0.5,
               run_dir: Path | None = None, start_loop: bool = True, world_path: Path | None = None,
               resume: bool = True) -> web.Application:
    app = web.Application()
    st = ServerState(seed=seed, token=token, tick_seconds=tick_seconds, run_dir=run_dir)
    st.world_path = world_path
    if world_path and resume and world_path.exists():
        restore(st, world_path)
        log.info("resumed world from %s at tick %d with %d creatures", world_path, st.world.tick, len(st.world.creatures))
    app[STATE] = st
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
    app.router.add_get("/api/history", api_history)
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
            yield
            if app[STATE].world_path:  # save first, synchronously, so a second signal can't cut it short
                save(app[STATE], app[STATE].world_path)
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        app.cleanup_ctx.append(_start)
    return app
