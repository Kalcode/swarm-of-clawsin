"""Brain node: connect to the world, receive think jobs, answer them with a local model."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import aiohttp

log = logging.getLogger("swarmworld.node")


@dataclass
class ModelSpec:
    tag: str
    brain: Any
    creatures: int
    adopt: list[str] = field(default_factory=list)  # other models whose sleeping creatures this one takes over


class FatalNodeError(Exception):
    pass


async def _handle(ws: aiohttp.ClientWebSocketResponse, job: dict, brains: dict[str, Any], default: Any,
                  sem: asyncio.Semaphore, stats: dict) -> None:
    brain = brains.get(job.get("model")) or default
    async with sem:
        t0 = time.monotonic()
        ok, output, error, usage = await brain.think(job["messages"], job.get("schema"), int(job.get("max_tokens") or 256))
        latency = int((time.monotonic() - t0) * 1000)
    stats["thinks"] += 1
    if not ok:
        stats["errors"] += 1
        log.warning("think failed for %s: %s", job.get("creature"), error)
    try:
        await ws.send_json({"type": "result", "job": job["job"], "ok": ok, "output": output, "error": error,
                            "latency_ms": latency, "tokens_in": usage.get("prompt_tokens", 0),
                            "tokens_out": usage.get("completion_tokens", 0),
                            "cached_tokens": (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)})
    except Exception:
        pass


async def run_node(server_url: str, name: str, models: list[ModelSpec], slots: int, token: str | None = None,
                   hardware: dict | None = None, once: bool = False) -> None:
    url = server_url.rstrip("/")
    if not url.endswith("/ws/node"):
        url += "/ws/node"
    brains = {m.tag: m.brain for m in models}
    default = models[0].brain
    hello = {"type": "hello", "node": name, "token": token, "slots": slots,
             "models": [{"tag": m.tag, "creatures": m.creatures, "adopt": m.adopt} for m in models], "hardware": hardware or {}}
    backoff = 1.0
    stats = {"thinks": 0, "errors": 0}
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(url, heartbeat=20, max_msg_size=8 * 1024 * 1024) as ws:
                    await ws.send_json(hello)
                    sem = asyncio.Semaphore(slots)
                    tasks: set[asyncio.Task] = set()
                    backoff = 1.0
                    async for msg in ws:
                        if msg.type != aiohttp.WSMsgType.TEXT:
                            continue
                        data = json.loads(msg.data)
                        kind = data.get("type")
                        if kind == "welcome":
                            names = ", ".join(c["name"] for c in data.get("creatures", []))
                            log.info("joined the world as %s; creatures: %s", data.get("node_id"), names)
                            print(f"  Joined! Your creatures: {names}")
                        elif kind == "think":
                            t = asyncio.create_task(_handle(ws, data, brains, default, sem, stats))
                            tasks.add(t)
                            t.add_done_callback(tasks.discard)
                        elif kind == "error":
                            log.error("server says: %s", data.get("message"))
                            if "token" in str(data.get("message")):
                                raise FatalNodeError(data.get("message"))
            log.warning("disconnected from world")
        except FatalNodeError:
            raise
        except (aiohttp.ClientError, OSError, asyncio.TimeoutError) as exc:
            log.warning("cannot reach world at %s (%s); retrying in %.0fs", url, exc, backoff)
        if once:
            return
        await asyncio.sleep(backoff)
        backoff = min(30.0, backoff * 2)
