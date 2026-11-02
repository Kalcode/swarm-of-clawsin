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
    assert init["width"] == 64 and len(init["tiles"]) == 64 and init["objects"]
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
