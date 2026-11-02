"""Turn-based play: the world's clock waits until every thinking creature has its answer, so a model's speed doesn't
change what it gets to do. Headless (no viewer, no sockets), but through the same ServerState code paths as the live
server: dispatch, prompts, parsing, actions, memory and learning. Used by bench/world_bench.py (comparing models) and
scripts/teacher_runs.py (teacher data for distillation)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from .state import Node, ServerState

MILESTONES = ["rope", "stone_knife", "stone_axe", "campfire_placed", "invention", "hoe", "fishing_rod", "planks"]
ITEM_MILESTONES = ("rope", "stone_knife", "stone_axe", "hoe", "fishing_rod", "planks")

ThinkResult = tuple[bool, Any, "str | None", dict]
Think = Callable[[dict], Awaitable[ThinkResult]]


class NullWS:
    """A brain node's socket for headless play: jobs are handed out by the loop, never sent."""

    closed = False

    async def send_json(self, _):
        pass


@dataclass
class Tally:
    """What an episode reached: the first tick (since the start) of each milestone, things learned, words said."""

    start: int = 0
    first: dict[str, int] = field(default_factory=dict)
    learned: int = 0
    speech: int = 0

    def see(self, st: ServerState, events: list) -> None:
        w = st.world
        for e in events:
            if e.kind == "learn":
                self.learned += 1
            elif e.kind == "say" and e.actor:
                self.speech += 1
            elif e.kind == "place" and e.data.get("object_kind") == "campfire":
                self.first.setdefault("campfire_placed", w.tick - self.start)
            elif e.kind == "invent":
                self.first.setdefault("invention", w.tick - self.start)
        for c in w.creatures.values():
            for item in ITEM_MILESTONES:
                if c.inventory.get(item):
                    self.first.setdefault(item, w.tick - self.start)


def join(st: ServerState, name: str, tag: str, creatures: int, slots: int | None = None) -> Node:
    """One headless brain node with `creatures` creatures of one model; `slots` (default: all of them) can think at once."""
    node, _ = st.register_node(NullWS(), {"node": name, "slots": slots or creatures,
                                          "models": [{"tag": tag, "creatures": creatures}]})
    return node


async def play(st: ServerState, node: Node, think: Think, ticks: int, tally: Tally | None = None) -> Tally:
    """Run `ticks` world ticks. Each tick, every creature ready to think gets a job; `think(job)` answers it (the
    calls run together) and time moves on only when all have answered."""
    tally = tally or Tally(start=st.world.tick)

    async def timed(job: dict) -> tuple[ThinkResult, int]:
        t0 = time.monotonic()
        out = await think(job)
        return out, int((time.monotonic() - t0) * 1000)

    for _ in range(ticks):
        events = st.sim.tick()
        st.tick_message(events)  # bookkeeping (event log, relations, metrics), same as the live loop
        tally.see(st, events)
        jobs = [job for _, job in st.plan_dispatch()]
        if jobs:  # turn-based: everyone who is thinking gets an answer before time moves on
            results = await asyncio.gather(*(timed(j) for j in jobs))
            for job, ((ok, output, error, usage), ms) in zip(jobs, results):
                st.handle_result(node, {"job": job["job"], "ok": ok, "output": output, "error": error, "latency_ms": ms,
                                        "tokens_in": usage.get("prompt_tokens", 0),
                                        "tokens_out": usage.get("completion_tokens", 0),
                                        "cached_tokens": (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)})
    st.tick_message(st.sim.take_events())  # what the last answers did, so the event log is complete
    return tally


def outcome(st: ServerState, tag: str, tally: Tally) -> dict:
    """How one model's creatures did in an episode (the benchmark's columns)."""
    m = st.metrics.models[tag]
    acts = m["act_ok"] + m["act_fail"]
    cs = st.world.creatures.values()
    return {"first": dict(tally.first), "thinks": m["thinks"], "success_rate": m["act_ok"] / acts if acts else 0,
            "parse_failures": m["parse_failures"], "errors": m["errors"], "loops": m["loops"], "learned": tally.learned,
            "speech": tally.speech, "crafted": sum(c.stats.get("crafted", 0) for c in cs),
            "noop_rate": m["noops"] / acts if acts else 0,
            "collapses": sum(c.stats.get("collapses", 0) for c in cs),
            "inventions": sum(c.stats.get("inventions", 0) for c in cs)}
