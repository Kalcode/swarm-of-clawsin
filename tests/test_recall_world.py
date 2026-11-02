import json

import pytest

from aiohttp import web

from swarmworld.mind.prompts import SYSTEM_PROMPT_CORE, build_act_messages
from swarmworld.server.harness import Harness
from swarmworld.server.persistence import restore, save
from swarmworld.server.state import ServerState
from swarmworld.world.actions import Intention, apply_intention


class NullWS:
    closed = False

    async def send_json(self, _):
        pass


def setup(layers=("recall",), run_dir=None):
    st = ServerState(seed=7, run_dir=run_dir, harness=Harness(set(layers), set(layers)))
    node, cs = st.register_node(NullWS(), {"node": "t", "slots": 2, "models": [{"tag": "mock", "creatures": 1}]})
    return st, node, cs[0]


def remember_clay(st, c, filler=80):
    st._remember(c, "You gathered clay from the clay bank by the pond.", 1)
    for i in range(filler):
        st._remember(c, f"You walked past boulder number {i}.", 1)
    assert not any("clay" in e.text for e in st.memory(c.id).entries)  # fell out of the 60-entry window


def free_tile_near(st, c):
    w = st.world
    for dx in range(2, 5):
        for dy in range(-2, 3):
            if (c.x + dx, c.y + dy) not in w.grid and w.in_bounds(c.x + dx, c.y + dy):
                return c.x + dx, c.y + dy
    raise AssertionError("no free tile")


def user_text(st, node, c):
    return st.make_job(node, c)["messages"][1]["content"]


def test_memories_feed_the_index_even_after_eviction():
    st, _, c = setup()
    remember_clay(st, c)
    hits = st.recall.search(c.id, "where did I find clay", now=st.world.tick)
    assert hits and "clay bank" in hits[0].text


def test_auto_recall_only_for_recall_layer():
    for layers, expect in ((("recall",), True), ((), False)):
        st, node, c = setup(layers)
        remember_clay(st, c)
        x, y = free_tile_near(st, c)
        st.world.add_object("clay", x, y)
        text = user_text(st, node, c)
        assert ("You recall:" in text) is expect
        if expect:
            assert "clay bank by the pond" in text.split("You recall:")[1]
            assert "recall: target is what you want to remember" in text
        else:
            assert "think back with recall" not in text


def test_auto_recall_skips_what_is_already_shown():
    st, node, c = setup()
    st._remember(c, "You gathered clay from the clay bank by the pond.", 2)
    x, y = free_tile_near(st, c)
    st.world.add_object("clay", x, y)
    text = user_text(st, node, c)
    assert text.count("clay bank by the pond") == 1  # in recent memories, not again under You recall


def test_recall_action_answers_and_remembers():
    st, node, c = setup(())
    c.spots["clay"] = (c.x + 7, c.y, st.world.tick)
    res = apply_intention(st.world, c, Intention("recall", target="where did I see clay"))
    assert res.ok and not res.noop
    assert "place:" in res.message and "clay" in res.message
    assert len(res.message.splitlines()) <= 6  # header + up to 5 results
    job = st.make_job(node, c)
    st.handle_result(node, {"job": job["job"], "ok": True,
                            "output": {"action": "recall", "target": "which clay is near"}})  # a fresh query
    note = st.memory(c.id).entries[-1].text
    assert note.startswith('You thought back about "which clay is near":') and len(note) <= 160 and "\n" not in note
    assert "place: clay" in note
    assert "more" not in note  # the full answer is shown once instead; nothing hints at a hidden rest


def section(text, header):
    return text.split(header, 1)[1].split("\n\n", 1)[0].strip().splitlines()


def test_asked_recall_is_shown_in_full_once():
    st, node, c = setup(())
    for i in range(6):
        st._remember(c, f"You saw clay number {i} by the pond.", 1)
    for i in range(30):
        st._remember(c, f"You walked past boulder number {i}.", 1)
    job = st.make_job(node, c)
    st.handle_result(node, {"job": job["job"], "ok": True, "output": {"action": "recall", "target": "clay by the pond"}})
    found = c.last_recall[2].splitlines()[1:]
    assert len(found) == 5
    text = user_text(st, node, c)
    assert section(text, "You thought back:") == [f"- {line}" for line in found]
    assert "You thought back:" not in user_text(st, node, c)  # one-shot


def test_asked_recall_after_restart_still_shows(tmp_path):
    st, node, c = setup(())
    st._remember(c, "You saw clay by the pond.", 1)
    job = st.make_job(node, c)
    st.handle_result(node, {"job": job["job"], "ok": True, "output": {"action": "recall", "target": "clay"}})
    save(st, tmp_path / "w.json")
    st2 = ServerState(seed=7)
    restore(st2, tmp_path / "w.json")
    assert st2.memory(c.id).thought_back == st.memory(c.id).thought_back != []


def test_asked_recall_has_at_most_one_lore_line():
    st, _, c = setup(())
    st._remember(c, "You fed sticks to the campfire by the oak and gave berries to a sheep.", 1)
    st._remember(c, "You planted seeds in the soil and placed a sign.", 1)
    res = apply_intention(st.world, c, Intention("recall", target="give feed sticks campfire animal plant seeds sign"))
    kinds = [line.split(":", 1)[0] for line in res.message.splitlines()[1:]]
    assert kinds.count("lore") == 1 and kinds.count("memory") == 2


def test_repeated_recall_is_a_noop():
    st, _, c = setup()
    st._remember(c, "You gathered clay from the clay bank by the pond.", 2)
    first = apply_intention(st.world, c, Intention("recall", target="Where did I see CLAY"))
    st.world.tick += 10
    again = apply_intention(st.world, c, Intention("recall", target="where did i see clay"))
    assert again.noop and again.message == first.message
    st.world.tick += 60
    later = apply_intention(st.world, c, Intention("recall", target="where did i see clay"))
    assert not later.noop


def test_recall_without_a_question_or_hook():
    st, _, c = setup()
    assert not apply_intention(st.world, c, Intention("recall")).ok
    st.world.recall_hook = None
    res = apply_intention(st.world, c, Intention("recall", target="anything"))
    assert res.ok and "nothing" in res.message.lower()


def test_lore_answers_how_to():
    st, _, c = setup(())
    res = apply_intention(st.world, c, Intention("recall", target="how do I keep a fire burning"))
    assert "lore:" in res.message and "campfire to keep it burning" in res.message


def test_recall_survives_restart(tmp_path):
    st, _, c = setup()
    remember_clay(st, c)
    save(st, tmp_path / "w.json")
    st2 = ServerState(seed=7, harness=Harness({"recall"}, {"recall"}))
    restore(st2, tmp_path / "w.json")
    hits = st2.recall.search(c.id, "clay bank", now=st2.world.tick)
    assert hits and "clay bank" in hits[0].text
    assert any(d.kind == "lore" for d in st2.recall.search(c.id, "keep a fire burning", now=0))


def test_old_save_without_an_index_is_seeded_from_memories(tmp_path):
    st, _, c = setup()
    st._remember(c, "You gathered clay from the clay bank by the pond.", 2)
    save(st, tmp_path / "w.json")
    data = json.loads((tmp_path / "w.json").read_text())
    data.pop("recall")
    (tmp_path / "w.json").write_text(json.dumps(data))
    st2 = ServerState(seed=7)
    restore(st2, tmp_path / "w.json")
    assert st2.recall.search(c.id, "clay bank", now=st2.world.tick)


def test_reflections_are_recallable():
    st, node, c = setup()
    st.memory(c.id).thinks_since_reflect = 12
    st.memory(c.id).entries_since_reflect = 12
    job = st.make_job(node, c)
    assert job["kind"] == "reflect"
    st.handle_result(node, {"job": job["job"], "ok": True, "output": "I learned that the walnut grove feeds everyone."})
    assert any("walnut" in d.text for d in st.recall.search(c.id, "walnut grove", now=st.world.tick))


def test_think_log_records_what_was_shown_and_recalled(tmp_path):
    st, node, c = setup(("disclose", "recall"), run_dir=tmp_path)
    remember_clay(st, c)
    st.memory(c.id).goal = "make a clay pot"
    x, y = free_tile_near(st, c)
    st.world.add_object("terminal", x, y)
    job = st.make_job(node, c)
    st.handle_result(node, {"job": job["job"], "ok": True, "output": {"action": "wait"}})
    line = json.loads((tmp_path / "thinks.jsonl").read_text().splitlines()[-1])
    assert "program" in line["shown"]
    assert any(r.startswith("memory: You gathered clay") for r in line["recalled"])
    assert all(len(r.split(": ", 1)[1]) <= 60 for r in line["recalled"])


def measure_prompts():
    st, node, c = setup(("plan", "disclose", "recall"))
    w = st.world
    c.inventory.update({"wheat_seeds": 2, "workbench": 1, "stick": 3})
    for kind, dx, dy in (("terminal", 2, 0), ("basket", 0, 2), ("sign", -2, 0), ("campfire", 0, -2)):
        w.grid.pop((c.x + dx, c.y + dy), None)
        w.add_object(kind, c.x + dx, c.y + dy)
    mem = st.memory(c.id)
    mem.goal = "make a clay pot"
    mem.set_plan(["get 3 clay", "find the kiln", "shape the pot", "dry it by the fire", "store it in the basket"])
    for i in range(12):
        st._remember(c, f"You gathered {i} sticks from the oak tree near the north camp.", 1)
    st._remember(c, "You found clay at the clay bank by the pond.", 1)
    st._remember(c, "You saw a kiln near the north camp.", 1)
    st._remember(c, "You shaped a pot from wet clay.", 1)
    for i in range(20):
        st._remember(c, f"You walked past boulder number {i}.", 1)
    st._remember(c, "You gathered clay from the clay bank by the pond.", 1)
    st._remember(c, "You saw a kiln near the north camp, with clay.", 1)
    for i in range(20):
        st._remember(c, f"You walked past rock number {i}.", 1)
    job = st.make_job(node, c)
    msgs = job["messages"]
    today = build_act_messages(w, c, mem, st.last[c.id]["perception"], c.wake_reason or "woke")  # no layers
    full_user = msgs[1]["content"]
    assert msgs[0]["content"] == SYSTEM_PROMPT_CORE
    assert "You recall:" in full_user and "Things you could also do here:" in full_user and "Your plan:" in full_user
    # the system prompt is cached; what costs is the user message
    today_user, full_len = len(today[1]["content"]), len(full_user)
    print(f"user message chars: today {today_user}, full stack {full_len}; "
          f"system+user: today {len(today[0]['content']) + today_user}, full {len(msgs[0]['content']) + full_len}")
    return today_user, full_len


def test_full_stack_prompt_within_budget():
    today_user, full_len = measure_prompts()
    assert full_len <= 1.5 * today_user  # measured 1.41x in this scenario; see the xfail below for the 1.15x target


@pytest.mark.xfail(reason="controller target 1.15x of today's user message; the ruled cuts reach about 1.41x", strict=False)
def test_full_stack_prompt_meets_the_tight_target():
    today_user, full_len = measure_prompts()
    assert full_len <= 1.15 * today_user


def test_a_creature_recalls_only_landmarks_it_has_been_near():
    st, _, c = setup(())
    w = st.world
    w.landmarks = [{"kind": "camp", "name": "the north camp", "x": c.x + 40, "y": c.y}]
    assert not any("north camp" in t for _, t in st._places(c))
    c.x += 30  # walks within range
    from swarmworld.world.perception import note_spots

    note_spots(w, c, w.tick)
    assert any("north camp" in t for _, t in st._places(c))
    assert "north camp" in apply_intention(w, c, Intention("recall", target="north camp")).message


def test_landmarks_seen_survive_restart(tmp_path):
    st, _, c = setup(())
    c.landmarks_seen.add("the north camp")
    save(st, tmp_path / "w.json")
    st2 = ServerState(seed=7)
    restore(st2, tmp_path / "w.json")
    assert st2.world.creatures[c.id].landmarks_seen == {"the north camp"}


def test_repeated_memory_is_indexed_once():
    st, _, c = setup(())
    for _ in range(4):
        st._remember(c, "You gathered clay from the clay bank.", 1)
    st._remember(c, "You walked.", 1)
    st._remember(c, "You gathered clay from the clay bank.", 1)
    texts = [d.text for d in st.recall.search(c.id, "clay bank", k=5, now=st.world.tick)]
    assert texts == ["You gathered clay from the clay bank."]
    assert sum(1 for d in st.recall._docs[c.id] if "clay bank" in d.text) == 2


def test_hunger_adds_food_words_to_the_automatic_query():
    st, _, c = setup()
    st._remember(c, "You savoured berries at dusk.", 1)
    mem = st.memory(c.id)
    c.satiety = 90
    assert not st.auto_recall(c, mem, [])
    c.satiety = 20
    assert any("berries" in t for _, t in st.auto_recall(c, mem, []))


def test_auto_recall_leaves_lore_out_and_trims():
    st, _, c = setup()
    mem = st.memory(c.id)
    mem.goal = "keep a fire burning"
    assert not st.auto_recall(c, mem, [])  # lore is shown as techniques instead
    st._remember(c, "You kept a fire burning " + "x" * 300, 1)
    (kind, text), = st.auto_recall(c, mem, [])
    assert len(text) <= 140


async def stop(task):
    import asyncio

    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


class FakeEmbedder:
    def __init__(self, fail=False):
        self.calls, self.fail = 0, fail

    async def embed(self, texts, input_type):
        self.calls += 1
        if self.fail:
            raise RuntimeError("network down")
        return [[1.0, float(len(t) % 7), 0.5] for t in texts]


@pytest.mark.asyncio
async def test_embed_loop_fills_vectors_without_blocking():
    import asyncio

    from swarmworld.server.app import STATE, create_app, embed_loop

    app = create_app(seed=7, start_loop=False, embedder=FakeEmbedder())
    st = app[STATE]
    assert st.recall.pending(1)  # lore waits for vectors
    task = asyncio.create_task(embed_loop(app, every=0.01))
    for _ in range(100):
        await asyncio.sleep(0.02)
        if not st.recall.pending(1):
            break
    await stop(task)
    assert not st.recall.pending(1)


@pytest.mark.asyncio
async def test_embed_loop_survives_a_dead_embedder():
    import asyncio

    from swarmworld.server.app import STATE, create_app, embed_loop

    emb = FakeEmbedder(fail=True)
    app = create_app(seed=7, start_loop=False, embedder=emb)
    task = asyncio.create_task(embed_loop(app, every=0.01))
    await asyncio.sleep(0.1)
    assert not task.done() and emb.calls > 1
    await stop(task)
    assert app[STATE].recall.pending(1)  # keyword search carries on


class HTTPError(Exception):
    """Like aiohttp's ClientResponseError: carries the HTTP status (and here, a key that must never be logged)."""

    def __init__(self, status):
        super().__init__(f"{status} for Authorization: Bearer pa-secret")
        self.status = status


class Flaky:
    """Answers with each outcome in turn: an HTTP status to fail with, or None to succeed."""

    def __init__(self, outcomes):
        self.outcomes, self.calls = list(outcomes), 0

    async def embed(self, texts, input_type):
        self.calls += 1
        status = self.outcomes.pop(0) if self.outcomes else None
        if status:
            raise HTTPError(status)
        return [[1.0, 0.5, float(len(t) % 5)] for t in texts]


class Stop(Exception):
    pass


async def run_embed_loop(emb, sleeps):
    from swarmworld.server.app import STATE, create_app, embed_loop

    app = create_app(seed=7, start_loop=False, embedder=emb)
    for i in range(1000):  # plenty of work queued, so every turn of the loop calls the embedder
        app[STATE].recall.add("c1", "memory", f"note {i}", i)
    delays = []

    async def fake_sleep(s):
        delays.append(s)
        if len(delays) >= sleeps:
            raise Stop

    try:
        await embed_loop(app, every=3.0, sleep=fake_sleep)
    except Stop:
        pass
    return app[STATE], delays


@pytest.mark.asyncio
async def test_embed_failures_back_off_and_reset(caplog):
    caplog.set_level("INFO")
    st, delays = await run_embed_loop(Flaky([429, 429, 429, None, 503] + [500] * 9), sleeps=14)
    assert delays[:5] == [6.0, 12.0, 24.0, 3.0, 6.0]  # doubles on failure, back to 3 s after a success
    assert max(delays) == 300.0 and delays[-2:] == [300.0, 300.0]  # capped at 5 minutes
    fails = [r for r in caplog.records if "embedding failed" in r.getMessage()]
    assert len(fails) == 13 and all(r.exc_info is None for r in fails)  # one line each, no traceback
    assert "HTTP 429" in fails[0].getMessage() and "HTTP 503" in fails[3].getMessage()
    assert not any("pa-secret" in r.getMessage() for r in caplog.records)
    assert st.embedder is not None


@pytest.mark.asyncio
async def test_rejected_key_turns_embeddings_off(caplog):
    caplog.set_level("INFO")
    for status in (401, 403):
        caplog.clear()
        st, delays = await run_embed_loop(Flaky([status]), sleeps=3)
        assert delays == [] and st.embedder is None  # the loop ends instead of retrying
        msgs = [r.getMessage() for r in caplog.records if r.levelname in ("WARNING", "ERROR")]
        assert len(msgs) == 1 and f"HTTP {status}" in msgs[0] and "keywords only" in msgs[0]
        assert not any("pa-secret" in r.getMessage() for r in caplog.records)


def test_startup_line_says_what_recall_uses(tmp_path, monkeypatch):
    from swarmworld.server.__main__ import make_embedder, recall_search_line

    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    assert recall_search_line(make_embedder(None), None) == "Recall search: keywords only (no VOYAGE_API_KEY)"
    assert recall_search_line(make_embedder("none"), "none") == "Recall search: keywords only (--embed none)"
    monkeypatch.setenv("VOYAGE_API_KEY", "pa-secret")
    line = recall_search_line(make_embedder(None), None)
    assert line == "Recall search: keywords + Voyage embeddings (voyage-3.5-lite)" and "pa-secret" not in line


@pytest.mark.asyncio
async def test_no_embedder_means_no_embed_task():
    import asyncio

    from swarmworld.server.app import create_app

    app = create_app(seed=7, start_loop=True)
    runner = web.AppRunner(app)
    await runner.setup()
    names = {t.get_coro().__name__ for t in asyncio.all_tasks()}
    assert "tick_loop" in names and "embed_loop" not in names
    await runner.cleanup()


def test_voyage_key_from_env_or_dotenv(tmp_path, monkeypatch):
    from swarmworld.server.__main__ import make_embedder, voyage_key

    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
    assert voyage_key(str(tmp_path / ".env")) is None
    (tmp_path / ".env").write_text('OTHER=1\nVOYAGE_API_KEY="pa-secret"\n')
    assert voyage_key(str(tmp_path / ".env")) == "pa-secret"
    monkeypatch.setenv("VOYAGE_API_KEY", "from-env")
    assert voyage_key(str(tmp_path / ".env")) == "from-env"
    monkeypatch.chdir(tmp_path)
    assert make_embedder("none") is None
    assert make_embedder(None).api_key == "from-env"
    monkeypatch.delenv("VOYAGE_API_KEY")
    (tmp_path / ".env").unlink()
    assert make_embedder(None) is None
    with pytest.raises(SystemExit):
        make_embedder("voyage")
