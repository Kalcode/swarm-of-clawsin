"""Server state: the world, the simulation, connected brain nodes, and job dispatch."""

from __future__ import annotations

import json
import random
import re
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from pathlib import Path

from aiohttp import web

from ..mind.memory import Memory
from ..mind.prompts import (INTENTION_SCHEMA, INTENTION_SCHEMA_PLAN, build_act_messages, build_reflect_messages,
                            curated_recent, make_persona, recent_limit, tip_limit)
from ..mind.recall import RecallIndex
from ..mind.techniques import TECHNIQUES, lore, relevant
from ..world.actions import ActionResult, apply_intention, parse_intention
from ..world.model import Creature
from ..world.perception import direction, dist, perceive, spot_name, visible_creatures, visible_objects
from ..world.simulation import Simulation
from ..world.terrain import generate_world
from .harness import Harness
from .metrics import Metrics
from .wishes import Wishes

AUTO_RECALL = 3
AUTO_LINE = 140
HUNGRY = 40
RECALL_ASKED = 5
RECALL_LINE = 160
MIN_GAP_TICKS = 4
CHRONICLE_EVERY = 600
HISTORY_EVERY = 60
HISTORY_MAX = 3000  # ticks (5 minutes of world time)
JOB_TIMEOUT_S = 90
MAX_PER_NODE = 60
MAX_CREATURES = 200
HISTORY_STATS = ("crafted", "discoveries", "inventions", "speech", "built", "gathered", "writing", "collapses", "stored",
                 "tended_fire")
LEARN_STATS = ("learned_by_watching", "learned_by_listening", "learned_by_reading")
PALETTE = ["#f2c14e", "#5bc0eb", "#9bc53d", "#fa7921", "#e55934", "#c879ff", "#4ecdc4", "#ff6b9d", "#f7f7f7"]
WAKE_PRIORITY = {"heard": 0, "hungry": 1, "woke": 2, "result": 2, "met": 3, "idle": 4}
SAYS_RE = re.compile(r'^(\w+) says(?: to (?:you|\w+))?: "(.*)"$')
GAVE_RE = re.compile(r"^(\w+) gave you (.*)\.$")


@dataclass
class Node:
    id: str
    name: str
    ws: web.WebSocketResponse
    slots: int
    models: list[dict]
    hardware: dict
    inflight: dict[str, str] = field(default_factory=dict)
    joined: float = field(default_factory=time.time)


@dataclass
class Job:
    id: str
    creature: str
    node: str
    kind: str
    model: str
    sent: float
    wake_reason: str | None
    shown: list[str] = field(default_factory=list)  # techniques disclosed in this act's prompt
    recalled: list[str] = field(default_factory=list)  # "kind: first 60 chars" of the lines recalled for it


class ServerState:
    def __init__(self, seed: int = 7, token: str | None = None, tick_seconds: float = 0.5, run_dir: Path | None = None,
                 harness: Harness | None = None):
        self.world = generate_world(seed)
        self.harness = harness or Harness()
        self.memories: dict[str, Memory] = {}
        self.recall = RecallIndex()
        self.load_lore()
        self.embedder = None  # a recall.VoyageEmbedder (or anything with async embed) when embeddings are on
        try:
            from ..scripting.terminal import run_terminal
        except ImportError:  # sandbox unavailable: terminals stay inert
            run_terminal = None
        self.sim = Simulation(self.world, memory_sink=self._remember, terminal_runner=run_terminal)
        self.sim.on_result = self._on_activity_result
        self.world.recall_hook = self._recall_hook
        self.token = token
        self.tick_seconds = tick_seconds
        self.nodes: dict[str, Node] = {}
        self.owner: dict[str, str] = {}
        self.jobs: dict[str, Job] = {}
        self.metrics = Metrics()
        self.viewers: set[web.WebSocketResponse] = set()
        self.last: dict[str, dict] = {}
        self.recent_acts: dict[str, deque] = {}
        self.model_colors: dict[str, str] = {}
        self.rng = random.Random(seed + 99)
        self.started = time.time()
        self._job_seq = 0
        self.run_dir = run_dir
        self.world_path: Path | None = None
        self.relations: dict[str, Counter] = {}
        self.history: list[dict] = []  # a snapshot every HISTORY_EVERY ticks, for charts  # "a|b" (sorted ids) -> counts of talk, gift, teach
        self.chronicle: list[dict] = []
        self.wishes = Wishes(self.world.catalog)
        self.chronicle_due = self.world.tick + CHRONICLE_EVERY
        self.chronicle_from = self.world.tick
        self.chronicle_inflight = False
        self._events_fh = None
        self._thinks_fh = None
        if run_dir:
            run_dir.mkdir(parents=True, exist_ok=True)
            self._events_fh = open(run_dir / "events.jsonl", "a", buffering=1)
            self._thinks_fh = open(run_dir / "thinks.jsonl", "a", buffering=1)

    # ------------------------------------------------------------ memory
    def memory(self, cid: str) -> Memory:
        return self.memories.setdefault(cid, Memory())

    def load_lore(self) -> None:
        for name, text in lore():
            self.recall.add_lore(name, text)

    def _remember(self, c: Creature, text: str, importance: int = 1, kind: str = "memory", index: bool = True) -> None:
        mem = self.memory(c.id)
        mem.add(self.world.tick, text, importance)
        if index:
            self.recall.add(c.id, kind, text, self.world.tick, importance, skip_repeat=True)
        m = SAYS_RE.match(text)
        if m:
            mem.note_person(m.group(1), f'last said: "{m.group(2)[:70]}"')
        m = GAVE_RE.match(text)
        if m:
            mem.note_person(m.group(1), f"gave you {m.group(2)}")

    def _on_activity_result(self, c: Creature, res: ActionResult) -> None:
        self._remember(c, res.message if res.ok else f"{res.message}", 1)
        self.last.setdefault(c.id, {})["result"] = res.message
        if res.ok and res.step_done:
            self._advance_plan(c)

    def _advance_plan(self, c: Creature) -> None:
        mem = self.memory(c.id)
        done = mem.advance()
        if done and not mem.plan:
            self._remember(c, f"You finished your plan: {done}", 2)

    # ------------------------------------------------------------ nodes
    def color_for(self, model: str) -> str:
        if model not in self.model_colors:
            self.model_colors[model] = PALETTE[len(self.model_colors) % len(PALETTE)]
        return self.model_colors[model]

    def new_creature(self, model: str) -> Creature:
        used = {c.name for c in self.world.creatures.values()}
        persona = make_persona(self.rng, used)
        x, y = self.world.spawn_point()
        cid = self.world.new_id("c")
        c = Creature(cid, persona["name"], x, y, model=model, color=self.color_for(model), persona=persona)
        c.known_recipes = {r.output for r in self.world.catalog.recipes if r.known_at_start}
        self.world.creatures[cid] = c
        mem = self.memory(cid)
        self._remember(c, "You wake in a sunny meadow with empty hands. You remember nothing before this moment.", 2)
        self.world.emit("join", cid, x, y, f"{c.name} appeared in the meadow ({model}).")
        return c

    def name_in_use(self, name: str) -> bool:
        """A live node already has this name (a dropped one's socket is closed, so its name can be reclaimed)."""
        return any(n.name == name[:40] and not getattr(n.ws, "closed", False) for n in self.nodes.values())

    def register_node(self, ws: web.WebSocketResponse, hello: dict) -> tuple[Node, list[Creature]]:
        name = str(hello.get("node") or f"node-{len(self.nodes) + 1}")[:40]
        for old in [n for n in self.nodes.values() if n.name == name]:
            self.unregister_node(old.id)
        node = Node(self.world.new_id("n"), name, ws, max(1, min(64, int(hello.get("slots") or 4))),
                    list(hello.get("models") or []), dict(hello.get("hardware") or {}))
        self.nodes[node.id] = node
        assigned: list[Creature] = []
        budget = MAX_PER_NODE
        for spec in node.models:
            tag = str(spec.get("tag") or "unknown")[:60]
            want = max(0, min(int(spec.get("creatures") or 0), budget))
            mine = [c for c in self.world.creatures.values() if self.owner.get(c.id) == name and c.model == tag and c.node_id is None]
            orphans = [c for c in self.world.creatures.values()
                       if c.model == tag and c.node_id is None and self.owner.get(c.id) not in {n.name for n in self.nodes.values()}
                       and c not in mine]
            adopt = {str(t)[:60] for t in spec.get("adopt") or []} - {tag}
            others = {n.name for n in self.nodes.values() if n is not node}  # creatures of a node still connected stay with it
            adoptees = [c for c in self.world.creatures.values()
                        if c.model in adopt and c.node_id is None and self.owner.get(c.id) not in others]
            picked = (mine + orphans + adoptees)[:want]
            for c in picked:
                if c.model != tag:
                    self.transplant(c, tag)
            while len(picked) < want and len(self.world.creatures) < MAX_CREATURES:
                picked.append(self.new_creature(tag))
            for c in picked:
                c.node_id = node.id
                c.asleep = False
                c.thinking = False
                c.wake_reason = "woke"
                self.owner[c.id] = name
            assigned += picked
            budget -= len(picked)
        self.harness.assign(self.world.creatures.values())
        self.world.emit("join", None, *self.world.center, f"Brain node '{name}' joined with {len(assigned)} creatures.")
        return node, assigned

    def transplant(self, c: Creature, tag: str) -> None:
        """Give a creature a new mind. Its body, memories and bonds stay; what it did so far stays credited to the old model."""
        old = c.model
        earned = Counter(c.stats)
        earned.subtract(c.stats_base)
        self.metrics.retire(old, +earned)
        c.stats_base = Counter(c.stats)
        c.minds.append({"model": old, "until": self.world.tick})
        c.model, c.color = tag, self.color_for(tag)
        self._remember(c, "You wake with a strange clarity, as if your thoughts run along new paths.", 1)
        self.world.emit("join", c.id, c.x, c.y, f"{c.name}'s mind moved from {old} to {tag}.")

    def unregister_node(self, node_id: str) -> None:
        node = self.nodes.pop(node_id, None)
        if not node:
            return
        for jid in list(node.inflight):
            self.jobs.pop(jid, None)
        for c in self.world.creatures.values():
            if c.node_id == node_id:
                c.node_id = None
                c.asleep = True
                c.thinking = False
                c.activity = None
        self.world.emit("sleep", None, *self.world.center, f"Brain node '{node.name}' left; its creatures fell asleep.")

    # ------------------------------------------------------------ dispatch
    def _next_job_id(self) -> str:
        self._job_seq += 1
        return f"j{self._job_seq}"

    def expire_jobs(self) -> None:
        now = time.time()
        for jid, job in list(self.jobs.items()):
            if now - job.sent > JOB_TIMEOUT_S:
                self.jobs.pop(jid, None)
                if job.kind == "chronicle":
                    self.chronicle_inflight = False
                node = self.nodes.get(job.node)
                if node:
                    node.inflight.pop(jid, None)
                c = self.world.creatures.get(job.creature)
                if c:
                    c.thinking = False
                    c.wake_reason = c.wake_reason or "idle"
                self.metrics.bump(job.model, "timeouts")

    def plan_dispatch(self) -> list[tuple[Node, dict]]:
        w = self.world
        out: list[tuple[Node, dict]] = []
        for node in self.nodes.values():
            free = node.slots - len(node.inflight)
            if free <= 0:
                continue
            ready = [c for c in w.creatures.values()
                     if c.node_id == node.id and not c.asleep and not c.thinking and not c.collapsed
                     and c.wake_reason is not None and w.tick - c.last_think_tick >= MIN_GAP_TICKS]
            if not self.chronicle_inflight and w.tick >= self.chronicle_due and node.models:
                job = self.make_chronicle_job(node)  # rare, so it jumps the queue
                if job:
                    out.append((node, job))
                    free -= 1
            ready.sort(key=lambda c: (WAKE_PRIORITY.get(c.wake_reason, 9), c.last_think_tick))
            for c in ready[:max(0, free)]:
                out.append((node, self.make_job(node, c)))
        return out

    # ------------------------------------------------------------ chronicle
    def chronicle_digest(self, since: int) -> list[str]:
        w = self.world
        evs = [e for e in w.events if e.tick > since]
        lines: list[str] = []
        crafted: dict[str, int] = {}
        eaten = 0
        speech = []
        for e in evs:
            if e.kind in ("discover", "place", "plant", "write", "program", "collapse", "give"):
                lines.append(e.text.split("\n")[0][:200])
            elif e.kind == "craft":
                crafted[e.text] = crafted.get(e.text, 0) + 1
            elif e.kind == "eat":
                eaten += 1
            elif e.kind == "say" and e.actor:
                speech.append(e.text[:200])
        lines += [t if n == 1 else f"{t} (x{n})" for t, n in list(crafted.items())[:15]]
        if eaten:
            lines.append(f"Creatures ate {eaten} times.")
        if speech:
            step = max(1, len(speech) // 12)
            lines += ["Overheard: " + s for s in speech[::step][:12]]
        return lines[:60]

    def firsts_text(self) -> str:
        w = self.world
        firsts = sorted(w.discoveries.values(), key=lambda d: d["tick"])
        if not firsts:
            return "none yet"
        return "; ".join(f"{d['by']} {'invented' if d.get('invented') else 'first made'} the {w.catalog.name(d['item'])}"
                         for d in firsts)

    def make_chronicle_job(self, node: Node) -> dict | None:
        lines = self.chronicle_digest(self.chronicle_from)
        self.chronicle_due = self.world.tick + CHRONICLE_EVERY
        if len(lines) < 3:
            return None
        clock = self.world.clock()
        prev = self.chronicle[-1]["text"] if self.chronicle else "(this is the first chapter)"
        messages = [
            {"role": "system", "content": "You are the chronicler of a small wild world whose creatures are learning to survive, make tools and live together. Write warmly and concretely, like a storybook historian. Never invent events that are not in the notes."},
            {"role": "user", "content": f"Previous chapter: {prev}\n\nFirsts in this world's history so far: {self.firsts_text()}\n\n"
             f"What happened since the previous chapter (raw notes):\n" + "\n".join(f"- {l}" for l in lines)
             + f"\n\nIt is now day {clock['day']}, {clock['phase']}. Write the next chapter of the chronicle in 3 to 6 sentences. Name the creatures involved, highlight discoveries, cooperation and troubles. Someone making a thing that was already discovered is copying it, not discovering it. Plain prose only."},
        ]
        jid = self._next_job_id()
        tag = str(node.models[0].get("tag"))
        self.jobs[jid] = Job(jid, "", node.id, "chronicle", tag, time.time(), None)
        node.inflight[jid] = ""
        self.chronicle_inflight = True
        self._chron_until = self.world.tick
        return {"type": "think", "job": jid, "creature": "", "model": tag, "kind": "chronicle",
                "messages": messages, "schema": None, "max_tokens": 320}

    def finish_chronicle(self, ok: bool, output) -> None:
        self.chronicle_inflight = False
        if not ok or not output:
            return
        text = output if isinstance(output, str) else json.dumps(output)
        text = " ".join(text.split())[:1500]
        clock = self.world.clock()
        entry = {"tick": self.world.tick, "day": clock["day"], "phase": clock["phase"], "text": text}
        self.chronicle.append(entry)
        self.chronicle_from = getattr(self, "_chron_until", self.world.tick)
        cx, cy = self.world.center
        self.world.emit("chronicle", None, cx, cy, f"Chronicle, day {clock['day']}: {text}")
        if self.run_dir:
            with open(self.run_dir / "chronicle.md", "a") as fh:
                fh.write(f"## Day {clock['day']}, {clock['phase']} (tick {self.world.tick})\n\n{text}\n\n")

    def _places(self, c: Creature) -> list[tuple[str, str]]:
        """Where this creature remembers things being: its map memory and the landmarks it can name."""
        out = []
        for kind, (x, y, t) in c.spots.items():
            d = dist(c.x, c.y, x, y)
            where = "right here" if d == 0 else f"about {d} steps {direction(x - c.x, y - c.y)}"
            out.append(("place", f"{spot_name(kind)}, {where} of you (last seen {max(0, self.world.tick - t)} ticks ago)"))
        for lm in getattr(self.world, "landmarks", []):
            if lm["name"] not in c.landmarks_seen:  # only what it has been near
                continue
            d = dist(c.x, c.y, lm["x"], lm["y"])
            out.append(("place", f"{lm['name']}, about {d} steps {direction(lm['x'] - c.x, lm['y'] - c.y)} of you"))
        return out

    def _recipes(self, c: Creature) -> list[tuple[str, str]]:
        cat = self.world.catalog
        return [("recipe", cat.describe_recipe(r)) for name in sorted(c.known_recipes) if (r := cat.recipe_for(name))]

    def _recall_hook(self, c: Creature, query: str) -> list[tuple[str, str]]:
        """What the `recall` action finds: memories, places, recipes, texts read and shared lore."""
        hits = self.recall.search(c.id, query, k=RECALL_ASKED, now=self.world.tick,
                                  extra=[*self._places(c), *self._recipes(c)])
        return [(d.kind, d.text[:RECALL_LINE]) for d in hits]

    @staticmethod
    def _recall_note(it, message: str) -> str:
        """What a creature keeps of a recall: one short line, not the whole answer."""
        found = message.splitlines()[1:]
        query = (it.target or it.text)[:40]
        if not found:
            return f'You tried to think back about "{query}", but nothing came.'
        more = f"; and {len(found) - 1} more" if len(found) > 1 else ""
        return f'You thought back about "{query}": {found[0][:90]}{more}.'[:160]

    def auto_recall(self, c: Creature, mem: Memory, recent: list[str]) -> list[tuple[str, str]]:
        """Up to 3 things worth recalling now: from the goal, the plan's NOW step and what is in sight."""
        aim = [mem.goal]
        if mem.plan and mem.plan_step < len(mem.plan):
            aim.append(mem.plan[mem.plan_step])
        stable = " ".join(w for w in aim if w)  # steady across turns, so its embedding is reused
        words = [stable]
        words += [o.name for o, _, _ in visible_objects(self.world, c)]
        words += [o.name for o, _, _ in visible_creatures(self.world, c)]
        if c.satiety < HUNGRY:
            words.append("food eat berries")
        query = " ".join(dict.fromkeys(w for w in words if w))
        hits = self.recall.search(c.id, query, k=AUTO_RECALL, now=self.world.tick, exclude=recent,
                                  semantic=stable, lore=False)  # lore is already shown as techniques
        return [(d.kind, d.text[:AUTO_LINE]) for d in hits]

    def make_job(self, node: Node, c: Creature) -> dict:
        mem = self.memory(c.id)
        jid = self._next_job_id()
        reason = c.wake_reason
        shown: list[str] = []
        shown_recalled: list[str] = []
        layers = self.harness.layers_for(c)
        if mem.needs_reflection():
            kind, messages, schema, max_tokens = "reflect", build_reflect_messages(c, mem, layers), None, 220
        else:
            self.sim.maybe_inspire(c)
            perception = perceive(self.world, c, heard=self.sim.take_heard(c))
            self.last.setdefault(c.id, {})["perception"] = perception
            recalled: list[tuple[str, str]] = []
            if "recall" in layers:
                recalled = self.auto_recall(c, mem, curated_recent(mem, recent_limit(layers)))
            if "disclose" in layers:
                tips = set(relevant(self.world, c, tip_limit(layers)))
                shown = [t.name for t in TECHNIQUES if t.line in tips]
            kind, messages, schema, max_tokens = "act", build_act_messages(
                self.world, c, mem, perception, reason, layers, [f"{k}: {t}" for k, t in recalled]), \
                (INTENTION_SCHEMA_PLAN if "plan" in layers else INTENTION_SCHEMA), 260
            shown_recalled = [f"{k}: {t[:60]}" for k, t in recalled]
        c.thinking = True
        c.last_think_tick = self.world.tick
        c.wake_reason = None
        self.jobs[jid] = Job(jid, c.id, node.id, kind, c.model, time.time(), reason, shown, shown_recalled)
        node.inflight[jid] = c.id
        return {"type": "think", "job": jid, "creature": c.id, "model": c.model, "kind": kind,
                "messages": messages, "schema": schema, "max_tokens": max_tokens}

    def handle_result(self, node: Node, msg: dict) -> None:
        jid = str(msg.get("job"))
        node.inflight.pop(jid, None)
        job = self.jobs.pop(jid, None)
        if not job:
            return
        if job.kind == "chronicle":
            self.finish_chronicle(bool(msg.get("ok")), msg.get("output"))
            return
        c = self.world.creatures.get(job.creature)
        if not c:
            return
        c.thinking = False
        ok = bool(msg.get("ok"))
        self.metrics.think(c.model, int(msg.get("latency_ms") or 0), int(msg.get("tokens_in") or 0), int(msg.get("tokens_out") or 0), ok)
        self.metrics.bump(c.model, "cached_tokens", int(msg.get("cached_tokens") or 0))
        mem = self.memory(c.id)
        output = msg.get("output")
        log = {"tick": self.world.tick, "creature": c.id, "name": c.name, "model": c.model, "kind": job.kind, "ok": ok,
               "output": output, "error": msg.get("error"), "latency_ms": msg.get("latency_ms"),
               "tokens_in": msg.get("tokens_in"), "cached_tokens": msg.get("cached_tokens"),
               "harness": sorted(self.harness.layers_for(c))}
        if job.kind == "act":
            log.update(shown=job.shown, recalled=job.recalled)

        def write_log(result: dict | None = None) -> None:
            if self._thinks_fh:
                self._thinks_fh.write(json.dumps({**log, "result": result} if result else log) + "\n")

        if not ok or job.kind == "reflect":
            write_log()
        if not ok:
            c.last_think_tick = self.world.tick + 6  # back off a little
            c.wake_reason = "idle"
            self.last.setdefault(c.id, {})["error"] = str(msg.get("error"))[:300]
            return
        if job.kind == "reflect":
            text = output if isinstance(output, str) else json.dumps(output)
            mem.apply_reflection(text)
            if mem.summary:
                self.recall.add(c.id, "memory", f"You reflected: {mem.summary}", self.world.tick, 3)
            self.wishes.observe_reflection(c.name, text, self.world.tick)
            self.last.setdefault(c.id, {})["reflection"] = mem.summary
            c.wake_reason = job.wake_reason or "woke"
            return
        it = parse_intention(output)
        info = self.last.setdefault(c.id, {})
        if it is None:
            write_log({"ok": False, "parsed": False})
            self.metrics.bump(c.model, "parse_failures")
            info.update(thought="(confused)", intention=str(output)[:200], result="You hesitate, unsure what to do.")
            self._remember(c, "You hesitated, unsure what to do.", 1)
            c.wake_reason = "idle"
            return
        mem.thinks_since_reflect += 1
        if it.goal and it.goal.lower() not in ("", "none", "same", "keep"):
            mem.goal = it.goal
        plan_on = "plan" in self.harness.layers_for(c)
        if plan_on and it.plan:
            mem.set_plan(it.plan)
        res = apply_intention(self.world, c, it)
        write_log({"ok": res.ok, "noop": res.noop, "message": res.message[:240]})
        info.update(thought=it.thought, intention=it.summary(), result=res.message, tick=self.world.tick)
        self.metrics.bump(c.model, "act_ok" if res.ok else "act_fail")
        if res.noop:
            self.metrics.bump(c.model, "noops")
        if res.ok and res.instant and it.action == "recall":
            self._remember(c, self._recall_note(it, res.message), 1, index=False)
        elif res.ok and res.instant:
            self._remember(c, res.message, 2 if it.action in ("combine", "craft", "say", "read") else 1,
                           kind="read" if it.action == "read" else "memory")
        elif not res.ok:
            self._remember(c, f"You tried to {it.summary()}, but: {res.message}", 1)
        if plan_on and it.step_done and res.ok and not res.noop and mem.plan:
            if res.instant:
                self._advance_plan(c)
            elif c.activity:
                c.activity["step_done"] = True
        if it.action == "say" and res.ok and it.target:
            mem.note_person(it.target.split()[0].capitalize(), f'you told them: "{it.text[:60]}"')
        self._track_loop(c, it.action, it.target, res.ok, res.noop)
        if res.instant:
            c.wake_reason = "result"

    def _track_loop(self, c: Creature, action: str, target: str, ok: bool, noop: bool = False) -> None:
        dq = self.recent_acts.setdefault(c.id, deque(maxlen=3))
        dq.append((action, target.lower(), ok, noop))
        if len(dq) == 3 and len(set(dq)) == 1 and (noop or not ok):
            self.metrics.bump(c.model, "loops")
            self._remember(c, "You notice you keep doing the same thing and nothing changes. Try something different."
                           if noop else "You notice you keep trying the same thing and failing. Try something different.", 3)
            dq.clear()

    # ------------------------------------------------------------ history
    def record_history(self) -> None:
        w = self.world
        models: dict[str, Counter] = {}
        known_total = 0
        for c in w.creatures.values():
            m = models.setdefault(c.model, Counter())
            m["creatures"] += 1
            for k in HISTORY_STATS:
                m[k] += c.stats.get(k, 0) - c.stats_base.get(k, 0)
            m["learned"] += sum(c.stats.get(k, 0) - c.stats_base.get(k, 0) for k in LEARN_STATS)
            m["recipes_known"] += len(c.known_recipes)
            known_total += len(c.known_recipes)
        for tag, r in self.metrics.retired.items():  # creatures' deeds under minds they've since lost
            m = models.setdefault(tag, Counter())
            for k in HISTORY_STATS:
                m[k] += r.get(k, 0)
            m["learned"] += sum(r.get(k, 0) for k in LEARN_STATS)
        for tag, m in models.items():
            m["thinks"] = self.metrics.models[tag]["thinks"]
        structures = sum(1 for o in w.objects.values()
                         if o.kind in ("campfire", "workbench", "furnace", "bed", "creation", "chest", "millstone", "sign", "wall", "door"))
        self.history.append({
            "tick": w.tick, "day": w.clock()["day"],
            "models": {k: dict(v) for k, v in models.items()},
            "world": {"recipes_known": known_total, "firsts": len(w.discoveries), "structures": structures,
                      "camps": sum(1 for lm in getattr(w, "landmarks", []) if lm["kind"] == "camp"),
                      "inventions": len(getattr(w.catalog, "inventions", [])), "ties": len(self.relations)},
        })
        if len(self.history) > HISTORY_MAX:
            del self.history[: len(self.history) - HISTORY_MAX]

    # ------------------------------------------------------------ society
    def _note_relation(self, ev) -> None:
        kind = {"say": "talk", "give": "gift", "learn": "teach"}.get(ev.kind)
        if not kind:
            return
        if ev.kind == "learn":
            a, b = ev.data.get("teacher"), ev.actor
        else:
            a, b = ev.actor, ev.data.get("to")
        if not a or not b or a == b or a not in self.world.creatures or b not in self.world.creatures:
            return
        key = "|".join(sorted((a, b)))
        self.relations.setdefault(key, Counter())[kind] += 1

    def society(self) -> dict:
        w = self.world
        nodes = [{"id": c.id, "name": c.name, "model": c.model, "color": c.color, "asleep": c.asleep,
                  "drive": (c.persona or {}).get("drive")} for c in w.creatures.values()]
        edges = []
        for key, cnt in self.relations.items():
            a, b = key.split("|")
            weight = cnt["talk"] + 3 * cnt["gift"] + 4 * cnt["teach"]
            edges.append({"a": a, "b": b, "talk": cnt["talk"], "gift": cnt["gift"], "teach": cnt["teach"], "weight": weight})
        edges.sort(key=lambda e: -e["weight"])
        degree: Counter = Counter()
        for e in edges:
            degree[e["a"]] += e["weight"]
            degree[e["b"]] += e["weight"]
        name = {c.id: c.name for c in w.creatures.values()}
        hubs = [{"id": cid, "name": name.get(cid, cid), "weight": wt} for cid, wt in degree.most_common(5)]
        loners = [n["name"] for n in nodes if degree[n["id"]] == 0 and not n["asleep"]]
        return {"nodes": nodes, "edges": edges, "hubs": hubs, "loners": loners}

    # ------------------------------------------------------------ the experimenter
    def voice_from_the_sky(self, text: str, x=None, y=None, radius=None) -> list[str]:
        w = self.world
        heard = []
        for c in w.creatures.values():
            if c.collapsed or c.asleep:
                continue
            if x is not None and y is not None and max(abs(c.x - int(x)), abs(c.y - int(y))) > int(radius or 6):
                continue
            line = f'A booming voice from the sky says: "{text}"'
            self.sim.heard[c.id].append(line)
            self._remember(c, line, 3)
            self.sim.wake(c, "heard")
            heard.append(c.name)
        cx, cy = (int(x), int(y)) if x is not None and y is not None else w.center
        w.emit("voice", None, cx, cy, f'A voice from the sky: "{text}"', line=text)
        return heard

    def answer_wish(self, wid: str, reply: str = "", grant: str = "", count: int = 1, status: str = "") -> dict:
        """The people running the world answer a wish: a reply from the sky, a gift, or a note that it will be built."""
        w = self.wishes.get(wid)
        if w is None:
            raise KeyError(wid)
        reply = " ".join(str(reply).split())[:300]
        if not (reply or grant or status):
            raise ValueError("answer with a reply, a gift or a status")
        wishers = [c for c in self.world.creatures.values() if c.name in w["by"]]
        granted_to = None
        if grant:
            iid = self.world.catalog.resolve(grant)
            if iid is None:
                raise ValueError(f"there's no '{grant}' in this world")
            latest = next((q["name"] for q in reversed(w["quotes"])), "")
            c = next((c for c in wishers if c.name == latest), wishers[0] if wishers else None)
            if c is None:
                raise ValueError("nobody who wished for it is in the world now")
            n = max(1, min(5, int(count or 1)))
            c.inventory[iid] += n
            what = f"{n} {self.world.catalog.name(iid)}"
            self._remember(c, f"Your wish for {w['thing']} was heard: {what} appeared in your hands, as if from the sky.", 3)
            self.sim.wake(c, "heard")
            self.world.emit("grant", c.id, c.x, c.y, f"The sky granted {c.name}'s wish: {what}.", item=iid)
            w["granted"], w["status"], granted_to = f"{what} to {c.name}", "granted", c.name
        heard = []
        if reply:
            for c in wishers:
                if c.collapsed:
                    continue
                if c.asleep:
                    self._remember(c, f'In a dream, a voice from the sky answered your wish for {w["thing"]}: "{reply}"', 3)
                else:
                    line = f'A voice from the sky answers your wish for {w["thing"]}: "{reply}"'
                    self.sim.heard[c.id].append(line)
                    self._remember(c, line, 3)
                    self.sim.wake(c, "heard")
                heard.append(c.name)
            self.world.emit("voice", None, *self.world.center, f'A voice from the sky answers the wish for {w["thing"]}: "{reply}"',
                            line=reply)
            w["answer"] = reply
            if w["status"] in ("open", "noted"):
                w["status"] = "answered"
        if status in ("open", "noted", "closed"):
            w["status"] = status
        return {"ok": True, "wish": self.wishes.view(w), "heard_by": heard, "granted_to": granted_to}

    # ------------------------------------------------------------ views
    def creature_detail(self, cid: str) -> dict | None:
        c = self.world.creatures.get(cid)
        if not c:
            return None
        mem = self.memory(cid)
        info = self.last.get(cid, {})
        cat = self.world.catalog
        node = self.nodes.get(c.node_id) if c.node_id else None
        return {
            "id": c.id, "name": c.name, "model": c.model, "minds": c.minds, "color": c.color, "persona": c.persona,
            "x": c.x, "y": c.y, "node": node.name if node else None, "asleep": c.asleep, "thinking": c.thinking,
            "activity": (c.activity or {}).get("label"),
            "perception": info.get("perception", ""), "last_thought": info.get("thought", ""),
            "last_intention": info.get("intention", ""), "last_result": info.get("result", ""),
            "last_error": info.get("error"), "reflection": info.get("reflection"),
            "inventory": {cat.name(i): n for i, n in c.inventory.items() if n > 0},
            "satiety": round(c.satiety), "energy": round(c.energy), "health": round(c.health),
            "goal": mem.goal, "plan": list(mem.plan), "plan_step": mem.plan_step, "summary": mem.summary,
            "known_recipes": [cat.describe_recipe(cat.recipe_for(r)) for r in sorted(c.known_recipes) if cat.recipe_for(r)],
            "people": [f"{n}: {v}" for n, v in mem.people.items()],
            "recent": mem.recent(15),
            "stats": dict(c.stats),
            "harness": sorted(self.harness.layers_for(c)),
        }

    def tick_message(self, new_events: list) -> str:
        w = self.world
        if w.tick % HISTORY_EVERY == 0:
            self.record_history()
        upsert, removed = w.take_object_changes()
        names = {c.id: c.name for c in w.creatures.values()} if new_events else {}
        for ev in new_events:
            self.wishes.observe(ev, names)
            if ev.kind in ("craft", "discover") and ev.actor in w.creatures:
                self.metrics.item(w.creatures[ev.actor].model, ev.data.get("item", ""))
            self._note_relation(ev)
            if self._events_fh:
                self._events_fh.write(json.dumps(ev.to_dict()) + "\n")
        msg = {
            "type": "tick", "tick": w.tick, "clock": w.clock(),
            "creatures": [w.cre_dict(c) for c in w.creatures.values()],
            "objects_upsert": upsert, "objects_removed": removed,
            "landmarks": getattr(w, "landmarks", []) if w.tick % 30 == 0 else None,
            "events": [e.to_dict() for e in new_events if e.kind != "fire_out" or True],
        }
        return json.dumps(msg)

    def metrics_message(self) -> str:
        return json.dumps(self.metrics.snapshot(self.world, self.started))
