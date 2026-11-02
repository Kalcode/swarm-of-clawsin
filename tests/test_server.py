import asyncio
import json

import pytest

from swarmworld.server.app import STATE, create_app


async def _recv_type(ws, kind, timeout=5.0):
    async def go():
        while True:
            msg = await ws.receive_json()
            if msg.get("type") == kind:
                return msg
    return await asyncio.wait_for(go(), timeout)


@pytest.fixture
async def client(aiohttp_client):
    app = create_app(seed=7, tick_seconds=0.02)
    return await aiohttp_client(app)


async def _join(client, name="laptop", n=3, token=None):
    ws = await client.ws_connect("/ws/node")
    await ws.send_json({"type": "hello", "node": name, "token": token, "slots": 4,
                        "models": [{"tag": "mock", "creatures": n}], "hardware": {}})
    welcome = await _recv_type(ws, "welcome")
    return ws, welcome


async def test_node_join_creates_creatures(client):
    ws, welcome = await _join(client, n=3)
    assert len(welcome["creatures"]) == 3
    st = client.app[STATE]
    assert all(not c.asleep for c in st.world.creatures.values())
    await ws.close()


async def test_think_roundtrip(client):
    ws, welcome = await _join(client, n=1)
    job = await _recv_type(ws, "think")
    assert job["kind"] == "act" and job["messages"][0]["role"] == "system"
    assert "You see" in job["messages"][1]["content"]
    await ws.send_json({"type": "result", "job": job["job"], "ok": True, "latency_ms": 10, "tokens_in": 5, "tokens_out": 5,
                        "output": {"thought": "hi", "action": "say", "target": "", "items": [], "text": "Hello world",
                                   "count": 1, "goal": "meet people"}})
    cid = welcome["creatures"][0]["id"]
    for _ in range(50):
        resp = await client.get(f"/api/creature/{cid}")
        detail = await resp.json()
        if detail["last_intention"]:
            break
        await asyncio.sleep(0.02)
    assert detail["last_intention"].startswith("say")
    assert detail["goal"] == "meet people"
    assert "Hello world" in detail["last_result"]
    await ws.close()


async def test_repeated_noops_count_as_a_loop_and_a_noop_rate(client):
    ws, welcome = await _join(client, n=1)
    st = client.app[STATE]
    c = st.world.creatures[welcome["creatures"][0]["id"]]
    for _ in range(3):
        st._track_loop(c, "walk_to", "berry bush", ok=True, noop=True)
    assert st.metrics.models["mock"]["loops"] == 1
    st.metrics.bump("mock", "act_ok", 4)
    st.metrics.bump("mock", "noops", 1)
    assert st.metrics.snapshot(st.world, 0)["models"]["mock"]["noop_rate"] == 0.25
    await ws.close()


async def test_second_live_node_with_the_same_name_is_refused(client):
    ws1, welcome1 = await _join(client, name="laptop", n=2)
    ws2 = await client.ws_connect("/ws/node")
    await ws2.send_json({"type": "hello", "node": "laptop", "slots": 4, "models": [{"tag": "mock", "creatures": 2}], "hardware": {}})
    err = await _recv_type(ws2, "error")
    assert "already connected" in err["message"]
    assert all(c.node_id for c in client.app[STATE].world.creatures.values())  # the first node keeps its creatures
    await ws1.close()
    await asyncio.sleep(0.05)
    ws3, welcome3 = await _join(client, name="laptop", n=2)  # a reconnect after a drop reclaims them
    assert {c["id"] for c in welcome3["creatures"]} == {c["id"] for c in welcome1["creatures"]}
    await ws3.close()


async def test_bad_output_counts_parse_failure(client):
    ws, welcome = await _join(client, n=1)
    job = await _recv_type(ws, "think")
    await ws.send_json({"type": "result", "job": job["job"], "ok": True, "output": "I like turtles"})
    await asyncio.sleep(0.1)
    st = client.app[STATE]
    assert st.metrics.models["mock"]["parse_failures"] == 1
    await ws.close()


async def test_node_disconnect_puts_creatures_to_sleep(client):
    ws, welcome = await _join(client, name="pc", n=2)
    ids = sorted(c["id"] for c in welcome["creatures"])
    await ws.close()
    await asyncio.sleep(0.1)
    st = client.app[STATE]
    assert all(st.world.creatures[i].asleep for i in ids)
    ws2, welcome2 = await _join(client, name="pc", n=2)
    assert sorted(c["id"] for c in welcome2["creatures"]) == ids
    assert all(not st.world.creatures[i].asleep for i in ids)
    await ws2.close()


async def test_view_stream(client):
    ws = await client.ws_connect("/ws/view")
    init = await _recv_type(ws, "init")
    assert init["width"] == 128 and len(init["tiles"]) == 128 and init["objects"]  # a fresh world
    tick = await _recv_type(ws, "tick")
    assert "creatures" in tick and "clock" in tick
    metrics = await _recv_type(ws, "metrics")
    assert "models" in metrics
    await ws.close()


async def test_lan_requires_token(aiohttp_client):
    client = await aiohttp_client(create_app(seed=7, token="secret", tick_seconds=0.02))
    ws = await client.ws_connect("/ws/node")
    await ws.send_json({"type": "hello", "node": "x", "token": "wrong", "slots": 1, "models": [{"tag": "m", "creatures": 1}]})
    err = await _recv_type(ws, "error")
    assert "token" in err["message"]
    ws2, welcome = await _join(client, n=1, token="secret")
    assert len(welcome["creatures"]) == 1
    await ws2.close()


async def test_viewer_served(client):
    resp = await client.get("/api/state")
    assert resp.status == 200
    resp = await client.get("/../pyproject.toml")
    assert resp.status == 404


async def test_chronicle_job(client):
    ws, welcome = await _join(client, n=1)
    st = client.app[STATE]
    w = st.world
    w.emit("discover", None, 1, 1, "Tam discovered how to make stone knife!")
    w.emit("place", None, 1, 1, "Tam placed a campfire.")
    w.emit("say", "c1", 1, 1, 'Tam: "Look what I made"')
    st.chronicle_due = w.tick
    job = None
    for _ in range(100):
        msg = await ws.receive_json()
        if msg.get("type") == "think" and msg.get("kind") == "chronicle":
            job = msg
            break
        if msg.get("type") == "think":
            await ws.send_json({"type": "result", "job": msg["job"], "ok": True, "output": {"action": "wait"}})
    assert job and "stone knife" in job["messages"][1]["content"]
    await ws.send_json({"type": "result", "job": job["job"], "ok": True, "output": "On the first day, Tam made the first knife."})
    for _ in range(50):
        await asyncio.sleep(0.02)
        if st.chronicle:
            break
    resp = await client.get("/api/chronicle")
    chron = await resp.json()
    assert chron and "first knife" in chron[0]["text"]
    await ws.close()


async def test_voice_from_the_sky(client):
    ws, welcome = await _join(client, n=2)
    resp = await client.post("/api/voice", json={"text": "The tablets in the north hold secrets."})
    data = await resp.json()
    assert resp.status == 200 and len(data["heard_by"]) == 2
    st = client.app[STATE]
    cid = welcome["creatures"][0]["id"]
    assert any("voice from the sky" in t for t in st.memory(cid).recent())
    await ws.close()


async def test_society_graph(client):
    ws, welcome = await _join(client, n=2)
    st = client.app[STATE]
    a, b = [c["id"] for c in welcome["creatures"]]
    w = st.world
    w.emit("say", a, 1, 1, "x", to=b, line="hi")
    w.emit("give", a, 1, 1, "y", to=b, item="stick", n=1)
    w.emit("learn", b, 1, 1, "z", teacher=a, how="watching", item="stone_knife")
    for _ in range(50):
        await asyncio.sleep(0.02)
        if st.relations:
            break
    resp = await client.get("/api/society")
    soc = await resp.json()
    e = soc["edges"][0]
    assert {e["a"], e["b"]} == {a, b} and e["talk"] == 1 and e["gift"] == 1 and e["teach"] == 1
    await ws.close()


async def test_history_snapshots(client):
    ws, welcome = await _join(client, n=2)
    st = client.app[STATE]
    st.record_history()
    resp = await client.get("/api/history")
    hist = await resp.json()
    assert hist and "mock" in hist[-1]["models"] and "recipes_known" in hist[-1]["world"]
    await ws.close()


async def test_tunnelled_requests_are_not_local(client):
    # cloudflared runs on this machine, so tunnelled visitors arrive from 127.0.0.1 with proxy headers
    resp = await client.post("/api/voice", json={"text": "hi"}, headers={"CF-Connecting-IP": "203.0.113.9"})
    assert resp.status == 403
    resp = await client.post("/api/voice", json={"text": "hi"})
    assert resp.status == 200
    ws = await client.ws_connect("/ws/node", headers={"X-Forwarded-For": "203.0.113.9"})
    await ws.send_json({"type": "hello", "node": "intruder", "slots": 1, "models": [{"tag": "m", "creatures": 3}]})
    err = await _recv_type(ws, "error")
    assert "token" in err["message"]
    assert not any(c.model == "m" for c in client.app[STATE].world.creatures.values())


def test_think_log_records_what_happened(tmp_path):
    from swarmworld.server.state import ServerState

    class NullWS:
        async def send_json(self, _):
            pass

    st = ServerState(seed=7, run_dir=tmp_path)
    node, _ = st.register_node(NullWS(), {"node": "t", "slots": 2, "models": [{"tag": "mock", "creatures": 1}]})
    job = next(job for _, job in st.plan_dispatch())
    st.handle_result(node, {"job": job["job"], "ok": True, "output": {"action": "say", "text": "hello"}})
    line = json.loads((tmp_path / "thinks.jsonl").read_text().splitlines()[-1])
    assert line["result"]["ok"] is True and line["result"]["noop"] is False and "hello" in line["result"]["message"]


async def test_wishes_api_lists_and_answers_locally_only(client):
    ws, welcome = await _join(client, n=1)
    st = client.app[STATE]
    c = st.world.creatures[welcome["creatures"][0]["id"]]
    st.world.emit("say", c.id, c.x, c.y, "", line="I wish we had a windmill.", speaker=c.name)
    st.tick_message(st.world.events[-1:])
    body = await (await client.get("/api/wishes")).json()
    assert body["can_answer"] and body["wishes"][0]["thing"] == "windmill"
    wid = body["wishes"][0]["id"]
    tunnel = {"CF-Connecting-IP": "203.0.113.9"}
    assert (await client.get("/api/wishes", headers=tunnel)).status == 200
    assert not (await (await client.get("/api/wishes", headers=tunnel)).json())["can_answer"]
    assert (await client.post(f"/api/wishes/{wid}", json={"reply": "hi"}, headers=tunnel)).status == 403
    assert (await client.post(f"/api/wishes/{wid}", json={"grant": "unobtainium"})).status == 400
    assert (await client.post("/api/wishes/w999", json={"reply": "hi"})).status == 404
    out = await (await client.post(f"/api/wishes/{wid}", json={"status": "noted"})).json()
    assert out["wish"]["status"] == "noted"
    await ws.close()
