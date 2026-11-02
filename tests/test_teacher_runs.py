import importlib.util
import json
from pathlib import Path

import pytest

from swarmworld.node.brain import MockBrain
from swarmworld.server.state import ServerState

spec = importlib.util.spec_from_file_location("teacher_runs", Path(__file__).resolve().parent.parent / "scripts" / "teacher_runs.py")
tr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tr)


class NullWS:
    closed = False

    async def send_json(self, _):
        pass


def lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def episodes(out: Path) -> list[Path]:
    return sorted(p for p in out.iterdir() if p.is_dir() and not p.name.endswith(".partial"))


async def night(out: Path, *more: str) -> dict:
    return await tr.night(tr.parse_args(["--mock", "--seeds", "11-12", "--creatures", "2", "--ticks", "40",
                                         "--out", str(out), *more]), log=lambda *_: None)


# ------------------------------------------------------------------ think logs
def test_think_log_carries_prompts_only_when_asked(tmp_path):
    for flag, folder in ((False, tmp_path / "live"), (True, tmp_path / "teacher")):
        st = ServerState(seed=7, run_dir=folder, log_prompts=flag)
        node, _ = st.register_node(NullWS(), {"node": "t", "slots": 2, "models": [{"tag": "mock", "creatures": 1}]})
        job = next(job for _, job in st.plan_dispatch())
        st.handle_result(node, {"job": job["job"], "ok": True, "output": {"action": "say", "text": "hello"}})
        st.close()
        line = lines(folder / "thinks.jsonl")[-1]
        if flag:
            assert line["messages"] == job["messages"]
            assert [m["role"] for m in line["messages"]] == ["system", "user"]
        else:
            assert "messages" not in line  # live logs don't grow


def test_the_live_server_logs_prompts_only_with_the_flag():
    from swarmworld.server.app import STATE, create_app

    assert create_app(start_loop=False)[STATE].log_prompts is False
    assert create_app(start_loop=False, log_prompts=True)[STATE].log_prompts is True


# ------------------------------------------------------------------ seeds
def test_seed_ranges_and_lists():
    assert tr.parse_seeds("100-103") == [100, 101, 102, 103]
    assert tr.parse_seeds("5,7, 9-10") == [5, 7, 9, 10]
    with pytest.raises(ValueError):
        tr.parse_seeds("9-3")


def test_folder_names_are_safe_everywhere():
    assert tr.folder_tag("gpt-oss:20b") == "gpt-oss-20b"
    assert tr.folder_tag("Qwen3.5-9B-MLX-4bit") == "qwen3.5-9b"


# ------------------------------------------------------------------ episodes
async def test_mock_night_writes_episodes_skips_finished_and_redoes_unfinished(tmp_path):
    out = tmp_path / "teacher"
    first = await night(out)
    assert sorted(r["seed"] for r in first["done"]) == [11, 12]
    eps = episodes(out)
    assert len(eps) == 2 and {p.name.rsplit("-s", 1)[1] for p in eps} == {"11", "12"}
    for ep in eps:
        assert {"thinks.jsonl", "events.jsonl", "meta.json", "done"} <= {p.name for p in ep.iterdir()}
        meta = json.loads((ep / "meta.json").read_text())
        assert meta["model"] == "mock" and meta["creatures"] == 2 and meta["ticks"] == 40
        assert meta["harness"] == ["disclose", "plan", "recall"] and meta["recall"] == "keywords only"
        assert set(meta["packs"]) >= {"play", "sound", "weather"} and "git_commit" in meta and "seed" in meta
        thinks = lines(ep / "thinks.jsonl")
        acts = [t for t in thinks if t["kind"] == "act"]
        assert acts and all(t["messages"][0]["role"] == "system" and t["messages"][1]["role"] == "user" for t in acts)
        assert all(sorted(t["harness"]) == ["disclose", "plan", "recall"] for t in acts)  # every layer, every creature
        assert all("result" in t and t["model"] == "mock" for t in acts)
        assert lines(ep / "events.jsonl")
        done = json.loads((ep / "done").read_text())
        assert done["thinks"] > 0 and 0 <= done["ok_rate"] <= 1

    again = await night(out)
    assert again["done"] == [] and sorted(again["skipped"]) == [11, 12]
    assert episodes(out) == eps

    (eps[0] / "done").unlink()  # as if the night stopped in the middle of this one
    redo = await night(out)
    assert [r["seed"] for r in redo["done"]] == [int(eps[0].name.rsplit("-s", 1)[1])]
    assert (out / (eps[0].name + ".partial")).is_dir()
    assert len(episodes(out)) == 2 and all((p / "done").exists() for p in episodes(out))


async def test_other_teachers_seeds_are_left_alone(tmp_path):
    """Two writers into one folder: an unfinished episode of another model (or another seed) is not ours to touch."""
    out = tmp_path / "teacher"
    theirs = out / "20261102-230000-gpt-oss-20b-s11"
    theirs.mkdir(parents=True)
    (theirs / "thinks.jsonl").write_text("")
    other_seed = out / "20261102-230000-mock-s99"
    other_seed.mkdir()
    r = await night(out)
    assert sorted(x["seed"] for x in r["done"]) == [11, 12]
    assert theirs.is_dir() and other_seed.is_dir() and not list(out.glob("*.partial"))


async def test_ticks_and_ok_rate_in_the_episode_line(tmp_path):
    printed = []
    await tr.night(tr.parse_args(["--mock", "--seeds", "3", "--creatures", "2", "--ticks", "30", "--out", str(tmp_path)]),
                   log=printed.append)
    line = next(p for p in printed if p.startswith("seed 3:"))
    assert "min" in line and "thinks" in line and "ok" in line and "milestones" in line


# ------------------------------------------------------------------ failures
class Flaky:
    """Fails the first `fails` thinks (as a dropped connection would), then answers like the mock."""

    def __init__(self, fails: int):
        self.fails = fails
        self.calls = 0
        self.inner = MockBrain(1)
        self.model = "flaky"

    async def think(self, messages, schema, max_tokens):
        self.calls += 1
        if self.calls <= self.fails:
            return False, None, "ClientConnectorError: connection refused", {}
        return await self.inner.think(messages, schema, max_tokens)

    async def close(self):
        pass


async def test_a_failed_think_is_retried_with_backoff_not_skipped():
    slept = []

    async def sleep(s):
        slept.append(s)

    brain = Flaky(2)
    ok, output, error, _ = await tr.think_with_retry(brain, {"messages": [{"role": "user", "content": "Right now: x"}],
                                                             "schema": {"type": "object"}, "max_tokens": 50,
                                                             "creature": "c1"}, sleep=sleep, log=lambda *_: None)
    assert ok and isinstance(output, dict) and error is None
    assert brain.calls == 3 and slept == [5, 15]


async def test_a_think_that_keeps_failing_gives_up_after_ten_minutes():
    now = [0.0]
    slept, said = [], []

    async def sleep(s):
        slept.append(s)
        now[0] += s

    brain = Flaky(10_000)
    ok, _, error, _ = await tr.think_with_retry(brain, {"messages": [], "schema": None, "max_tokens": 50, "creature": "c1"},
                                                sleep=sleep, clock=lambda: now[0], log=said.append)
    assert not ok and "gave up" in error
    assert slept[:4] == [5, 15, 60, 60] and set(slept[2:]) == {60}
    assert 600 <= now[0] < 700
    assert any("gave up" in s for s in said)


async def test_retries_inside_an_episode_leave_no_failed_thinks(tmp_path):
    async def no_wait(_):
        pass

    brain = Flaky(3)
    r = await tr.episode(brain, "flaky", seed=5, creatures=2, ticks=30, root=tmp_path, concurrency=1, base_url=None,
                         log=lambda *_: None, sleep=no_wait)
    thinks = lines(Path(r["dir"]) / "thinks.jsonl")
    assert brain.calls > 3 and thinks and all(t["ok"] for t in thinks)


# ------------------------------------------------------------------ recall
async def test_teacher_recall_is_keywords_only_even_with_a_voyage_key(tmp_path, monkeypatch):
    import swarmworld.mind.recall as recall

    monkeypatch.setenv("VOYAGE_API_KEY", "sk-test-not-real")

    def refuse(*a, **k):
        raise AssertionError("teacher runs must never build an embedding client")

    monkeypatch.setattr(recall.VoyageEmbedder, "__init__", refuse)
    monkeypatch.setattr(recall, "embed_pending", refuse)
    st = tr.make_state(5, tmp_path / "s")
    assert st.embedder is None
    st.close()
    r = await tr.episode(MockBrain(1), "mock", seed=5, creatures=2, ticks=30, root=tmp_path, concurrency=2,
                         base_url=None, log=lambda *_: None)
    assert json.loads((Path(r["dir"]) / "meta.json").read_text())["recall"] == "keywords only"


def test_gemini_is_never_a_teacher():
    with pytest.raises(SystemExit):
        tr.check_teacher("gemini-3.8-flash", "https://generativelanguage.googleapis.com/v1beta/openai")
    with pytest.raises(SystemExit):
        tr.check_teacher("some-model", "https://generativelanguage.googleapis.com/v1beta/openai")
    tr.check_teacher("gpt-oss:20b", "http://192.168.50.42:11434/v1")
