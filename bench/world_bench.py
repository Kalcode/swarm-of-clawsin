"""The world as a benchmark: run the same small scenario for each model, turn-based so speed doesn't matter.

Each episode is a fresh world (fixed seed) with N creatures driven by one model. The clock only advances
when every waiting creature has answered, so a fast model gets no extra turns. It reuses the exact server
code paths (prompts, parsing, actions, memory, learning) the live world uses.

    uv run python bench/world_bench.py --model gemma-4-e4b-it-4bit --model Qwen3.5-4B-MLX-4bit --episodes 2
    uv run python bench/world_bench.py --mock --episodes 3          # plumbing check, no model needed
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from swarmworld.node.__main__ import short_tag  # noqa: E402
from swarmworld.node.brain import LLMBrain, MockBrain  # noqa: E402
from swarmworld.server.state import ServerState  # noqa: E402
from swarmworld.server.turns import MILESTONES, join, outcome, play  # noqa: E402


async def episode(model: str, brain, seed: int, creatures: int, ticks: int, slots: int) -> dict:
    st = ServerState(seed=seed, tick_seconds=0)
    tag = short_tag(model)
    node = join(st, "bench", tag, creatures, slots)
    t0 = time.time()
    tally = await play(st, node, lambda j: brain.think(j["messages"], j.get("schema"), j["max_tokens"]), ticks)
    return {"model": model, "seed": seed, **outcome(st, tag, tally), "wall_s": round(time.time() - t0, 1)}


def summarize(results: list[dict], ticks: int) -> str:
    by_model: dict[str, list[dict]] = {}
    for r in results:
        by_model.setdefault(r["model"], []).append(r)
    head = (["model", "episodes", "thinks", "success", "no-op", "parse fail", "learned", "speech", "crafted", "inventions", "collapses"]
            + [f"{m} @tick" for m in MILESTONES])
    rows = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for model, rs in by_model.items():
        def avg(k):
            return statistics.mean(r[k] for r in rs)

        def reached(ms):
            got = [r["first"][ms] for r in rs if ms in r["first"]]
            return f"{len(got)}/{len(rs)}" + (f" ~{int(statistics.mean(got))}" if got else "")

        rows.append("| " + " | ".join([model, str(len(rs)), f"{avg('thinks'):.0f}", f"{avg('success_rate'):.0%}",
                                        f"{avg('noop_rate'):.0%}", f"{avg('parse_failures'):.1f}", f"{avg('learned'):.1f}",
                                        f"{avg('speech'):.0f}", f"{avg('crafted'):.0f}", f"{avg('inventions'):.1f}",
                                        f"{avg('collapses'):.1f}"] + [reached(ms) for ms in MILESTONES]) + " |")
    return (f"Turn-based episodes of {ticks} ticks. Milestones: how many episodes reached it, and the average tick when they did.\n\n"
            + "\n".join(rows))


async def main() -> None:
    ap = argparse.ArgumentParser(description="Swarm World benchmark: same scenario, every model, turn-based")
    ap.add_argument("--model", action="append", default=[])
    ap.add_argument("--mock", action="store_true", help="benchmark the rule-based mock brain (plumbing check)")
    ap.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    ap.add_argument("--episodes", type=int, default=2)
    ap.add_argument("--creatures", type=int, default=4)
    ap.add_argument("--ticks", type=int, default=600, help="world ticks per episode (a day is 1200)")
    ap.add_argument("--slots", type=int, default=8)
    ap.add_argument("--seed", type=int, default=100)
    ap.add_argument("--out", default="bench/results")
    args = ap.parse_args()
    models = [("mock", MockBrain(1))] if args.mock else [(m, LLMBrain(args.base_url, m)) for m in args.model]
    if not models:
        sys.exit("give --model NAME (repeatable) or --mock")
    results = []
    for model, brain in models:
        for ep in range(args.episodes):
            r = await episode(model, brain, args.seed + ep, args.creatures, args.ticks, args.slots)
            results.append(r)
            print(f"  {model} episode {ep + 1}: thinks {r['thinks']}, success {r['success_rate']:.0%}, no-op {r['noop_rate']:.0%}, "
                  f"milestones {r['first']}, learned {r['learned']}, {r['wall_s']}s", flush=True)
        await brain.close()
    table = summarize(results, args.ticks)
    print("\n" + table)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"world_bench-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps({"args": vars(args), "results": results, "table": table}, indent=1))
    print(f"\nsaved {path}")


if __name__ == "__main__":
    asyncio.run(main())
