"""Per-model and per-creature counters: the world as a living benchmark."""

from __future__ import annotations

import time
from collections import Counter, defaultdict, deque

from ..world.model import World


class Metrics:
    def __init__(self) -> None:
        self.models: dict[str, Counter] = defaultdict(Counter)
        self.items: dict[str, set] = defaultdict(set)
        self.retired: dict[str, Counter] = defaultdict(Counter)  # what creatures did under minds they've since lost
        self.think_stamps: deque[float] = deque()

    def think(self, model: str, latency_ms: int, tokens_in: int, tokens_out: int, ok: bool) -> None:
        m = self.models[model]
        m["thinks"] += 1
        m["latency_ms_total"] += max(0, latency_ms)
        m["tokens_in"] += tokens_in or 0
        m["tokens_out"] += tokens_out or 0
        if not ok:
            m["errors"] += 1
        now = time.time()
        self.think_stamps.append(now)
        while self.think_stamps and now - self.think_stamps[0] > 60:
            self.think_stamps.popleft()

    def bump(self, model: str, key: str, n: int = 1) -> None:
        self.models[model][key] += n

    def retire(self, model: str, stats: Counter) -> None:
        self.retired[model].update(stats)

    def item(self, model: str, item: str) -> None:
        self.items[model].add(item)

    def snapshot(self, world: World, started: float) -> dict:
        by_model: dict[str, dict] = {}
        creature_stats: dict[str, Counter] = defaultdict(Counter)
        for c in world.creatures.values():
            s = creature_stats[c.model]
            s["creatures"] += 1
            s["awake"] += 0 if c.asleep else 1
            for k in ("speech", "discoveries", "crafted", "collapses", "built", "gathered", "programs", "writing",
                      "inventions", "tamed", "planted"):
                s[k] += c.stats.get(k, 0) - c.stats_base.get(k, 0)
        for model, r in self.retired.items():
            for k, n in r.items():
                creature_stats[model][k] += n
        for model in set(self.models) | set(creature_stats):
            m = self.models[model]
            s = creature_stats[model]
            acts = m["act_ok"] + m["act_fail"]
            by_model[model] = {
                "creatures": s["creatures"],
                "awake": s["awake"],
                "thinks": m["thinks"],
                "avg_latency_s": round(m["latency_ms_total"] / m["thinks"] / 1000, 1) if m["thinks"] else 0,
                "success_rate": round(m["act_ok"] / acts, 2) if acts else 0,
                "noop_rate": round(m["noops"] / acts, 2) if acts else 0,
                "parse_failures": m["parse_failures"],
                "errors": m["errors"],
                "loops": m["loops"],
                "tokens_out": m["tokens_out"],
                "cache_hit": round(m["cached_tokens"] / m["tokens_in"], 2) if m["tokens_in"] else 0,
                "unique_items": len(self.items[model]),
                "discoveries": s["discoveries"],
                "crafted": s["crafted"],
                "gathered": s["gathered"],
                "built": s["built"],
                "speech": s["speech"],
                "writing": s["writing"],
                "programs": s["programs"],
                "inventions": s["inventions"],
                "tamed": s["tamed"],
                "planted": s["planted"],
                "collapses": s["collapses"],
            }
        discoveries = sorted(world.discoveries.values(), key=lambda d: d["tick"])
        return {
            "type": "metrics",
            "tick": world.tick,
            "uptime_s": int(time.time() - started),
            "thinks_per_min": len(self.think_stamps),
            "models": by_model,
            "discoveries": [{"item": world.catalog.name(d["item"]), "by": d["by"], "model": d.get("model"), "tick": d["tick"],
                             "invented": bool(d.get("invented"))} for d in discoveries],
        }
