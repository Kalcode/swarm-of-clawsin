"""DAgger labels: the teacher answers the student's own situations.

    uv run python scripts/dagger_label.py runs/20261103-104243 runs/20261104-090000 \\
        --base-url http://192.168.50.42:11434/v1 --model gpt-oss:20b --out runs/dagger-r2 --failures-first --limit 6000

Reads live run folders (thinks.jsonl with the full prompt in `messages`), picks the student's act decisions (model
starts with --student-prefix), failures first (the action failed, was a no-op, or the think failed), then the rest
shuffled with a fixed seed. --limit applies, then identical prompts are deduped. The teacher is asked the exact same
messages through the node's own LLMBrain, with the schema the live brain sent (the plan one when the run had the
plan layer). Each answer is written as a teacher-episode-shaped folder, <out>/<source run>-dagger/, which
scripts/export_training.py takes as teacher decisions (weight 1, never validation).

LICENSING. Gemini outputs must never enter training (Google's terms). So only runs whose folder name (a timestamp) is
>= --since-run (default 20261103-104243, the fresh world with no Gemini mind) are read, and a run with any row (any
kind, any creature) whose model matches /gemini/i is refused. Both refusals exit 1 before any request is made."""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from swarmworld.mind.prompts import INTENTION_SCHEMA, INTENTION_SCHEMA_PLAN  # noqa: E402
from swarmworld.node.brain import LLMBrain  # noqa: E402
from swarmworld.server.state import ACT_TOKENS, ACT_TOKENS_PLAN  # noqa: E402

DEFAULT_SINCE = "20261103-104243"
GEMINI = re.compile(r"gemini|google", re.I)
STAMP = re.compile(r"^\d{8}-\d{6}$")
RETRIES = 2


def fail(msg: str) -> "SystemExit":
    print(f"Refused: {msg}", file=sys.stderr)
    return SystemExit(1)


def thinks_of(run: Path) -> list[dict]:
    path = run / "thinks.jsonl"
    if not path.exists():
        raise fail(f"{run} has no thinks.jsonl")
    rows = []
    for line in path.read_text().splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:  # a line cut off when the world stopped
            continue
    return rows


def check_runs(runs: list[Path], since_run: str) -> None:
    """Exit 1 (with a message) for a run older than since_run, or holding Gemini/Google anywhere in its raw text."""
    if since_run < DEFAULT_SINCE:
        raise fail(f"--since-run {since_run} is below the floor {DEFAULT_SINCE}: the floor is the licensing guarantee")
    for run in runs:
        if not STAMP.match(run.name) or run.name < since_run:
            raise fail(f"{run} is older than --since-run {since_run} (or not a live run folder): it may hold Gemini "
                       "outputs, which must never enter training")
        raw = (run / "thinks.jsonl").read_text(errors="replace") if (run / "thinks.jsonl").exists() else ""
        hit = GEMINI.search(raw)  # the raw text, before any parsing: cut-off lines and prompt words count too
        if hit:
            raise fail(f"{run} mentions {hit.group(0)!r} in thinks.jsonl: Gemini outputs must never enter training")


def is_failure(r: dict) -> bool:
    res = r.get("result")
    return not r.get("ok") or not res or not res.get("ok") or bool(res.get("noop"))


def pick(runs: list[Path], prefix: str, failures_first: bool, limit: int | None, seed: int = 0) -> tuple[list[dict], int]:
    """The student's act rows with a prompt: (rows, how many of them are failures), each row tagged with its "run"."""
    rows = []
    for run in runs:
        for r in thinks_of(run):
            if (r.get("kind") == "act" and str(r.get("model") or "").startswith(prefix)
                    and isinstance(r.get("messages"), list) and len(r["messages"]) == 2):
                rows.append({**r, "run": run.name})
    bad = [r for r in rows if is_failure(r)] if failures_first else []
    rest = [r for r in rows if not (failures_first and is_failure(r))]
    random.Random(seed).shuffle(rest)
    chosen = (bad + rest)[:limit]
    seen, out = set(), []
    for r in chosen:
        key = json.dumps(r["messages"], sort_keys=True)
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out, sum(1 for r in out if r in bad)


def prompt_key(r: dict) -> str:
    return json.dumps(r["messages"], sort_keys=True)


def existing_rows(ep: Path) -> list[dict]:
    path = ep / "thinks.jsonl"
    rows = []
    for line in path.read_text().splitlines() if path.exists() else []:
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


async def ask(brain: LLMBrain, r: dict) -> dict | None:
    plan = "plan" in (r.get("harness") or [])
    schema, tokens = (INTENTION_SCHEMA_PLAN, ACT_TOKENS_PLAN) if plan else (INTENTION_SCHEMA, ACT_TOKENS)
    for _ in range(1 + RETRIES):
        ok, output, _err, _usage = await brain.think(r["messages"], schema, tokens)
        if ok and isinstance(output, dict) and output.get("action"):
            return output
    return None


async def run_labeling(runs: list[Path], base_url: str, model: str, out: Path, student_prefix: str = "swarm-student",
                       since_run: str = DEFAULT_SINCE, failures_first: bool = False, limit: int | None = None,
                       concurrency: int = 8, api_key: str | None = None, temperature: float = 0.4, resume: bool = False, log=print) -> dict:
    if GEMINI.search(model) or GEMINI.search(base_url):
        raise fail("Gemini (or any Google model) is never a teacher: its terms forbid training other models on its outputs")
    check_runs(runs, since_run)
    t0 = time.monotonic()
    picked, n_fail = pick(runs, student_prefix, failures_first, limit)
    log(f"Picked {len(picked)} decisions ({n_fail} failures-first) from {len(runs)} run(s)")
    eps = {run.name: out / f"{run.name}-dagger" for run in runs}
    counts: dict[str, int] = {}
    have: set[str] = set()
    for name, ep in eps.items():
        if (ep / "done").exists() and resume:
            raise fail(f"{ep} is already complete (has done)")
        rows = existing_rows(ep) if resume else []
        if resume and (ep / "thinks.jsonl").exists():  # drop a line cut off by the crash
            (ep / "thinks.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows))
        counts[name] = len(rows)
        have |= {prompt_key(x) for x in rows}
    todo = [r for r in picked if prompt_key(r) not in have]
    if len(todo) < len(picked):
        log(f"Resuming: {len(picked) - len(todo)} already labelled, {len(todo)} to go")
    brain = LLMBrain(base_url, model, api_key, timeout=180.0, temperature=temperature)
    sem = asyncio.Semaphore(max(1, concurrency))
    done = 0
    failed = 0
    out.mkdir(parents=True, exist_ok=True)

    async def one(r: dict) -> None:
        nonlocal done, failed
        async with sem:
            a = await ask(brain, r)
        if a is None:
            failed += 1
        else:
            ep = eps[r["run"]]
            ep.mkdir(exist_ok=True)
            row = {"tick": r.get("tick"), "creature": r.get("creature"), "name": r.get("name"), "model": model,
                   "kind": "act", "ok": True, "output": a, "messages": r["messages"], "harness": r.get("harness") or [],
                   "result": {"ok": True, "noop": False, "message": "dagger label"}}
            with open(ep / "thinks.jsonl", "a") as fh:  # one line per label as it completes
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                fh.flush()
            counts[r["run"]] += 1
        done += 1
        if done % 100 == 0:
            log(f"  {done}/{len(todo)} labelled")

    tasks = [asyncio.ensure_future(one(r)) for r in todo]
    try:
        await asyncio.gather(*tasks)
    finally:
        for t in tasks:  # a crash stops the rest at once; what was written stays for --resume
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await brain.close()
    for name, ep in eps.items():
        if counts[name]:
            (ep / "meta.json").write_text(json.dumps({"model": model, "dagger": True, "source_runs": [name],
                                                      "labelled": counts[name]}))
            (ep / "done").write_text("{}")
    labeled = sum(counts.values())
    s = {"picked": len(picked), "labeled": labeled, "skipped": failed, "failures_first": n_fail,
         "seconds": round(time.monotonic() - t0, 1)}
    log(f"Summary: picked {s['picked']}, labeled {s['labeled']}, skipped {s['skipped']} (failed after {RETRIES} retries), "
        f"failures-first {s['failures_first']}, {s['seconds']} seconds. Written to {out}")
    return s


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="DAgger: the teacher labels the student's own situations")
    ap.add_argument("runs", nargs="+", help="live run folders (runs/<timestamp>)")
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--model", required=True, help="the teacher, e.g. gpt-oss:20b")
    ap.add_argument("--out", required=True, help="e.g. runs/dagger-r2")
    ap.add_argument("--since-run", default=DEFAULT_SINCE, help="refuse runs older than this folder name")
    ap.add_argument("--student-prefix", default="swarm-student")
    ap.add_argument("--failures-first", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--temperature", type=float, default=0.4, help="teacher temperature for labels (0.4: its preferred move)")
    ap.add_argument("--api-key", default=None)
    ap.add_argument("--resume", action="store_true", help="continue an unfinished --out (folders without done)")
    a = ap.parse_args(argv)
    out = Path(a.out)
    if out.exists() and any(out.iterdir()) and not a.resume:
        raise fail(f"{out} exists and is not empty (--resume continues an unfinished one)")
    asyncio.run(run_labeling([Path(r) for r in a.runs], a.base_url, a.model, out, a.student_prefix, a.since_run,
                             a.failures_first, a.limit, a.concurrency, a.api_key, a.temperature, a.resume))


if __name__ == "__main__":
    main()
