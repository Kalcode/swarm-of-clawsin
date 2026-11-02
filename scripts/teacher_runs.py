"""Teacher data for distillation: headless, turn-based practice worlds where one teacher model thinks for every creature.

Each seed is one episode: a fresh world, N creatures, every harness layer (plan, disclose, recall) for every creature,
all installed packs, the clock waiting for every answer (bench/world_bench.py's loop, via swarmworld.server.turns), so
the teacher's speed doesn't matter. Recall is keywords only: no embedding service is ever called. The brain is the
live one (swarmworld.node.brain.LLMBrain), so each request is exactly what a live creature's would be.

    uv run python scripts/teacher_runs.py --base-url http://192.168.50.42:11434/v1 --model gpt-oss:20b --seeds 100-139
    uv run python scripts/teacher_runs.py --base-url http://127.0.0.1:8000/v1 --model Qwen3.5-9B-MLX-4bit --seeds 200-239
    uv run python scripts/teacher_runs.py --mock --seeds 1-2 --creatures 2 --ticks 60 --out /tmp/teacher   # plumbing

Each episode writes runs/teacher/<time>-<model tag>-s<seed>/:
    meta.json     model, base URL host, seed, creatures, ticks, harness layers, packs, recall, git commit (written first)
    thinks.jsonl  the live format; act lines also carry "messages" (the system and user prompt the model saw)
    events.jsonl  the live format
    chronicle.md  if the episode got that far (one chapter every 600 ticks)
    done          written last: the episode's summary (JSON). A folder without it is unfinished.

Resumable: a seed whose episode (same model tag) has a `done` marker is skipped; an unfinished one is renamed
<folder>.partial and the seed starts over. Several runs may write into one --out at once (say, the gaming PC's
gpt-oss and this Mac's Qwen) as long as their (model, seed) pairs differ: nothing else is shared.

A think that fails (timeout, HTTP error, dropped connection) is retried after 5 s, 15 s, 60 s and then every 60 s;
after 10 minutes of failures the creature idles that turn and the run says so (the thinks.jsonl line records the
error). Ctrl-C stops cleanly: the episode in progress has no `done`, so the next start redoes it."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from swarmworld.node.__main__ import short_tag  # noqa: E402
from swarmworld.node.brain import LLMBrain, MockBrain  # noqa: E402
from swarmworld.server.harness import LAYERS, Harness  # noqa: E402
from swarmworld.server.state import ServerState  # noqa: E402
from swarmworld.server.turns import join, outcome, play  # noqa: E402
from swarmworld.world.packs import LOADED as PACKS  # noqa: E402

BACKOFF = (5, 15, 60)  # seconds before each retry of a failed think; the last repeats
GIVE_UP_S = 600  # after this long failing, the creature idles this turn
NEVER = re.compile(r"gemini|google", re.I)  # Google's terms forbid training on Gemini outputs
TEACHERS = re.compile(r"gpt-oss|qwen", re.I)  # what export_training.py keeps
EPISODE = re.compile(r"^\d{8}-\d{6}-(?P<tag>.+)-s(?P<seed>\d+)$")


def say(*parts) -> None:
    print(*parts, flush=True)  # a night's log is usually a file (nohup): every line as it happens


def parse_seeds(text: str) -> list[int]:
    """'100-139' (inclusive), '5,7,9' or a mix: '100-104,200'."""
    seeds: list[int] = []
    for part in (p.strip() for p in text.split(",")):
        if not part:
            continue
        lo, sep, hi = part.partition("-")
        if sep:
            a, b = int(lo), int(hi)
            if b < a:
                raise ValueError(f"seed range {part} runs backwards")
            seeds += range(a, b + 1)
        else:
            seeds.append(int(part))
    return list(dict.fromkeys(seeds))


def folder_tag(model: str) -> str:
    """The model's short tag, safe as part of a folder name on any machine ("gpt-oss:20b" -> "gpt-oss-20b")."""
    return re.sub(r"[^A-Za-z0-9._-]+", "-", short_tag(model)).strip("-") or "model"


def check_teacher(model: str, base_url: str | None, log=say) -> None:
    if NEVER.search(model) or (base_url and NEVER.search(base_url)):
        raise SystemExit("Gemini (or any Google model) is never a teacher: its terms forbid training other models on "
                         "its outputs.")
    if model != "mock" and not TEACHERS.search(model):
        log(f"  Note: export_training.py keeps only gpt-oss and Qwen teachers; '{model}' decisions won't be exported.")


def git_commit() -> str | None:
    try:
        head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True,
                              check=True).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--untracked-files=no"],
                               capture_output=True, text=True, check=True).stdout.strip()
        return head + ("-dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return None


def prepare(root: Path, tag: str, seeds: list[int], log=say) -> tuple[list[int], list[int]]:
    """Which seeds still need an episode by this model, and which are done. Unfinished episodes of this model on these
    seeds are moved aside (<folder>.partial); everything else in the folder belongs to someone else."""
    mine: dict[int, list[Path]] = {}
    if root.is_dir():
        for p in sorted(root.iterdir()):
            m = EPISODE.match(p.name)
            if p.is_dir() and m and m["tag"] == tag and int(m["seed"]) in seeds:
                mine.setdefault(int(m["seed"]), []).append(p)
    todo, skipped = [], []
    for seed in seeds:
        dirs = mine.get(seed, [])
        if any((d / "done").exists() for d in dirs):
            skipped.append(seed)
            continue
        for d in dirs:
            aside = d.with_name(d.name + ".partial")
            n = 1
            while aside.exists():
                n += 1
                aside = d.with_name(f"{d.name}.partial{n}")
            d.rename(aside)
            log(f"  seed {seed}: unfinished episode moved aside to {aside.name}; starting it over")
        todo.append(seed)
    return todo, skipped


def make_state(seed: int, run_dir: Path) -> ServerState:
    """A fresh practice world: every harness layer for every creature, prompts logged, keyword-only recall (the
    state's embedder stays None: nothing here ever builds one, whatever VOYAGE_API_KEY says)."""
    return ServerState(seed=seed, tick_seconds=0, run_dir=run_dir, harness=Harness(set(LAYERS), set(LAYERS)),
                       log_prompts=True)


async def think_with_retry(brain, job: dict, sleep=asyncio.sleep, clock=time.monotonic, log=say,
                           backoff: tuple[int, ...] = BACKOFF, give_up_s: float = GIVE_UP_S) -> tuple[bool, Any, str | None, dict]:
    """brain.think, retried with backoff until it answers or GIVE_UP_S of failures have passed."""
    t0 = clock()
    tries = 0
    while True:
        ok, output, error, usage = await brain.think(job["messages"], job.get("schema"), int(job["max_tokens"]))
        if ok:
            return ok, output, error, usage
        failing = clock() - t0
        who = job.get("creature") or job.get("kind", "?")
        if failing >= give_up_s:
            error = f"gave up after {failing / 60:.0f} min of failures: {error}"
            log(f"  {time.strftime('%H:%M:%S')} think for {who} {error}; it idles this turn")
            return False, None, error, {}
        wait = backoff[min(tries, len(backoff) - 1)]
        tries += 1
        log(f"  {time.strftime('%H:%M:%S')} think for {who} failed ({error}); retry {tries} in {wait} s")
        await sleep(wait)


async def episode(brain, model: str, seed: int, creatures: int, ticks: int, root: Path, concurrency: int,
                  base_url: str | None, log=say, sleep=asyncio.sleep) -> dict:
    tag = short_tag(model)
    run_dir = root / f"{time.strftime('%Y%m%d-%H%M%S')}-{folder_tag(model)}-s{seed}"
    st = make_state(seed, run_dir)
    meta = {"model": model, "model_tag": tag, "base_url_host": urlparse(base_url).netloc.rpartition("@")[2] if base_url else None,
            "seed": seed, "creatures": creatures, "ticks": ticks, "harness": sorted(LAYERS), "packs": list(PACKS),
            "recall": "keywords only" if st.embedder is None else "embeddings", "inspiration": st.sim.inspiration,
            "temperature": getattr(brain, "temperature", None), "concurrency": concurrency, "git_commit": git_commit(),
            "started": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=1))
    gate = asyncio.Semaphore(max(1, concurrency))

    async def think(job: dict):
        async with gate:
            return await think_with_retry(brain, job, sleep=sleep, log=log)

    t0 = time.monotonic()
    try:
        node = join(st, "teacher", tag, creatures)
        tally = await play(st, node, think, ticks)
    finally:
        st.close()
    r = {"seed": seed, "model": model, "dir": str(run_dir), "minutes": round((time.monotonic() - t0) / 60, 2),
         **outcome(st, tag, tally)}
    r["ok_rate"] = r["success_rate"]
    r["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    tmp = run_dir / "done.tmp"
    tmp.write_text(json.dumps(r, indent=1))
    tmp.rename(run_dir / "done")  # last, and whole: a folder with `done` is a finished episode
    reached = ", ".join(f"{k}@{v}" for k, v in sorted(tally.first.items(), key=lambda kv: kv[1])) or "none"
    log(f"seed {seed}: {r['minutes']:.1f} min, {r['thinks']} thinks, ok {r['ok_rate']:.0%}, milestones {reached}")
    return r


async def night(args: argparse.Namespace, log=say) -> dict:
    model = "mock" if args.mock else args.model
    if not model:
        raise SystemExit("give --model NAME (with --base-url), or --mock")
    base_url = None if args.mock else args.base_url
    check_teacher(model, base_url, log)
    root = Path(args.out)
    root.mkdir(parents=True, exist_ok=True)
    todo, skipped = prepare(root, folder_tag(model), parse_seeds(args.seeds), log)
    where = "the mock brain" if args.mock else f"{model} on {urlparse(base_url).netloc}"
    log(f"Teacher runs with {where}: {len(todo)} episode(s) to run" + (f", {len(skipped)} already done" if skipped else "")
        + f" ({args.creatures} creatures, {args.ticks} ticks each) into {root}")
    done = []
    brain = None if args.mock else LLMBrain(base_url, model, args.api_key or os.environ.get("TEACHER_API_KEY"),
                                            timeout=args.timeout)
    try:
        for seed in todo:
            b = MockBrain(seed) if args.mock else brain
            done.append(await episode(b, model, seed, args.creatures, args.ticks, root,
                                      args.concurrency or args.creatures, base_url, log))
    finally:
        if brain:
            await brain.close()
    if done:
        log(f"Done: {len(done)} episode(s), {sum(r['thinks'] for r in done)} thinks in "
            f"{sum(r['minutes'] for r in done):.0f} min.")
    return {"done": done, "skipped": skipped}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Swarm World teacher runs: turn-based episodes for distillation data")
    ap.add_argument("--base-url", default="http://127.0.0.1:8000/v1", help="OpenAI-compatible server of the teacher")
    ap.add_argument("--model", default=None, help="the teacher (one per run), e.g. gpt-oss:20b")
    ap.add_argument("--api-key", default=None, help="if the server wants one (or set TEACHER_API_KEY)")
    ap.add_argument("--seeds", default="100-139", help="one episode per seed: a range '100-139' or a list '1,5,9'")
    ap.add_argument("--creatures", type=int, default=6)
    ap.add_argument("--ticks", type=int, default=2400, help="world ticks per episode (a day is 1200)")
    ap.add_argument("--out", default="runs/teacher")
    ap.add_argument("--concurrency", type=int, default=None, help="thinks in flight per turn (default: --creatures)")
    ap.add_argument("--timeout", type=float, default=180.0, help="seconds before one request counts as failed")
    ap.add_argument("--mock", action="store_true", help="the rule-based mock brain (tests and plumbing checks)")
    args = ap.parse_args(argv)
    if not 1 <= args.creatures <= 60:
        ap.error("--creatures must be 1 to 60 (one brain node's limit)")
    try:
        parse_seeds(args.seeds)
    except ValueError as exc:
        ap.error(f"--seeds: {exc}")
    return args


async def stoppable(args: argparse.Namespace) -> dict:
    """The night, stopped by SIGTERM (kill) as cleanly as by Ctrl-C: the episode in progress closes its logs."""
    task = asyncio.current_task()
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, task.cancel)
    return await night(args)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    try:
        asyncio.run(stoppable(args))
    except (KeyboardInterrupt, asyncio.CancelledError):
        say("\nStopped. The episode in progress has no `done` marker: the next start moves it aside and redoes it.")
        sys.exit(130)


if __name__ == "__main__":
    main()
