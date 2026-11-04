"""The frontier soak: a headless world of mock creatures that mostly explore, run for tens of thousands of ticks.

    uv run python scripts/frontier_soak.py --ticks 50000 --creatures 24 --seed 7 --out /tmp/frontier-soak.json

No sockets, no ports, no model: the live world's own pieces (ServerState, Publisher, the tick message, the viewer
payloads) driven the way the server's tick loop drives them, with MockBrain answering the thinks between ticks. Prints a
summary and exits 1 when a gate fails. The gates are the spec's (docs/superpowers/specs/2026-11-03-frontier-design.md)."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import statistics
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from swarmworld.node.brain import MockBrain  # noqa: E402
from swarmworld.server import persistence, turns  # noqa: E402
from swarmworld.server.public import Publisher  # noqa: E402
from swarmworld.server.state import ServerState  # noqa: E402
from swarmworld.world.model import FrontierSettings  # noqa: E402

WINDOW = 300        # ticks: the spec's 5 live minutes at 1 s ticks
AT_CAP = 2000       # ticks at the cap that the absolute gate looks at
MIN_AT_CAP = 200    # fewer than this many ticks at the cap and the absolute gate has measured nothing
DAY = 1200          # ticks: one in-game day, the window of the relative gate
MIN_WINDOW = 300    # a window shorter than this isn't measured
MEDIAN_FLOOR_MS = 0.5
SLACK = 1.25
FLOOR_MS = 1.0
ABSOLUTE_MS = 50.0
NEAR_START = 20     # start_near_edges: steps from the side's edge


median = statistics.median


def p95(xs: list[float]) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(0.95 * len(xs)))] if xs else 0.0


class _Errors(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.ERROR)
        self.records: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(f"{record.name}: {record.getMessage()}")


def _near_edges(st: ServerState, creatures: list) -> None:
    """Each creature to a free surface tile NEAR_START steps from its side's edge (east for even, west for odd)."""
    w = st.world
    s = w.region("surface")
    taken: set[tuple[int, int]] = set()
    for i, c in enumerate(creatures):
        x = w.width - 1 - NEAR_START if i % 2 == 0 else NEAR_START
        y0 = s.y0 + (i * 7) % (s.y1 - s.y0)
        spot = next((x + dx, y) for dx in range(0, 12) for y in sorted(range(s.y0, s.y1), key=lambda y: abs(y - y0))
                    if w.walkable(x + dx, y) and (x + dx, y) not in w.grid and (x + dx, y) not in taken)
        taken.add(spot)
        c.x, c.y = spot
        c.activity = None


def _stuck(st: ServerState) -> int:
    w = st.world
    return sum(1 for c in w.creatures.values() if not w.walkable(c.x, c.y))


def soak(ticks: int, creatures: int, seed: int = 7, settings: FrontierSettings = FrontierSettings(on=True),
         explore_bias: float = 0.6, start_near_edges: bool = False, log=print) -> dict:
    handler = _Errors()
    logging.getLogger("swarmworld").addHandler(handler)
    try:
        return _soak(ticks, creatures, seed, settings, explore_bias, start_near_edges, log, handler)
    finally:
        logging.getLogger("swarmworld").removeHandler(handler)


def _soak(ticks, creatures, seed, settings, explore_bias, start_near_edges, log, handler) -> dict:
    st = ServerState(seed, tick_seconds=1.0, frontier=settings)
    w = st.world
    node = turns.join(st, "soak", "mock", creatures)
    pub = Publisher(st, clock=lambda: float(st.world.tick), every=3.0)
    brain = MockBrain(seed)
    mind = brain.rng.__class__(f"{seed}:soak")  # the explore dice, apart from the brain's
    cs = list(w.creatures.values())
    side_of = {c.id: ("east" if i % 2 == 0 else "west") for i, c in enumerate(cs)}
    if start_near_edges:
        _near_edges(st, cs)
    loop = asyncio.new_event_loop()
    exceptions: list[str] = []
    times: list[float] = []
    widths: list[int] = []       # the width at each timed tick
    growths: list[dict] = []
    stuck = 0

    def guard(what: str, fn, *a):
        try:
            return fn(*a)
        except Exception as exc:  # the live loop logs and carries on; the soak counts
            exceptions.append(f"{what}: {type(exc).__name__}: {exc}")
            return None

    def noticed(width_before: int, origin_before: int) -> None:
        nonlocal stuck
        if w.width != width_before:
            side = "west" if w.origin_x != origin_before else "east"
            growths.append({"tick": w.tick, "side": side, "width_before": width_before, "width": w.width,
                            "at": len(times)})
            if side == "west":
                stuck += _stuck(st)
            log(f"  tick {w.tick}: strip {side}, {width_before} -> {w.width}")

    async def answer(job: dict):
        ok, out, err, usage = await brain.think(job["messages"], job["schema"], job["max_tokens"])
        if ok and job["schema"] and mind.random() < explore_bias:
            out = {**out, "action": "explore", "target": side_of.get(job["creature"], "east"), "items": [], "text": "",
                   "count": 1, "thought": "I want to see what lies that way."}
        return ok, out, err, usage

    async def answer_all(jobs: list[dict]):
        return await asyncio.gather(*(answer(j) for j in jobs))

    for _ in range(ticks):
        before = (w.width, w.origin_x)
        t0 = time.perf_counter()
        events = guard("tick", st.sim.tick) or []
        msg = guard("tick_dict", st.tick_dict, events)
        if msg is not None:
            guard("observe", pub.observe, msg, events)
            if pub.due():
                guard("publish", pub.publish)
            guard("viewer_payloads", st.viewer_payloads, msg)
        times.append((time.perf_counter() - t0) * 1000)
        widths.append(w.width)
        noticed(*before)
        jobs = guard("dispatch", lambda: [j for _, j in st.plan_dispatch()]) or []
        if jobs:
            results = loop.run_until_complete(answer_all(jobs))
            for job, (ok, out, err, usage) in zip(jobs, results):
                before = (w.width, w.origin_x)
                guard("result", st.handle_result, node, {
                    "job": job["job"], "ok": ok, "output": out, "error": err, "latency_ms": 0,
                    "tokens_in": usage.get("prompt_tokens", 0), "tokens_out": usage.get("completion_tokens", 0),
                    "cached_tokens": 0})
                noticed(*before)
    loop.close()
    stuck += _stuck(st)

    # the relative gate: the median tick over a day after each growth against the day before (p95s are information)
    for g in growths:
        at = g["at"]  # the index of the first timed tick after the growth
        b, a = times[max(0, at - DAY):at], times[at:at + DAY]
        g["p95_before_ms"], g["p95_after_ms"] = round(p95(b), 3), round(p95(a), 3)
        g["measured"] = len(b) >= MIN_WINDOW and len(a) >= MIN_WINDOW  # a cut-short window of 300 or more counts
        g["median_before_ms"], g["median_after_ms"] = round(median(b), 3) if b else 0.0, round(median(a), 3) if a else 0.0
        g["ok"] = (not g["measured"]) or (max(g["median_after_ms"], MEDIAN_FLOOR_MS)
                                          <= SLACK * max(g["median_before_ms"], MEDIAN_FLOOR_MS) * g["width"] / g["width_before"])
    windows = [round(p95(times[i:i + WINDOW]), 2) for i in range(0, len(times) - WINDOW + 1, WINDOW)]
    # the noise floor: how far adjacent 300-tick windows differ where no growth lies between them
    cuts = {g["at"] // WINDOW for g in growths}
    pairs = [max(windows[i + 1], FLOOR_MS) / max(windows[i], FLOOR_MS) for i in range(len(windows) - 1)
             if i not in cuts and i + 1 not in cuts]
    noise = {"pairs": len(pairs), "max_ratio": round(max(pairs), 2) if pairs else None,
             "share_over_slack": round(sum(r > SLACK for r in pairs) / len(pairs), 2) if pairs else None}
    cap_ms = [t for t, wd in zip(times, widths) if wd >= settings.cap][-AT_CAP:]
    p95_cap = round(p95(cap_ms), 3) if cap_ms else None

    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "soak-world.json"
        persistence.save(st, path)
        st2 = ServerState(seed, tick_seconds=1.0, frontier=settings)
        persistence.restore(st2, path)
        norm = lambda s: json.loads(json.dumps(persistence.snapshot(s)["world"]))  # noqa: E731
        round_trip = norm(st) == norm(st2)

    from tests.test_frontier_shift import uncovered
    gaps = sorted(uncovered(w))

    strips = dict(w.ext.get("frontier", {}).get("strips") or {"east": 0, "west": 0})
    errors = len(handler.records) + len(exceptions)
    gates = {
        "strips": strips["east"] >= 2 and strips["west"] >= 2,
        "errors": errors == 0,
        "relative": all(g["ok"] for g in growths),
        "absolute": p95_cap is not None and len(cap_ms) >= MIN_AT_CAP and p95_cap < ABSOLUTE_MS,
        "stuck": stuck == 0,
        "round_trip": round_trip,
        "canary": not gaps,
    }
    return {"ticks": ticks, "width": w.width, "strips": strips, "growths": growths, "errors": errors,
            "error_samples": (handler.records + exceptions)[:10], "stuck": stuck, "p95_at_cap_ms": p95_cap,
            "samples_at_cap": len(cap_ms), "p95_all_ms": round(p95(times), 3),
            "windows_p95_ms": windows, "noise": noise, "round_trip": round_trip,
            "uncovered": gaps, "gates": gates, "ok": all(gates.values())}


def report(r: dict) -> str:
    lines = [f"ticks {r['ticks']}, width {r['width']}, strips east {r['strips']['east']} west {r['strips']['west']}, "
             f"p95 overall {r['p95_all_ms']} ms",
             f"{'tick':>7} {'side':<5} {'width':>11} {'median bef':>11} {'median aft':>11} {'p95 bef':>9} {'p95 aft':>9}  gate (median)"]
    for g in r["growths"]:
        lines.append(f"{g['tick']:>7} {g['side']:<5} {g['width_before']:>5}->{g['width']:<5} "
                     f"{g['median_before_ms']:>9} ms {g['median_after_ms']:>8} ms {g['p95_before_ms']:>7} {g['p95_after_ms']:>8}  "
                     f"{'ok' if g['ok'] else 'FAIL'}{'' if g['measured'] else ' (skipped: window under 300 ticks)'}")
    n = r["noise"]
    lines.append(f"noise floor: of {n['pairs']} adjacent 300-tick windows with no growth between, {n['share_over_slack']} "
                 f"rose by more than {SLACK}x (largest {n['max_ratio']}x)")
    lines.append(f"p95 at the cap ({r['samples_at_cap']} ticks): {r['p95_at_cap_ms']} ms; errors {r['errors']}; "
                 f"creatures stuck {r['stuck']}; round trip {r['round_trip']}; uncovered stores {r['uncovered']}")
    lines += [f"  error: {e}" for e in r["error_samples"]]
    lines.append("gates: " + ", ".join(f"{k} {'ok' if v else 'FAIL'}" for k, v in r["gates"].items()))
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ticks", type=int, default=50000)
    ap.add_argument("--creatures", type=int, default=24)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--explore-bias", type=float, default=0.6)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    r = soak(a.ticks, a.creatures, a.seed, explore_bias=a.explore_bias)
    print(report(r))
    if a.out:
        a.out.write_text(json.dumps(r, indent=1))
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
