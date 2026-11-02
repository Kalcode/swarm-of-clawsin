"""Review a world's behavior from its run logs: where minds fail, stall, starve, or want things the world lacks.

    uv run python scripts/review_world.py runs/20261102-082718              # one run
    uv run python scripts/review_world.py --since 20261101-210224 --until 20261102-074900   # a span of runs
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

NOOP = re.compile(r"already beside|You wait and watch|nothing comes of it|has nothing left|You rest for a while")
WANTS = [  # failure text -> what the creature wanted that the world didn't have or understand
    (re.compile(r"don't know of anything called '([^']+)'"), "unknown thing"),
    (re.compile(r"never heard of a '([^']+)'"), "unknown thing to craft"),
    (re.compile(r"No one has ever made a '([^']+)'"), "dreamed-of thing"),
    (re.compile(r"don't see any '([^']+)'"), "thing not in sight"),
    (re.compile(r"won't burn|won't grow|can't eat ([a-z ]+)"), "impossible use"),
]
GENERIC_NAMES = re.compile(r"^(new |an? )?(invention|device|thing|item|tool|creation)( \d+)?$")


def load(dirs: list[Path]):
    events, thinks = [], []
    for d in dirs:
        if (d / "events.jsonl").exists():
            events += [json.loads(l) for l in (d / "events.jsonl").open()]
        if (d / "thinks.jsonl").exists():
            thinks += [json.loads(l) for l in (d / "thinks.jsonl").open()]
    return events, thinks


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="*")
    ap.add_argument("--since")
    ap.add_argument("--until")
    a = ap.parse_args()
    dirs = [Path(r) for r in a.runs] or [p for p in sorted(Path("runs").glob("2*"))
                                         if (not a.since or p.name >= a.since) and (not a.until or p.name <= a.until)]
    events, thinks = load(dirs)
    model_of = {t["name"]: t["model"] for t in thinks}
    print(f"# Review of {len(dirs)} run(s): {dirs[0].name} .. {dirs[-1].name}\n")
    print(f"{len(thinks)} model replies, {len(events)} world events\n")

    # 1. how each model spends its turns, and how often a turn achieves nothing
    acts: dict[str, Counter] = defaultdict(Counter)
    unparsed: Counter = Counter()
    streaks: Counter = Counter()
    last: dict[str, tuple] = {}
    run_len: dict[str, int] = defaultdict(int)
    for t in thinks:
        if t["kind"] != "act":
            continue
        o = t.get("output")
        if not isinstance(o, dict) or not o.get("action"):
            unparsed[t["model"]] += 1
            continue
        acts[t["model"]][o["action"]] += 1
        key = (o["action"], str(o.get("target", "")).lower())
        run_len[t["name"]] = run_len[t["name"]] + 1 if last.get(t["name"]) == key else 1
        last[t["name"]] = key
        if run_len[t["name"]] == 4:
            streaks[t["model"]] += 1
    fails: dict[str, Counter] = defaultdict(Counter)
    fail_examples: dict[tuple, str] = {}
    noops: Counter = Counter()
    collapses: Counter = Counter()
    wants: Counter = Counter()
    wants_by_kind: dict[str, Counter] = defaultdict(Counter)
    for e in events:
        actor = e["text"].split(" ", 1)[0]
        m = model_of.get(actor, "?")
        if e["kind"] == "collapse":
            collapses[m] += 1
        if e["kind"] != "fail":
            continue
        msg = e["text"].split(": ", 1)[-1]
        if NOOP.search(msg):
            noops[m] += 1
        key = re.sub(r"'[^']*'|\d+|\b[A-Z][a-z]+\b", "X", msg)[:70]
        fails[m][key] += 1
        fail_examples.setdefault((m, key), e["text"][:170])
        for rx, kind in WANTS:
            hit = rx.search(msg)
            if hit:
                thing = (hit.group(1) if hit.groups() and hit.group(1) else msg)[:40].lower().strip()
                wants[thing] += 1
                wants_by_kind[kind][thing] += 1

    print("## How each model spends its turns\n")
    for m, c in sorted(acts.items()):
        total = sum(c.values()) or 1
        top = ", ".join(f"{k} {100 * v / total:.0f}%" for k, v in c.most_common(9))
        print(f"- **{m}** ({total} actions, {unparsed[m]} unparsed, {streaks[m]} streaks of 4+ identical actions, "
              f"{collapses[m]} collapses): {top}")
    print("\n## Most common failures per model\n")
    for m, c in sorted(fails.items()):
        total = sum(c.values())
        print(f"**{m}**: {total} failures")
        for key, n in c.most_common(8):
            print(f"  - {n}x  {fail_examples[(m, key)]}")
        print()
    print("## Unmet desires (things they reached for that the world doesn't have or understand)\n")
    for kind, c in wants_by_kind.items():
        print(f"- **{kind}**: " + ", ".join(f"{t} ({n})" for t, n in c.most_common(15)))
    print("\n## Inventions\n")
    invs = [e for e in events if e["kind"] == "invent"]
    generic = [e for e in invs if GENERIC_NAMES.match(e["text"].split("invented the ", 1)[-1].split("!", 1)[0].strip())]
    print(f"{len(invs)} inventions, {len(generic)} with generic names; by model: "
          + ", ".join(f"{m} {n}" for m, n in Counter(model_of.get(e['text'].split(' ', 1)[0], '?') for e in invs).items()))
    print("\n## Terminals\n")
    progs = [e for e in events if e["kind"] == "program"]
    print(f"{len(progs)} programs written" + (": " + " | ".join(p["text"].split(":", 1)[-1].strip()[:60] for p in progs[:8]) if progs else ""))


if __name__ == "__main__":
    main()
