"""Do watchers slow the world?  Starts a throwaway world and a mock node, measures a quiet phase, then a phase with
many pollers fetching /public/* the way the public app does, and compares tick time, tick rate and CPU.

  uv run python scripts/public_load_test.py --port 7801 --clients 200 --seconds 60 --creatures 50

Never the live world's port (7777); a port that is already listening is refused too."""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import aiohttp

ROOT = Path(__file__).resolve().parent.parent
WARMUP_S = 15
CPU_FLAG_POINTS = 15.0


def percentile(xs: list[float], p: float) -> float:
    if not xs:
        return 0
    s = sorted(xs)
    return s[min(len(s) - 1, int(p * len(s)))]


def parse_cputime(s: str) -> float:
    """The `ps -o time=` column: [[hh:]mm:]ss[.ff] (minutes may exceed 59)."""
    total = 0.0
    for part in s.strip().split(":"):
        total = total * 60 + float(part)
    return total


def check_port(port: int) -> None:
    if port == 7777:
        raise SystemExit("port 7777 is the live world; the load test never touches it")
    with socket.socket() as s:
        s.settimeout(0.5)
        if s.connect_ex(("127.0.0.1", port)) == 0:
            raise SystemExit(f"port {port} is already in use")


def cpu_seconds(pid: int) -> float:
    out = subprocess.run(["ps", "-o", "time=", "-p", str(pid)], capture_output=True, text=True).stdout
    return parse_cputime(out) if out.strip() else 0.0


async def get_json(session: aiohttp.ClientSession, url: str) -> dict:
    async with session.get(url) as r:
        return await r.json(content_type=None)


async def wait_for(session, url: str, timeout: float = 60) -> None:
    end = time.time() + timeout
    while time.time() < end:
        try:
            async with session.get(url) as r:
                if r.status == 200:
                    return
        except aiohttp.ClientError:
            pass
        await asyncio.sleep(0.5)
    raise RuntimeError(f"{url} never came up")


async def poller(session, base: str, every: float, stop: asyncio.Event, stats: dict) -> None:
    seen_static, cids = None, []
    await asyncio.sleep(random.uniform(0, every))
    while not stop.is_set():
        async def fetch(path: str):
            t0 = time.perf_counter()
            try:
                async with session.get(base + path) as r:
                    body = await r.read()
                    stats["latency"].append((time.perf_counter() - t0) * 1000)
                    stats["requests"] += 1
                    if r.status != 200:
                        stats["errors"] += 1
                        return None
                    return json.loads(body)
            except Exception:
                stats["requests"] += 1
                stats["errors"] += 1
                return None
        live = await fetch("/public/live.json")
        if live:
            cids = [c["id"] for c in live.get("creatures", [])]
            if live.get("static") != seen_static:
                seen_static = live.get("static")
                await fetch(f"/public/static.json?v={seen_static}")
            if cids and random.random() < 0.10:
                await fetch(f"/public/creature/{random.choice(cids)}.json")
        try:
            await asyncio.wait_for(stop.wait(), every * random.uniform(0.9, 1.1))
        except asyncio.TimeoutError:
            pass


async def phase(session, base: str, pid: int, seconds: float, clients: int, every: float) -> dict:
    m0 = await get_json(session, base + "/api/metrics")
    cpu0, t0 = cpu_seconds(pid), time.time()
    stats = {"requests": 0, "errors": 0, "latency": []}
    stop = asyncio.Event()
    tasks = [asyncio.create_task(poller(session, base, every, stop, stats)) for _ in range(clients)]
    await asyncio.sleep(seconds)
    m1 = await get_json(session, base + "/api/metrics")  # the tick window (60 s) is this phase when seconds == 60
    elapsed, cpu1 = time.time() - t0, cpu_seconds(pid)
    stop.set()
    await asyncio.gather(*tasks)
    tm = m1["tick_ms"]
    out = {"tick_p50": tm["p50"], "tick_p95": tm["p95"], "tick_max": tm["max"],
           "ticks_per_s": round((m1["tick"] - m0["tick"]) / elapsed, 3),
           "cpu_pct": round(100 * (cpu1 - cpu0) / elapsed, 1)}
    if clients:
        out.update(requests=stats["requests"], errors=stats["errors"],
                   latency_p95_ms=round(percentile(stats["latency"], 0.95), 1))
    return out


def verdict(base: dict, load: dict) -> bool:
    limit = max(1.25 * base["tick_p95"], base["tick_p95"] + 5)
    return (load["errors"] == 0 and load["tick_p95"] <= limit and load["ticks_per_s"] >= 0.97 * base["ticks_per_s"])


async def run(port: int, clients: int, seconds: float, creatures: int, every: float = 2.0) -> dict:
    check_port(port)
    d = Path(tempfile.mkdtemp(prefix="swarm-load-"))
    procs: list[subprocess.Popen] = []
    ok = False
    try:
        log = open(d / "procs.log", "w")
        server = subprocess.Popen([sys.executable, "-m", "swarmworld.server", "--port", str(port), "--world", str(d / "w.json"),
                                   "--runs", str(d / "runs"), "--fresh", "--embed", "none", "--tick", "1.0"],
                                  cwd=ROOT, stdout=log, stderr=log)
        procs.append(server)
        base = f"http://127.0.0.1:{port}"
        conn = aiohttp.TCPConnector(limit=0)
        async with aiohttp.ClientSession(connector=conn, timeout=aiohttp.ClientTimeout(total=30)) as session:
            await wait_for(session, base + "/public/live.json")
            procs.append(subprocess.Popen([sys.executable, "-m", "swarmworld.node", "--server", f"ws://127.0.0.1:{port}",
                                           "--mock", str(creatures), "--name", "loadtest"], cwd=ROOT, stdout=log, stderr=log))
            await asyncio.sleep(WARMUP_S)
            baseline = await phase(session, base, server.pid, seconds, 0, every)
            load = await phase(session, base, server.pid, seconds, clients, every)
        ok = verdict(baseline, load)
        return {"baseline": baseline, "load": load, "pass": ok,
                "cpu_flag": load["cpu_pct"] - baseline["cpu_pct"] > CPU_FLAG_POINTS, "folder": str(d)}
    finally:
        for p in reversed(procs):
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
        if ok:
            shutil.rmtree(d, ignore_errors=True)
        else:
            print(f"kept {d} (logs in procs.log)", file=sys.stderr)


def table(rep: dict) -> str:
    keys = ["tick_p50", "tick_p95", "tick_max", "ticks_per_s", "cpu_pct", "requests", "errors", "latency_p95_ms"]
    lines = [f"{'':16}{'baseline':>12}{'load':>12}"]
    for k in keys:
        lines.append(f"{k:16}{str(rep['baseline'].get(k, '-')):>12}{str(rep['load'].get(k, '-')):>12}")
    lines.append(f"CPU difference {rep['load']['cpu_pct'] - rep['baseline']['cpu_pct']:+.1f} points"
                 + ("  (FLAG: above 15)" if rep.get("cpu_flag") else ""))
    lines.append("PASS" if rep["pass"] else "FAIL")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=7801)
    ap.add_argument("--clients", type=int, default=200)
    ap.add_argument("--seconds", type=float, default=60)
    ap.add_argument("--creatures", type=int, default=50)
    ap.add_argument("--every", type=float, default=2.0, help="seconds between a poller's live.json fetches")
    a = ap.parse_args()
    rep = asyncio.run(run(a.port, a.clients, a.seconds, a.creatures, a.every))
    print(table(rep))
    raise SystemExit(0 if rep["pass"] else 1)


if __name__ == "__main__":
    main()
