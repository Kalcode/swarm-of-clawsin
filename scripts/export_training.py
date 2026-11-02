"""Export a student's training data from run folders: the teacher decisions that worked, as mlx-lm chat examples.

    uv run python scripts/export_training.py runs/teacher --out data/student/night1          # every finished episode
    uv run python scripts/export_training.py runs/teacher/2026*-s1?? --out data/student/some --valid-fraction 0.1

Writes train.jsonl and valid.jsonl ({"messages": [system, user, assistant]}, the format mlx_lm.lora reads; the
assistant turn is the intention JSON with every field of the schema the creature was asked with, in the schema's
order) and summary.json. A folder without thinks.jsonl stands for the episode folders inside it (not *.partial).

Only finished teacher episodes (scripts/teacher_runs.py: a folder with meta.json and `done`) are exported. A live
run's folder is always left out, with no way to include it: a live prompt quotes what other creatures said and the
sky's words verbatim in its memories, and the save carries those memories across restarts, so even a run without a
Gemini creature in it can hold Gemini's words. A teacher episode has one mind thinking for everyone. A teacher
episode with meta.json but no `done` is unfinished and left out too (its seed gets redone).

What is kept from them: act decisions whose think and action succeeded and changed something (not a no-op), whose
line carries the full prompt, from allowed teachers: model names matching gpt-oss or qwen (any case). Gemini and
anything matching gemini or google is always left out (Google's terms forbid training other models on its outputs),
whatever its line, its episode's meta.json or its server says. Mock decisions only with --allow-mock (tests and
plumbing). Exact (prompt, answer) duplicates are dropped before weighting. Every skip is counted by reason in the
summary. A run folder that doesn't exist, or holds no episodes, is warned about; if none exists the export stops.

Weights (the controller's ruling), from what followed each decision until the creature's next one:
    a discovery or invention (a discover or invent event by the creature)   4
    a craft (a craft event by the creature)                                 3
    eating while hungry (eat, and "You feel a bit hungry / very hungry /
        starving" in the prompt)                                            2
    finishing a plan step (step_done true)                                  2
    anything else                                                           1
The largest that applies counts. Then repeats are damped: the same action and target as the creature's previous
decision is x0.5 the second time in a row and x0.25 the third time or later (counted over all its decisions, failed
ones too). mlx-lm has no per-example weights, so a weight w becomes int(w) copies plus one more with probability
w - int(w) (seeded): 3 is three copies, 0.25 is kept one time in four. Only train.jsonl is weighted; valid.jsonl
holds each kept decision once, so validation loss measures plain imitation.

The split is by world seed, never by line: every episode of one seed (two teachers on the same seed, or a seed redone
into another --out, start from the same world and say near-twin prompts) goes to the same side, and so does each
episode without a seed in its meta.json on its own. --valid-fraction of those groups (at least one when there are
two or more), chosen with --seed, go to valid.jsonl. With a single group everything goes to train.jsonl and a warning
says so (mlx_lm.lora needs a validation set: export two or more seeds)."""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import random
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from swarmworld.mind.prompts import INTENTION_SCHEMA, INTENTION_SCHEMA_PLAN  # noqa: E402

NEVER = re.compile(r"gemini|google", re.I)
TEACHERS = re.compile(r"gpt-oss|qwen", re.I)
HUNGRY = re.compile(r"^You feel (?:a bit hungry|very hungry|starving)\b", re.M)
UP = {"discovery": 4, "craft": 3, "ate hungry": 2, "plan step": 2}
OUTCOME_EVENTS = {"discover": "discovery", "invent": "discovery", "craft": "craft"}
REPEAT = (1.0, 0.5, 0.25)  # first, second, third-or-later time in a row
LIVE_RUN = "live run: prompts may hold other models' text"


@dataclass
class Decision:
    run: str
    model: str
    creature: str
    tick: int
    action: str
    messages: list[dict]
    answer: str
    weight: float = 1.0
    why: str = ""
    group: str = ""  # the split's unit: the episode's world seed, or the run folder when it has none


# ------------------------------------------------------------------ reading
def episodes(paths: list[Path], log=print) -> list[Path]:
    """The episode folders the given paths stand for. Warns about a path that doesn't exist or holds no episodes;
    stops if none of them exists (a mistyped path would otherwise export nothing, quietly)."""
    if paths and not any(p.exists() for p in paths):
        raise SystemExit("none of the run folders exist: " + ", ".join(str(p) for p in paths))
    out: list[Path] = []
    for p in paths:
        if (p / "thinks.jsonl").exists():
            out.append(p)
            continue
        if not p.exists():
            log(f"Warning: no such folder: {p}")
            continue
        inside = sorted(c for c in p.iterdir() if c.is_dir() and ".partial" not in c.name and (c / "thinks.jsonl").exists())
        if not inside:
            log(f"Warning: no episodes in {p} (no thinks.jsonl in it or in the folders inside it)")
        out += inside
    return list(dict.fromkeys(out))


def jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:  # a line cut off when a run stopped
            continue
    return rows


# ------------------------------------------------------------------ the schema answer
DEFAULTS = {"string": "", "array": [], "boolean": False}


def _fits(value, spec: dict) -> bool:
    t = spec.get("type")
    if t == "string":
        return isinstance(value, str) and len(value) <= spec.get("maxLength", 10**9) and value in spec.get("enum", [value])
    if t == "integer":
        return (isinstance(value, int) and not isinstance(value, bool)
                and spec.get("minimum", -10**9) <= value <= spec.get("maximum", 10**9))
    if t == "boolean":
        return isinstance(value, bool)
    if t == "array":
        return (isinstance(value, list) and len(value) <= spec.get("maxItems", 10**9)
                and all(_fits(v, spec.get("items", {})) for v in value))
    return False


def schema_answer(output, schema: dict) -> tuple[dict | None, bool]:
    """The teacher's answer as the schema has it: every property in order, a missing one given its empty value ("",
    [], false, the minimum). Returns (answer, completed) or (None, False) when a value doesn't fit the schema."""
    if not isinstance(output, dict):
        return None, False
    out, completed = {}, set(output) != set(schema["properties"])
    for key, spec in schema["properties"].items():
        if key in output:
            if not _fits(output[key], spec):
                return None, False
            out[key] = output[key]
        else:
            out[key] = spec.get("minimum", 1) if spec.get("type") == "integer" else DEFAULTS[spec["type"]]
    return out, completed


# ------------------------------------------------------------------ weights
def _key(output) -> tuple:
    if not isinstance(output, dict):
        return (None,)
    return (str(output.get("action", "")).lower(), str(output.get("target", "")).strip().lower())


def weigh(thinks: list[dict], events: list[dict]) -> list[Decision]:
    """A Decision (weight and reason, no answer yet) for every act line, in order; see the module docstring."""
    outcomes: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for e in events:
        if e.get("kind") in OUTCOME_EVENTS and e.get("actor"):
            outcomes[e["actor"]].append((int(e.get("tick", 0)), OUTCOME_EVENTS[e["kind"]]))
    for v in outcomes.values():
        v.sort()
    acts = [t for t in thinks if t.get("kind") == "act"]
    nxt: dict[int, int] = {}
    last_of: dict[str, int] = {}
    for i in range(len(acts) - 1, -1, -1):
        cid = acts[i].get("creature", "")
        nxt[i] = last_of.get(cid, 10**12)
        last_of[cid] = int(acts[i].get("tick", 0))
    streak: dict[str, tuple[tuple, int]] = {}
    out = []
    for i, t in enumerate(acts):
        cid, tick, output = t.get("creature", ""), int(t.get("tick", 0)), t.get("output")
        key = _key(output)
        prev, n = streak.get(cid, ((), 0))
        n = n + 1 if key == prev and key != (None,) else 1
        streak[cid] = (key, n)
        evs = outcomes.get(cid, [])
        lo = bisect.bisect_left(evs, (tick, ""))
        led = {why for tk, why in evs[lo:] if tk < nxt[i]} if evs else set()
        if isinstance(output, dict):
            user = next((m.get("content", "") for m in t.get("messages") or [] if m.get("role") == "user"), "")
            if output.get("action") == "eat" and HUNGRY.search(user.split("Right now:")[-1]):
                led.add("ate hungry")
            if output.get("step_done") is True:
                led.add("plan step")
        why = max(led, key=lambda w: UP[w]) if led else ""
        weight = UP.get(why, 1) * REPEAT[min(n, len(REPEAT)) - 1]
        if n > 1:
            why = f"{why}, repeat" if why else "repeat"
        out.append(Decision(str(t.get("run", "")), str(t.get("model", "")), cid, tick,
                            str(output.get("action", "")) if isinstance(output, dict) else "", t.get("messages") or [],
                            "", weight, why))
    return out


def copies(weight: float, rng: random.Random) -> int:
    n = int(weight)
    return n + (1 if rng.random() < weight - n else 0)


# ------------------------------------------------------------------ one episode
def teacher_gate(model: str, meta: dict, allow_mock: bool) -> str | None:
    """None if this model may teach, else the reason it may not."""
    names = [model, str(meta.get("model") or ""), str(meta.get("base_url_host") or "")]
    if any(NEVER.search(n) for n in names):
        return "Gemini/Google (never used)"
    if model == "mock":
        return None if allow_mock else "mock (needs --allow-mock)"
    return None if TEACHERS.search(model) else "teacher not allowed"


def _prompt(t: dict) -> list[dict] | None:
    msgs = t.get("messages")
    if (isinstance(msgs, list) and len(msgs) == 2 and [m.get("role") for m in msgs] == ["system", "user"]
            and all(isinstance(m.get("content"), str) and m["content"] for m in msgs)):
        return [{"role": m["role"], "content": m["content"]} for m in msgs]
    return None


def decisions(run_dir: Path, allow_mock: bool, skipped: Counter, completed: Counter) -> list[Decision]:
    thinks = jsonl(run_dir / "thinks.jsonl")
    meta_path = run_dir / "meta.json"
    acts_here = sum(1 for t in thinks if t.get("kind") == "act")
    if not meta_path.exists():
        skipped[LIVE_RUN] += acts_here
        return []
    meta = json.loads(meta_path.read_text())
    if not (run_dir / "done").exists():
        skipped["unfinished episode"] += acts_here
        return []
    group = f"seed {meta['seed']}" if meta.get("seed") is not None else f"run {run_dir}"
    skipped["not an act decision"] += sum(1 for t in thinks if t.get("kind") != "act")
    acts = [t for t in thinks if t.get("kind") == "act"]
    kept = []
    for t, d in zip(acts, weigh(thinks, jsonl(run_dir / "events.jsonl"))):
        r = t.get("result") or {}
        reason = teacher_gate(d.model, meta, allow_mock)
        if reason is None:
            reason = ("think failed" if not t.get("ok") or not t.get("result") else
                      "unparsed answer" if r.get("parsed") is False else
                      "action failed" if not r.get("ok") else
                      "no-op" if r.get("noop") else None)
        prompt = _prompt(t) if reason is None else None
        if reason is None and prompt is None:
            reason = "no full prompt"
        if reason is None:
            schema = INTENTION_SCHEMA_PLAN if "plan" in (t.get("harness") or []) else INTENTION_SCHEMA
            ans, filled = schema_answer(t.get("output"), schema)
            if ans is None:
                reason = "off-schema answer"
            else:
                completed["n"] += filled
                d.answer = json.dumps(ans, ensure_ascii=False)
        if reason:
            skipped[reason] += 1
            continue
        d.run, d.messages, d.group = run_dir.name, prompt, group
        kept.append(d)
    return kept


# ------------------------------------------------------------------ export
def tokens(text: str) -> int:
    return len(text) // 4


def chat(d: Decision) -> dict:
    return {"messages": [*d.messages, {"role": "assistant", "content": d.answer}]}


def export(run_dirs: list[Path], out: Path, valid_fraction: float = 0.1, seed: int = 0, allow_mock: bool = False,
           log=print) -> dict:
    skipped: Counter = Counter()
    completed: Counter = Counter()
    found = episodes(run_dirs, log)
    names = Counter(p.name for p in found)
    unique: list[Decision] = []
    seen: set[bytes] = set()  # digests of (prompt, answer): a night's prompts would double the memory as keys
    for p in found:
        for d in decisions(p, allow_mock, skipped, completed):
            if names[p.name] > 1:  # two folders of the same name from different places
                d.run = str(p)
            key = hashlib.sha256(json.dumps([d.messages, d.answer], ensure_ascii=False).encode()).digest()
            if key in seen:
                skipped["duplicate"] += 1
                continue
            seen.add(key)
            unique.append(d)
    runs = sorted({d.run for d in unique})
    groups = sorted({d.group for d in unique})
    shuffled = groups[:]
    random.Random(seed).shuffle(shuffled)
    warnings = []
    if len(groups) == 1:
        n_valid = 0
        warnings.append("only one episode (or one seed's episodes): it all goes to train.jsonl and valid.jsonl is empty "
                        "(mlx_lm.lora needs a validation set: export two or more seeds)")
    elif len(groups) >= 2 and valid_fraction > 0:
        n_valid = min(len(groups) - 1, max(1, round(len(groups) * valid_fraction)))
    else:
        n_valid = 0
    valid_groups = set(shuffled[:n_valid])
    valid_runs = {d.run for d in unique if d.group in valid_groups}
    train, valid = [], []
    lines_of: Counter = Counter()
    pick = random.Random(seed + 1)
    for d in unique:
        n = 1 if d.group in valid_groups else copies(d.weight, pick)
        (valid if d.group in valid_groups else train).extend([d] * n)
        lines_of[d.run] += n
    random.Random(seed + 2).shuffle(train)
    random.Random(seed + 3).shuffle(valid)
    out.mkdir(parents=True, exist_ok=True)
    for name, rows in (("train.jsonl", train), ("valid.jsonl", valid)):
        with open(out / name, "w") as fh:
            for d in rows:
                fh.write(json.dumps(chat(d), ensure_ascii=False) + "\n")
    written = train + valid
    prompt_t = [tokens(m["content"]) for d in written for m in d.messages]
    answer_t = [tokens(d.answer) for d in written]
    summary = {
        "examples": len(unique), "train_lines": len(train), "valid_lines": len(valid),
        "models": dict(Counter(d.model for d in unique).most_common()),
        "model_lines": dict(Counter(d.model for d in written).most_common()),
        "runs": {r: {"examples": sum(1 for d in unique if d.run == r), "lines": lines_of[r],
                     "split": "valid" if r in valid_runs else "train"} for r in runs},
        "actions": dict(Counter(d.action for d in written).most_common()),
        "weights": dict(Counter(d.why or "plain" for d in unique).most_common()),
        "avg_prompt_tokens": round(sum(prompt_t) / len(written)) if written else 0,
        "avg_answer_tokens": round(sum(answer_t) / len(written)) if written else 0,
        "max_example_tokens": max((tokens("".join(m["content"] for m in d.messages) + d.answer) for d in written), default=0),
        "completed_to_schema": completed["n"],
        "skipped": {k: v for k, v in skipped.most_common() if v},
        "warnings": warnings,
        "sources": [str(p) for p in found], "valid_fraction": valid_fraction, "seed": seed, "allow_mock": allow_mock,
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=1))
    for w in warnings:
        log(f"Warning: {w}")
    return summary


def report(s: dict, out: Path) -> str:
    def table(d: dict, total: int | None = None) -> list[str]:
        return [f"  {k:<40} {v:>7}" + (f"  {v / total:.0%}" if total else "") for k, v in d.items()]

    lines = [f"Wrote {s['train_lines']} train and {s['valid_lines']} valid lines ({s['examples']} unique decisions) to {out}",
             "", "Examples by source model (unique decisions; lines written):"]
    lines += [f"  {m:<40} {n:>7}  {s['model_lines'].get(m, 0):>7}" for m, n in s["models"].items()] or ["  (none)"]
    lines += ["", "Examples by run (unique decisions; lines written; split):"]
    lines += [f"  {r:<40} {v['examples']:>7}  {v['lines']:>7}  {v['split']}" for r, v in s["runs"].items()] or ["  (none)"]
    lines += ["", "Action mix (lines written):"] + (table(s["actions"], s["train_lines"] + s["valid_lines"]) or ["  (none)"])
    lines += ["", "Why decisions weigh what they do:"] + (table(s["weights"]) or ["  (none)"])
    lines += ["", f"Average prompt {s['avg_prompt_tokens']} tokens, average answer {s['avg_answer_tokens']} tokens "
                  f"(chars/4); longest example about {s['max_example_tokens']} tokens.",
              f"Answers completed to the schema (missing fields given empty values): {s['completed_to_schema']}",
              "", "Lines skipped, by reason:"]
    lines += table(s["skipped"]) or ["  (none)"]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Export mlx-lm chat training data from Swarm World run folders")
    ap.add_argument("runs", nargs="+", help="run folders (teacher episodes or live runs), or folders of them")
    ap.add_argument("--out", required=True, help="e.g. data/student/night1")
    ap.add_argument("--valid-fraction", type=float, default=0.1, help="share of episodes held out for validation")
    ap.add_argument("--seed", type=int, default=0, help="seeds the split, the subsampling and the shuffles")
    ap.add_argument("--allow-mock", action="store_true", help="keep mock decisions too (tests and plumbing only)")
    args = ap.parse_args(argv)
    out = Path(args.out)
    s = export([Path(r) for r in args.runs], out, args.valid_fraction, args.seed, args.allow_mock)
    print(report(s, out))


if __name__ == "__main__":
    main()
