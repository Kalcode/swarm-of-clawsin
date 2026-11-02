"""Summarize a Swarm World run: how each model's creatures behaved.

    uv run python scripts/analyze_run.py                 # latest run in runs/
    uv run python scripts/analyze_run.py runs/20261101-180627 runs/20261101-183218   # several runs together
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


def load(paths: list[Path]) -> tuple[list[dict], list[dict]]:
    events, thinks = [], []
    for p in paths:
        if (p / "events.jsonl").exists():
            events += [json.loads(l) for l in (p / "events.jsonl").open()]
        if (p / "thinks.jsonl").exists():
            thinks += [json.loads(l) for l in (p / "thinks.jsonl").open()]
    return events, thinks


def main() -> None:
    runs = [Path(a) for a in sys.argv[1:]] or sorted(Path("runs").glob("2*"))[-1:]
    events, thinks = load(runs)
    if not thinks:
        sys.exit("no thinks.jsonl found")
    model_of = {t["name"]: t["model"] for t in thinks}

    actions: dict[str, Counter] = defaultdict(Counter)
    latency: dict[str, list[int]] = defaultdict(list)
    names: dict[str, set] = defaultdict(set)
    for t in thinks:
        m = t["model"]
        names[m].add(t["name"])
        if t.get("latency_ms"):
            latency[m].append(t["latency_ms"])
        o = t.get("output")
        if t["kind"] == "act":
            actions[m][o.get("action") if isinstance(o, dict) else "(unparsed)"] += 1

    outcomes: dict[str, Counter] = defaultdict(Counter)
    for e in events:
        actor = e["text"].split(" ", 1)[0]
        m = model_of.get(actor)
        if m:
            outcomes[m][e["kind"]] += 1

    print(f"Runs: {', '.join(str(r) for r in runs)}   thinks: {len(thinks)}   events: {len(events)}\n")
    cols = ["gather", "craft", "discover", "invent", "learn", "place", "plant", "tame", "write", "store", "tend", "program", "say", "fail", "collapse"]
    print(f"{'model':<14}{'creatures':>10}{'thinks':>8}{'lat s':>7}" + "".join(f"{c:>9}" for c in cols))
    for m in sorted(names):
        lat = sum(latency[m]) / len(latency[m]) / 1000 if latency[m] else 0
        n_th = sum(actions[m].values())
        print(f"{m:<14}{len(names[m]):>10}{n_th:>8}{lat:>7.1f}" + "".join(f"{outcomes[m][c]:>9}" for c in cols))

    print("\nHow each model spends its thoughts (% of actions):")
    for m in sorted(names):
        total = sum(actions[m].values()) or 1
        top = ", ".join(f"{a} {100 * n / total:.0f}%" for a, n in actions[m].most_common(8))
        print(f"  {m}: {top}")

    print("\nDiscoveries and inventions:")
    for e in events:
        if e["kind"] in ("discover", "invent"):
            actor = e["text"].split(" ", 1)[0]
            print(f"  tick {e['tick']:>6}  {e['text'][:110]}  [{model_of.get(actor, '?')}]")

    speech = [e for e in events if e["kind"] == "say"]
    if speech:
        print("\nLongest things said:")
        for e in sorted(speech, key=lambda e: -len(e["text"]))[:5]:
            print(f"  {e['text'][:200]}")


if __name__ == "__main__":
    main()
