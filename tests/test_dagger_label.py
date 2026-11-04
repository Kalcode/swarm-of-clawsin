import importlib.util
import json
import sys
from pathlib import Path

import pytest
from aiohttp import web

from swarmworld.mind.prompts import INTENTION_SCHEMA, INTENTION_SCHEMA_PLAN

spec = importlib.util.spec_from_file_location("dagger_label",
                                              Path(__file__).resolve().parent.parent / "scripts" / "dagger_label.py")
dl = importlib.util.module_from_spec(spec)
sys.modules["dagger_label"] = dl
spec.loader.exec_module(dl)

LIVE_OK = "20261103-104243"
LATER = "20261104-090000"
OLD = "20261102-230000"
STUDENT = "swarm-student-20261103"
ALL = ["disclose", "plan", "recall"]


def row(tick, creature="c1", model=STUDENT, kind="act", ok=True, noop=False, result_ok=True, messages=True, harness=ALL,
        user=None):
    r = {"tick": tick, "creature": creature, "name": "Ann", "model": model, "kind": kind, "ok": ok,
         "output": {"thought": "x", "action": "gather", "target": "oak tree"}, "harness": harness,
         "result": {"ok": result_ok, "noop": noop, "message": "m"}}
    if messages:
        r["messages"] = [{"role": "system", "content": "You are a creature."},
                         {"role": "user", "content": user or f"tick {tick} {creature}\nRight now:\nWhat now?"}]
    return r


def live(root: Path, name: str, rows: list[dict]) -> Path:
    d = root / name
    d.mkdir(parents=True)
    (d / "thinks.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    return d


def read(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text().splitlines()]


# ------------------------------------------------------------------ licensing
def test_a_run_older_than_since_run_is_refused(tmp_path):
    d = live(tmp_path, OLD, [row(1)])
    with pytest.raises(SystemExit) as e:
        dl.check_runs([d], LIVE_OK)
    assert e.value.code == 1
    dl.check_runs([live(tmp_path, LIVE_OK, [row(1)]), live(tmp_path, LATER, [row(1)])], LIVE_OK)  # equal and later pass


def test_a_run_with_any_gemini_row_is_refused_not_only_students(tmp_path, capsys):
    d = live(tmp_path, LATER, [row(1), row(2, "c2", model="Gemini-3.8-flash", kind="reflect")])
    with pytest.raises(SystemExit) as e:
        dl.check_runs([d], LIVE_OK)
    assert e.value.code == 1
    assert "gemini" in capsys.readouterr().err.lower()


def test_a_gemini_teacher_is_refused(tmp_path):
    d = live(tmp_path, LATER, [row(1)])
    with pytest.raises(SystemExit) as e:
        dl.main([str(d), "--base-url", "http://x/v1", "--model", "gemini-3.8-flash", "--out", str(tmp_path / "o")])
    assert e.value.code == 1


def test_main_refuses_old_run_before_any_request(tmp_path):
    d = live(tmp_path, OLD, [row(1)])
    with pytest.raises(SystemExit) as e:  # nothing listens on this port: a request would fail differently
        dl.main([str(d), "--base-url", "http://127.0.0.1:9/v1", "--model", "gpt-oss:20b", "--out", str(tmp_path / "o")])
    assert e.value.code == 1 and not (tmp_path / "o").exists()


# ------------------------------------------------------------------ choosing
def test_pick_takes_student_acts_with_messages_failures_first_then_limit_then_dedupe(tmp_path):
    rows = [row(1), row(2, result_ok=False), row(3, noop=True), row(4, model="gpt-oss:20b"), row(5, kind="reflect"),
            row(6, messages=False), row(7), row(8, user="same"), row(9, "c2", user="same"), row(10, ok=False, result_ok=False)]
    rows[9].pop("result")
    d = live(tmp_path, LATER, rows)
    got, failures = dl.pick([d], STUDENT, failures_first=True, limit=None, seed=0)
    ticks = [r["tick"] for r in got]
    assert set(ticks[:3]) == {2, 3, 10} and failures == 3  # failures first (a think that failed counts)
    assert 4 not in ticks and 5 not in ticks and 6 not in ticks
    assert len(ticks) == 6 and {8, 9} & set(ticks) and not {8, 9} <= set(ticks)  # identical prompts: once
    again, _ = dl.pick([d], STUDENT, failures_first=True, limit=None, seed=0)
    assert [r["tick"] for r in again] == ticks  # fixed seed
    few, _ = dl.pick([d], STUDENT, failures_first=True, limit=4, seed=0)
    assert [r["tick"] for r in few][:3] == ticks[:3] and len(few) == 4
    plain, n = dl.pick([d], STUDENT, failures_first=False, limit=None, seed=0)
    assert len(plain) == 6


# ------------------------------------------------------------------ labelling against a fake server
class Teacher:
    def __init__(self, fail_first: dict | None = None, bad_for: str | None = None):
        self.bodies = []
        self.fail_first = fail_first or {}
        self.bad_for = bad_for
        self.seen = {}

    async def handle(self, request):
        body = await request.json()
        self.bodies.append(body)
        user = body["messages"][1]["content"]
        self.seen[user] = self.seen.get(user, 0) + 1
        if self.seen[user] <= self.fail_first.get(user, 0):
            return web.Response(status=500, text="boom")
        if self.bad_for and self.bad_for in user:
            return web.json_response({"choices": [{"message": {"content": "not json at all"}}]})
        out = {"thought": "teacher", "action": "explore", "target": "north", "items": [], "text": "", "count": 1,
               "goal": "", "speech": "", "plan": [], "step_done": False}
        return web.json_response({"choices": [{"message": {"content": json.dumps(out)}}], "usage": {}})


async def serve(aiohttp_server, teacher):
    app = web.Application()
    app.router.add_post("/v1/chat/completions", teacher.handle)
    srv = await aiohttp_server(app)
    return f"http://{srv.host}:{srv.port}/v1"


async def test_labelling_writes_a_teacher_episode_the_export_accepts(aiohttp_server, tmp_path):
    t = Teacher()
    url = await serve(aiohttp_server, t)
    d = live(tmp_path, LATER, [row(1), row(2, result_ok=False), row(3, harness=["recall"])])
    out = tmp_path / "runs" / "dagger-x"
    logs = []
    s = await dl.run_labeling([d], url, "gpt-oss:20b", out, student_prefix=STUDENT, since_run=LIVE_OK, failures_first=True,
                              limit=None, concurrency=2, log=logs.append)
    assert s["picked"] == 3 and s["labeled"] == 3 and s["skipped"] == 0 and s["failures_first"] == 1
    ep = out / f"{LATER}-dagger"
    rows = read(ep / "thinks.jsonl")
    assert len(rows) == 3 and (ep / "done").exists()
    assert json.loads((ep / "meta.json").read_text()) == {"model": "gpt-oss:20b", "dagger": True, "source_runs": [LATER],
                                                           "labelled": 3}
    r = rows[0]
    assert r["model"] == "gpt-oss:20b" and r["kind"] == "act" and r["ok"] is True and r["output"]["action"] == "explore"
    assert r["result"] == {"ok": True, "noop": False, "message": "dagger label"} and r["messages"][1]["role"] == "user"
    # schemas as the live brain sends them: the plan one when the plan layer ran
    schemas = {b["messages"][1]["content"]: b["response_format"]["json_schema"]["schema"] for b in t.bodies}
    plan_user = next(r["messages"][1]["content"] for r in rows if r["harness"] == ALL)
    plain_user = next(r["messages"][1]["content"] for r in rows if r["harness"] == ["recall"])
    assert schemas[plan_user] == INTENTION_SCHEMA_PLAN and schemas[plain_user] == INTENTION_SCHEMA
    assert t.bodies[0]["model"] == "gpt-oss:20b"
    # and export_training takes it as teacher decisions
    ex_spec = importlib.util.spec_from_file_location("export_training",
                                                     Path(__file__).resolve().parent.parent / "scripts" / "export_training.py")
    ex = importlib.util.module_from_spec(ex_spec)
    sys.modules["export_training"] = ex
    ex_spec.loader.exec_module(ex)
    es = ex.export([out], tmp_path / "data", log=lambda *_: None)
    assert es["examples"] == 3 and es["weights"] == {"dagger": 3}


async def test_a_failure_is_retried_twice_then_skipped_and_counted(aiohttp_server, tmp_path):
    flaky = row(1, user="flaky")
    dead = row(2, user="dead")
    garbage = row(3, user="garbage")
    fine = row(4, user="fine")
    t = Teacher(fail_first={"flaky": 2, "dead": 99}, bad_for="garbage")
    url = await serve(aiohttp_server, t)
    d = live(tmp_path, LATER, [flaky, dead, garbage, fine])
    s = await dl.run_labeling([d], url, "gpt-oss:20b", tmp_path / "o", student_prefix=STUDENT, since_run=LIVE_OK,
                              failures_first=False, limit=None, concurrency=3, log=lambda *_: None)
    assert s["picked"] == 4 and s["labeled"] == 2 and s["skipped"] == 2
    assert t.seen["flaky"] == 3 and t.seen["dead"] == 3  # first try plus two retries
    users = {r["messages"][1]["content"] for r in read(tmp_path / "o" / f"{LATER}-dagger" / "thinks.jsonl")}
    assert users == {"flaky", "fine"}


async def test_progress_every_100_and_a_summary(aiohttp_server, tmp_path):
    url = await serve(aiohttp_server, Teacher())
    d = live(tmp_path, LATER, [row(i, user=f"u{i}") for i in range(1, 251)])
    logs = []
    s = await dl.run_labeling([d], url, "gpt-oss:20b", tmp_path / "o", student_prefix=STUDENT, since_run=LIVE_OK,
                              failures_first=True, limit=None, concurrency=8, log=logs.append)
    assert s["labeled"] == 250
    assert sum("100" in x or "200" in x for x in logs if "label" in x) >= 2
    text = "\n".join(logs).lower()
    for want in ("picked", "labeled", "skipped", "failures-first", "seconds"):
        assert want in text
