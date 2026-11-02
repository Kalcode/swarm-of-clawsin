import importlib.util
import json
import sys
from pathlib import Path

from swarmworld.mind.prompts import INTENTION_SCHEMA, INTENTION_SCHEMA_PLAN

spec = importlib.util.spec_from_file_location("export_training",
                                              Path(__file__).resolve().parent.parent / "scripts" / "export_training.py")
ex = importlib.util.module_from_spec(spec)
sys.modules["export_training"] = ex  # its dataclass looks itself up there
spec.loader.exec_module(ex)

ALL = ["disclose", "plan", "recall"]


def answer(action="gather", target="oak tree", **more):
    out = {"thought": f"I'll {action}.", "action": action, "target": target, "items": [], "text": "", "count": 1,
           "goal": "", "speech": "", "plan": [], "step_done": False}
    out.update(more)
    return out


def act(tick, creature="c1", model="gpt-oss:20b", output=None, ok=True, noop=False, think_ok=True, prompt=True,
        feel="fed", harness=ALL, kind="act"):
    line = {"tick": tick, "creature": creature, "name": "Ann", "model": model, "kind": kind, "ok": think_ok,
            "output": answer() if output is None else output, "error": None if think_ok else "HTTP 500",
            "harness": harness, "result": {"ok": ok, "noop": noop, "message": "something"} if think_ok else None}
    if not think_ok:
        line.pop("result")
    if prompt:
        line["messages"] = [{"role": "system", "content": "You are a creature."},
                            {"role": "user", "content": f"tick {tick} {creature}\nRight now:\nYou feel {feel}.\nWhat now?"}]
    return line


def run(root: Path, name: str, thinks: list[dict], events: list[dict] = (), meta: dict | None = None, done=True) -> Path:
    d = root / name
    d.mkdir(parents=True)
    (d / "thinks.jsonl").write_text("".join(json.dumps(t) + "\n" for t in thinks))
    (d / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
    if meta is not None:
        (d / "meta.json").write_text(json.dumps(meta))
        if done:
            (d / "done").write_text("{}")
    return d


def read(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def export(dirs, out, **kw):
    kw.setdefault("log", lambda *_: None)
    return ex.export([Path(d) for d in dirs], Path(out), **kw)


def all_lines(out: Path) -> list[dict]:
    return read(out / "train.jsonl") + read(out / "valid.jsonl")


def user_of(line: dict) -> str:
    return line["messages"][1]["content"]


# ------------------------------------------------------------------ who may teach
def test_only_gpt_oss_and_qwen_teach_gemini_never_mock_only_when_asked(tmp_path):
    thinks = [act(1, "c1", "gpt-oss:20b"), act(2, "c2", "qwen3.5-9b"), act(3, "c3", "gemini-3.8-flash"),
              act(4, "c4", "google/gemma-3-12b"), act(5, "c5", "mock"), act(6, "c6", "gemma-4-e4b"),
              act(7, "c7", "Qwen3.5-4B-MLX-4bit"), act(8, "c8", "GPT-OSS-120B")]
    d = run(tmp_path, "r1", thinks)
    s = export([d], tmp_path / "out")
    assert sorted(s["models"]) == ["GPT-OSS-120B", "Qwen3.5-4B-MLX-4bit", "gpt-oss:20b", "qwen3.5-9b"]
    assert s["skipped"]["Gemini/Google (never used)"] == 2
    assert s["skipped"]["mock (needs --allow-mock)"] == 1
    assert s["skipped"]["teacher not allowed"] == 1
    s = export([d], tmp_path / "out2", allow_mock=True)
    assert "mock" in s["models"] and not any("gemini" in m or "google" in m for m in s["models"])


def test_a_run_on_googles_server_is_excluded_whatever_its_lines_say(tmp_path):
    d = run(tmp_path, "r1", [act(1, model="qwen-ish")], meta={"model": "qwen-ish", "base_url_host":
                                                             "generativelanguage.googleapis.com"})
    s = export([d], tmp_path / "out")
    assert s["examples"] == 0 and s["skipped"]["Gemini/Google (never used)"] == 1


# ------------------------------------------------------------------ what counts as a decision
def test_failed_noop_unparsed_and_promptless_lines_are_skipped_and_counted(tmp_path):
    thinks = [act(1), act(2, ok=False), act(3, noop=True), act(4, think_ok=False), act(5, prompt=False),
              act(6, kind="reflect", output="I reflected."),
              {**act(7), "result": {"ok": False, "parsed": False}, "output": "not json"},
              act(8, output=answer(action="fly")), act(9, output=answer(count="lots"))]
    s = export([run(tmp_path, "r1", thinks)], tmp_path / "out")
    assert s["examples"] == 1
    sk = s["skipped"]
    assert sk["action failed"] == 1 and sk["no-op"] == 1 and sk["think failed"] == 1 and sk["no full prompt"] == 1
    assert sk["not an act decision"] == 1 and sk["unparsed answer"] == 1 and sk["off-schema answer"] == 2


def test_an_unfinished_teacher_episode_is_skipped(tmp_path):
    d = run(tmp_path, "20261102-230000-gpt-oss-20b-s100", [act(1), act(5)], meta={"model": "gpt-oss:20b"}, done=False)
    s = export([d], tmp_path / "out")
    assert s["examples"] == 0 and s["skipped"]["unfinished episode"] == 2


def test_a_parent_folder_means_its_episodes_but_not_the_ones_moved_aside(tmp_path):
    root = tmp_path / "teacher"
    run(root, "20261102-230000-gpt-oss-20b-s100", [act(1)], meta={"model": "gpt-oss:20b"})
    run(root, "20261102-230500-gpt-oss-20b-s101", [act(1, "c9")], meta={"model": "gpt-oss:20b"})
    run(root, "20261102-220000-gpt-oss-20b-s101.partial", [act(1, "c8")], meta={"model": "gpt-oss:20b"})
    s = export([root], tmp_path / "out")
    assert sorted(s["runs"]) == ["20261102-230000-gpt-oss-20b-s100", "20261102-230500-gpt-oss-20b-s101"]


# ------------------------------------------------------------------ chat format
def test_lines_are_mlx_chat_examples_with_the_schema_answer(tmp_path):
    thinks = [act(1), act(5, "c2", harness=["recall"], output={k: v for k, v in answer().items() if k not in ("plan", "step_done")}),
              act(9, "c3", "mock", output={"thought": "x", "action": "eat", "target": "berries", "items": [], "text": "",
                                           "count": 1, "goal": ""})]  # the mock leaves out speech, plan, step_done
    s = export([run(tmp_path, "r1", thinks)], tmp_path / "out", allow_mock=True)
    lines = all_lines(tmp_path / "out")
    assert len(lines) == 3 and s["completed_to_schema"] == 1
    for line in lines:
        assert list(line) == ["messages"]
        assert [m["role"] for m in line["messages"]] == ["system", "user", "assistant"]
        assert all(set(m) == {"role", "content"} and isinstance(m["content"], str) for m in line["messages"])
        got = json.loads(line["messages"][2]["content"])
        schema = INTENTION_SCHEMA if "c2" in user_of(line) else INTENTION_SCHEMA_PLAN
        assert list(got) == list(schema["properties"])  # every field, in the schema's order
    mock = next(json.loads(x["messages"][2]["content"]) for x in lines if "c3" in user_of(x))
    assert mock["speech"] == "" and mock["plan"] == [] and mock["step_done"] is False


# ------------------------------------------------------------------ duplicates and weights
def test_exact_duplicates_are_removed_before_weighting(tmp_path):
    same = act(1)
    s = export([run(tmp_path, "r1", [same, {**same, "tick": 30}, act(60)])], tmp_path / "out")
    assert s["examples"] == 2 and s["skipped"]["duplicate"] == 1


def test_weights_reward_what_led_somewhere_and_damp_repeats():
    thinks = [act(10, "c1", output=answer("combine", "", items=["stick", "stone"])),   # a discovery follows
              act(20, "c1", output=answer("craft", "rope")),                            # a craft follows
              act(30, "c1", output=answer("eat", "berries"), feel="very hungry"),       # eating while hungry
              act(40, "c1", output=answer("eat", "fish"), feel="fed"),                  # not hungry: plain
              act(50, "c1", output=answer("walk_to", "boulder", step_done=True)),       # finished a plan step
              act(60, "c1", output=answer("gather", "grass")),
              act(70, "c1", output=answer("gather", "grass")),
              act(80, "c1", output=answer("gather", "grass")),
              act(90, "c1", output=answer("gather", "grass")),
              act(95, "c2", output=answer("craft", "rope"))]                            # c1's craft isn't c2's
    events = [{"tick": 10, "kind": "discover", "actor": "c1"}, {"tick": 20, "kind": "craft", "actor": "c1"},
              {"tick": 96, "kind": "say", "actor": "c2"}]
    w = [(e.weight, e.why) for e in ex.weigh(thinks, events)]
    assert w == [(4, "discovery"), (3, "craft"), (2, "ate hungry"), (1, ""), (2, "plan step"), (1, ""),
                 (0.5, "repeat"), (0.25, "repeat"), (0.25, "repeat"), (1, "")]


def test_weights_apply_by_repetition_in_train(tmp_path):
    runs = [run(tmp_path, f"r{i}", [act(10, f"c{i}", output=answer("craft", "rope")), act(20, f"c{i}")],
                [{"tick": 10, "kind": "craft", "actor": f"c{i}"}]) for i in range(2)]
    s = export(runs, tmp_path / "out", valid_fraction=0.5, seed=3)
    train = read(tmp_path / "out" / "train.jsonl")
    crafts = [x for x in train if json.loads(x["messages"][2]["content"])["action"] == "craft"]
    assert len(crafts) == 3  # weight 3: three copies
    assert len(train) == 4 and s["valid_lines"] == 2  # validation is not weighted


def test_fractional_weights_subsample_with_a_seed():
    rng = ex.random.Random(1)
    kept = sum(ex.copies(0.25, rng) for _ in range(4000))
    assert 850 < kept < 1150
    assert [ex.copies(w, ex.random.Random(0)) for w in (1, 2, 3)] == [1, 2, 3]


# ------------------------------------------------------------------ split
def test_split_is_by_episode_and_seeded(tmp_path):
    runs = [run(tmp_path, f"r{i:02d}", [act(t, f"c{i}") for t in range(10, 60, 10)]) for i in range(10)]
    s = export(runs, tmp_path / "a", valid_fraction=0.2, seed=7)
    valid_runs = {n for n, r in s["runs"].items() if r["split"] == "valid"}
    assert len(valid_runs) == 2
    train_creatures = {user_of(x).split()[2] for x in read(tmp_path / "a" / "train.jsonl")}
    valid_creatures = {user_of(x).split()[2] for x in read(tmp_path / "a" / "valid.jsonl")}
    assert train_creatures and valid_creatures and not train_creatures & valid_creatures
    again = export(runs, tmp_path / "b", valid_fraction=0.2, seed=7)
    assert again["runs"] == s["runs"]
    assert (tmp_path / "a" / "train.jsonl").read_text() == (tmp_path / "b" / "train.jsonl").read_text()


def test_one_episode_goes_to_train_with_a_warning(tmp_path):
    said = []
    s = export([run(tmp_path, "r1", [act(1), act(5, output=answer("explore", "north"))])], tmp_path / "out", log=said.append)
    assert s["train_lines"] == 2 and s["valid_lines"] == 0
    assert any("only one episode" in x for x in said)


# ------------------------------------------------------------------ the command
def test_main_writes_files_and_prints_a_summary(tmp_path, capsys):
    a = run(tmp_path, "r1", [act(1), act(5, output=answer("eat", "berries"))])
    b = run(tmp_path, "r2", [act(1, "c2"), act(5, "c2", model="gemini-3.8-flash")])
    ex.main([str(a), str(b), "--out", str(tmp_path / "data" / "night1")])
    out = capsys.readouterr().out.lower()
    for want in ("by source model", "by run", "action mix", "prompt", "answer", "skipped", "gemini/google"):
        assert want in out
    assert (tmp_path / "data" / "night1" / "train.jsonl").exists() and (tmp_path / "data" / "night1" / "valid.jsonl").exists()
    assert json.loads((tmp_path / "data" / "night1" / "summary.json").read_text())["examples"] == 3


def test_lengths_are_per_example_in_chars_over_four(tmp_path):
    line = act(1)
    line["messages"] = [{"role": "system", "content": "s" * 400}, {"role": "user", "content": "u" * 800}]
    s = export([run(tmp_path, "r1", [line])], tmp_path / "out")
    answer_chars = len(read(tmp_path / "out" / "train.jsonl")[0]["messages"][2]["content"])
    assert s["avg_prompt_tokens"] == 300 and s["avg_answer_tokens"] == answer_chars // 4
    assert s["max_example_tokens"] == (1200 + answer_chars) // 4
