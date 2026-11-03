"""The publisher: snapshots on a cadence, encoded once, versions that never repeat."""

import asyncio
import gzip
import json
import random

import pytest

from swarmworld.server.app import STATE, create_app
from swarmworld.server.public import LIVE_KEYS, PUBLISHER, STATIC_KEYS, Publisher
from swarmworld.server.state import ServerState


class Fake:
    t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def fake():
    return Fake()


@pytest.fixture
def st():
    return ServerState(seed=7)


@pytest.fixture
def pub(st, fake):
    return Publisher(st, clock=fake)


def tick(st, pub):
    ev = st.sim.tick()
    pub.observe(st.tick_dict(ev), ev)


def live_of(pub):
    return json.loads(pub.live_doc().body)


def test_live_and_static_shapes(pub):
    pub.publish()
    live, static = live_of(pub), json.loads(pub.static_doc().body)
    assert set(live) == set(LIVE_KEYS) and live["schema"] == static["schema"] == 1
    assert {"watching", "here"} <= set(live) and live["watching"] == 0 and live["here"]["every"] == 30
    assert live["type"] == "live" and static["type"] == "static" and live["static"] == static["version"]
    assert set(static) <= set(STATIC_KEYS) and len(static["tiles"]) == static["height"] and static["regions"]
    assert gzip.decompress(pub.live_doc().gz) == pub.live_doc().body


def test_deltas_since_the_static_version(st, pub):
    pub.publish()
    version_before = pub.static_version
    w = st.world
    tree = next(o for o in w.objects.values() if o.kind == "tree")
    animal = next(o for o in w.objects.values() if o.kind not in ("tree", "stone", "bush") and o.id != tree.id)
    bx, by = next((x, y) for x in range(5, 60) for y in range(5, 60) if (x, y) not in w.grid)
    basket = w.add_object("basket", bx, by)
    moved = any(w.move_object(animal, animal.x + dx, animal.y + dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (2, 0)))
    assert moved
    w.remove_object(tree.id)
    w.set_tile(3, 4, "t")
    tick(st, pub)
    pub.publish()
    live = live_of(pub)
    assert {basket.id, animal.id} <= {o["id"] for o in live["objects_upsert"]} and tree.id in live["objects_removed"]
    assert [3, 4, "t"] in live["tiles"] and live["static"] == version_before
    assert basket.id not in {o["id"] for o in json.loads(pub.static_doc().body)["objects"]}


def test_static_is_rebuilt_on_time_size_and_new_items(st, pub, fake):
    pub.publish()
    v1 = pub.static_version
    fake.t += 299
    pub.publish()
    assert pub.static_version == v1
    fake.t += 2
    pub.publish()
    live = live_of(pub)
    assert pub.static_version != v1 and live["objects_upsert"] == [] and live["tiles"] == []
    v2 = pub.static_version
    objs = list(st.world.objects.values())[:501]
    for o in objs:
        st.world.change_kind(o, o.kind)
    tick(st, pub)
    assert len(pub._upsert) > 500
    pub.publish()
    assert pub.static_version != v2
    v3 = pub.static_version
    st.world.catalog.add_invention({"id": "inv_test", "name": "test thing", "inputs": {"stick": 1, "stone": 2}})
    pub.publish()
    static = json.loads(pub.static_doc().body)
    assert pub.static_version != v3 and "inv_test" in static["items"] and static["inventions"][-1]["id"] == "inv_test"


def test_versions_never_repeat_across_restarts(st):
    a, b = Publisher(st), Publisher(st)
    a.publish()
    b.publish()
    assert a.boot != b.boot and a.static_version != b.static_version and a.chronicle_version != b.chronicle_version


def test_a_walker_brings_its_path(st, pub, fake):
    st.register_node(type("W", (), {"send_json": lambda s, m: None})(), {"node": "n", "slots": 2, "models": [{"tag": "mock", "creatures": 2}]})
    c, other = list(st.world.creatures.values())[:2]
    pub.publish()
    first = live_of(pub)
    x0, y0 = c.x, c.y
    for i in range(1, 4):
        st.world.creatures[c.id].x = x0 + i
        tick(st, pub)
    fake.t += 3
    pub.publish()
    live = live_of(pub)
    card = next(x for x in live["creatures"] if x["id"] == c.id)
    assert card["path"] == [[x0 + 1, y0], [x0 + 2, y0], [x0 + 3, y0]] and [card["x"], card["y"]] == card["path"][-1]
    still = next(x for x in live["creatures"] if x["id"] == other.id)
    assert "path" not in still and live["from_tick"] == first["tick"]


def test_events_carry_a_sequence_and_a_window(st, pub):
    w = st.world
    w.emit("say", None, 3, 3, "Mara: hello there")
    w.emit("steward", None, 3, 3, "the steward did a thing")
    w.emit("say", None, 3, 3, "Brain node laptop joined", brain_node=True)
    tick(st, pub)
    pub.publish()
    live = live_of(pub)
    seqs = [e["seq"] for e in live["events"]]
    assert seqs == sorted(set(seqs)) and any(e["text"] == "Mara: hello there" for e in live["events"])
    assert "steward" not in {e["kind"] for e in live["events"]}
    assert not any("Brain node" in e["text"] for e in live["events"])
    window = -(-12 // st.tick_seconds)
    for _ in range(int(window) + 2):
        tick(st, pub)
    pub.publish()
    assert not any(e["text"] == "Mara: hello there" for e in live_of(pub)["events"])
    for i in range(200):
        w.emit("say", None, 3, 3, f"line {i}")
    tick(st, pub)
    pub.publish()
    live = live_of(pub)
    assert len(live["events"]) <= 120 and live["events"][-1]["text"].startswith("line")


def test_documents_are_encoded_once_per_interval(st, pub, fake):
    pub.publish()
    doc = pub.live_doc()
    assert not pub.due() and pub.live_doc() is doc
    fake.t += 3.0
    assert pub.due()
    cid = next(iter(st.world.creatures), None)
    if cid is None:
        st.register_node(type("W", (), {"send_json": lambda s, m: None})(), {"node": "n", "slots": 1, "models": [{"tag": "mock", "creatures": 1}]})
        cid = next(iter(st.world.creatures))
    pub.creature_doc(cid)
    pub.creature_doc(cid)
    assert pub.builds["creature"] == 1 and pub.creature_doc("nobody") is None


def test_sizes_within_budget(st, pub):
    rng = random.Random(3)
    st.register_node(type("W", (), {"send_json": lambda s, m: None})(), {"node": "n", "slots": 60, "models": [{"tag": "mock", "creatures": 50}]})
    w = st.world
    words = [it.name for it in w.catalog.items.values()] + [c.name for c in w.creatures.values()]

    def sentence(n=14):
        return " ".join(rng.choice(words) for _ in range(n))
    for c in w.creatures.values():
        c.say = sentence()
    for i in range(40):
        for q in range(4):
            st.wishes.add(rng.choice(words), f"w{i}", "said", sentence(), st.world.tick + q)
    ids = [c.id for c in w.creatures.values()]
    from collections import Counter
    for i in range(400):
        st.relations[f"{rng.choice(ids)}|{rng.choice(ids)}{i}"] = Counter(talk=rng.randint(1, 9))
    for _ in range(3):
        st.finish_chronicle(True, " ".join(rng.choice(words) for _ in range(240)))
    for _ in range(120):
        w.emit("say", rng.choice(ids), 3, 3, sentence(30))
    pub.publish()
    objs = list(w.objects.values())[:500]
    for o in objs:
        w.change_kind(o, o.kind)
    tick(st, pub)
    pub.publish()
    assert len(live_of(pub)["events"]) >= 100
    assert len(pub.live_doc().gz) < 60_000
    assert len(pub.static_doc().gz) < 150_000


def test_slow_documents(st, pub, fake):
    a = pub.almanac_doc()
    assert "roadmap" not in json.loads(a.body) and pub.almanac_doc() is a
    fake.t += 60
    assert pub.almanac_doc() is not a
    st.history = [{"tick": i} for i in range(1000)]
    fake.t += 60
    assert len(json.loads(pub.history_doc().body)) == 400
    v = pub.chronicle_version
    st.finish_chronicle(True, "A first chapter.")
    assert pub.chronicle_version != v and json.loads(pub.chronicle_doc().body)[-1]["text"] == "A first chapter."


async def test_a_publishing_failure_never_stops_the_world(aiohttp_client, monkeypatch):
    monkeypatch.setattr(Publisher, "publish", lambda self: 1 / 0)
    client = await aiohttp_client(create_app(seed=7, tick_seconds=0.02, public_every=0.05))
    t0 = client.app[STATE].world.tick
    await asyncio.sleep(0.3)
    assert client.app[STATE].world.tick >= t0 + 5


async def test_the_tick_loop_publishes(aiohttp_client):
    client = await aiohttp_client(create_app(seed=7, tick_seconds=0.02, public_every=0.1))
    pub = client.app[PUBLISHER]
    seq0 = pub.seq
    await asyncio.sleep(0.5)
    assert pub.seq >= seq0 + 3
    assert (await (await client.get("/api/metrics")).json())["tick_ms"]["n"] > 0


def test_every_part_of_live_static_and_chronicle_is_picked(st, pub):
    w = st.world
    st.sim.tick()  # names the landmarks
    assert any(lm.get("by_sight") for lm in w.landmarks)
    w.landmarks.append({"name": "a cave", "x": 1, "y": 2, "kind": "cave", "size": 1, "secret": "s3cr3t"})
    w.ext.setdefault("building", {}).setdefault("built", {})["b1"] = {
        "design": "hut", "x0": 1, "y0": 1, "x1": 3, "y1": 3, "door": [2, 3], "roof": True, "by": ["Holt"], "tick": 5,
        "secret": "s3cr3t"}
    st.chronicle.append({"tick": 1, "day": 1, "phase": "dawn", "text": "It began.", "secret": "s3cr3t"})
    pub.publish()
    for doc in (pub.live_doc(), pub.static_doc(), pub.chronicle_doc()):
        assert b"s3cr3t" not in doc.body and b"by_sight" not in doc.body
    live = live_of(pub)
    assert live["chronicle"] == [{"tick": 1, "day": 1, "phase": "dawn", "text": "It began."}]
    assert any(b["id"] == "b1" for b in live["buildings"]) and any(lm["name"] == "a cave" for lm in live["landmarks"])


LONE = "half \ud83c an emoji"


def poison(st):
    """A lone surrogate (valid in a JSON escape, so a model can write one) in a say, a sign, a wish quote and a thought."""
    w = st.world
    if not w.creatures:
        st.register_node(type("W", (), {"send_json": lambda s, m: None})(), {"node": "n", "slots": 2, "models": [{"tag": "mock", "creatures": 2}]})
    c = next(iter(w.creatures.values()))
    c.say, c.say_until = LONE, w.tick + 10
    x, y = next((x, y) for x in range(5, 60) for y in range(5, 60) if (x, y) not in w.grid)
    w.add_object("sign", x, y, text=LONE)
    st.wishes.add("Mara", "lamp", "said", LONE, w.tick)
    st.last[c.id] = {"thought": LONE, "perception": "", "intention": "", "result": ""}
    return c.id


def test_a_lone_surrogate_in_model_text_publishes_everywhere(st, pub):
    cid = poison(st)
    pub.publish()
    for doc in (pub.live_doc(), pub.static_doc(), pub.creature_doc(cid)):
        assert json.loads(doc.body) and gzip.decompress(doc.gz) == doc.body
        doc.body.decode("ascii")  # \udXXX escapes, nothing a strict UTF-8 encoder would refuse
    assert "\\ud83c" in pub.live_doc().body.decode() or "\\ud83c" in pub.static_doc().body.decode()


def test_a_failing_publish_is_retried_at_the_next_interval_not_every_tick(st, pub, fake, monkeypatch):
    pub.publish()
    monkeypatch.setattr(pub, "_build_live", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    fake.t += 4
    assert pub.due()
    with pytest.raises(RuntimeError):
        pub.publish()
    assert not pub.due()  # the interval restarted
    fake.t += 4
    assert pub.due()



def test_a_failed_static_build_does_not_use_up_a_version(st, pub, fake, monkeypatch):
    pub.publish()
    v1, body1 = pub.static_version, pub.static_doc().body
    fake.t += 400  # static is due
    monkeypatch.setattr("swarmworld.server.public.public_inventions", lambda s: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        pub.publish()
    assert pub.static_version == v1 and pub.static_doc().body == body1
    monkeypatch.undo()
    fake.t += 4
    pub.publish()
    assert pub.static_version != v1 and json.loads(pub.static_doc().body)["version"] == pub.static_version
