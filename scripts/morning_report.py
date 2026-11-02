"""Write a readable report of what happened in the world: chronicle, firsts, society, places, models.

    uv run python scripts/morning_report.py                       # prints Markdown
    uv run python scripts/morning_report.py -o docs/overnight-report.md --since "2026-11-01 21:00"
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from collections import Counter
from pathlib import Path

BASE = "http://127.0.0.1:7777"


def get(path: str):
    with urllib.request.urlopen(BASE + path, timeout=10) as r:
        return json.loads(r.read())


def run_dirs_since(since: float) -> list[Path]:
    out = []
    for p in sorted(Path("runs").glob("2*")):
        try:
            started = time.mktime(time.strptime(p.name, "%Y%m%d-%H%M%S"))
        except ValueError:
            continue
        if started >= since - 1:
            out.append(p)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out")
    ap.add_argument("--since", help='local time, e.g. "2026-11-01 21:00" (default: the last 12 hours)')
    args = ap.parse_args()
    since = time.mktime(time.strptime(args.since, "%Y-%m-%d %H:%M")) if args.since else time.time() - 12 * 3600

    state, metrics, chronicle = get("/api/state"), get("/api/metrics"), get("/api/chronicle")
    society, inventions = get("/api/society"), get("/api/inventions")
    events = []
    for d in run_dirs_since(since):
        if (d / "events.jsonl").exists():
            events += [json.loads(l) for l in (d / "events.jsonl").open()]
    names = {c["id"]: c["name"] for c in state["creatures"]}

    lines: list[str] = []
    clock = state["clock"]
    lines.append("# Swarm World: what happened\n")
    lines.append(f"Report written {time.strftime('%Y-%m-%d %H:%M')}. The world is on **day {clock['day']}** ({clock['phase']}, tick {state['tick']}), "
                 f"with {len(state['creatures'])} creatures. In the window covered: {len(events)} events and "
                 f"{sum(1 for e in events if e['kind'] == 'say')} things said.\n")

    try:
        history = get("/api/history")
    except Exception:
        history = []
    if len(history) >= 2:
        a, b = history[0], history[-1]
        lines.append("## Growth\n")
        lines.append(f"From day {a['day']} to day {b['day']}: knowledge in the society (recipes known, summed over creatures) went from "
                     f"**{a['world']['recipes_known']} to {b['world']['recipes_known']}**, structures from {a['world']['structures']} to "
                     f"{b['world']['structures']}, camps from {a['world']['camps']} to {b['world']['camps']}, and relationships "
                     f"from {a['world']['ties']} to {b['world']['ties']}.\n")

    lines.append("## The Chronicle\n")
    if chronicle:
        for ch in chronicle:
            lines.append(f"**Day {ch['day']}, {ch['phase']}.** {ch['text']}\n")
    else:
        lines.append("No chapters yet.\n")

    lines.append("## Firsts\n")
    inv_by_name = {i["name"]: i for i in inventions}
    for d in sorted(metrics["discoveries"], key=lambda d: d["tick"]):
        if d.get("invented") and d["item"] in inv_by_name:
            i = inv_by_name[d["item"]]
            kind = "food" if i.get("food") else "tool" if i.get("tool") else ", ".join(i.get("effects") or []) or "structure"
            lines.append(f"- tick {d['tick']}: **{d['by']}** invented the **{d['item']}** ({kind}): \"{i['desc']}\" [{d.get('model')}]")
        else:
            lines.append(f"- tick {d['tick']}: **{d['by']}** first made **{d['item']}** [{d.get('model')}]")
    if not metrics["discoveries"]:
        lines.append("- none yet")
    lines.append("")

    learns = [e for e in events if e["kind"] == "learn"]
    if learns:
        how = Counter(e["text"].split(" by ")[-1].split(" ")[0] for e in learns)
        lines.append(f"## Culture\n\n{len(learns)} recipes passed from one creature to another "
                     f"({', '.join(f'{n} by {k}' for k, n in how.most_common())}). The latest:\n")
        lines += [f"- {e['text']}" for e in learns[-6:]]
        lines.append("")
    writes = [e for e in events if e["kind"] == "write"]
    if writes:
        lines.append("Words left in the world:\n")
        lines += [f"- {e['text'][:200]}" for e in writes[-8:]]
        lines.append("")
    programs = [e for e in events if e["kind"] == "program"]
    lines.append("## Terminals\n")
    lines += ([f"- {e['text'][:300]}" for e in programs] or ["- No creature has programmed a terminal yet."])
    lines.append("")

    lines.append("## Society\n")
    edges = society["edges"][:8]
    if edges:
        lines.append("Strongest ties:\n")
        for e in edges:
            bits = [f"{e[k]} {k}{'s' if e[k] != 1 else ''}" for k in ("talk", "gift", "teach") if e[k]]
            lines.append(f"- {names.get(e['a'], e['a'])} and {names.get(e['b'], e['b'])}: {', '.join(bits)}")
        lines.append("")
    if society["hubs"]:
        lines.append("Most connected: " + ", ".join(h["name"] for h in society["hubs"]) + ".")
    if society["loners"]:
        lines.append("Loners: " + ", ".join(society["loners"]) + ".")
    places = [lm["name"] for lm in state.get("landmarks", []) if lm["kind"] == "camp"]
    lines.append("\nCamps: " + (", ".join(places) if places else "none yet") + ".\n")

    lines.append("## The minds, compared\n")
    cols = ["creatures", "thinks", "success_rate", "crafted", "discoveries", "inventions", "built", "writing", "speech", "collapses"]
    lines.append("| model | " + " | ".join(cols) + " |")
    lines.append("|---|" + "---|" * len(cols))
    for m, v in metrics["models"].items():
        lines.append(f"| {m} | " + " | ".join(str(v.get(c, "")) for c in cols) + " |")
    lines.append("")

    benches = sorted(Path("bench/results").glob("world_bench-*.json"))
    if benches:
        latest = json.loads(benches[-1].read_text())
        if not latest["args"].get("mock"):
            lines.append("## Turn-based benchmark (latest run)\n")
            lines.append(latest["table"] + "\n")

    quotes = [e for e in events if e["kind"] == "say" and len(e["text"]) > 60]
    if quotes:
        lines.append("## Overheard\n")
        step = max(1, len(quotes) // 8)
        lines += [f"- {e['text'][:220]}" for e in quotes[::step][:8]]
        lines.append("")

    md = "\n".join(lines)
    if args.out:
        Path(args.out).write_text(md)
        print(f"wrote {args.out}")
    else:
        print(md)


if __name__ == "__main__":
    main()
