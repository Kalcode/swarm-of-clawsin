"""The steward's admin API: local-only test and management actions on the live world, each leaving a steward event."""

from swarmworld.server.app import STATE

from tests.test_server import _join, client  # noqa: F401  (fixture)


async def post(client, action, body, **kw):
    return await client.post(f"/api/admin/{action}", json=body, **kw)


async def test_admin_is_local_only(client):
    r = await post(client, "weather", {"weather": "rain"}, headers={"CF-Connecting-IP": "203.0.113.9"})
    assert r.status == 403


async def test_give_place_move_remove_and_weather(client):
    ws, welcome = await _join(client, n=1)
    st = client.app[STATE]
    c = st.world.creatures[welcome["creatures"][0]["id"]]
    r = await post(client, "give", {"creature": c.name, "item": "rope", "count": 2})
    assert r.status == 200 and c.inventory["rope"] == 2
    assert (await post(client, "give", {"creature": c.name, "item": "unobtainium"})).status == 400
    x, y = next((x, y) for x in range(c.x - 3, c.x + 4) for y in range(c.y - 3, c.y + 4)
                if (x, y) != (c.x, c.y) and st.world.walkable(x, y) and not st.world.object_at(x, y) and not st.world.occupied(x, y))
    r = await post(client, "place", {"kind": "basket", "x": x, "y": y})
    oid = (await r.json())["object"]["id"]
    assert r.status == 200 and st.world.objects[oid].kind == "basket"
    assert (await post(client, "place", {"kind": "basket", "x": x, "y": y})).status == 400  # tile taken
    assert (await post(client, "place", {"kind": "dragon", "x": x, "y": y})).status == 400  # unknown kind
    r = await post(client, "move", {"creature": c.id, "x": x, "y": y + 1 if st.world.walkable(x, y + 1) else y - 1})
    assert r.status in (200, 400)
    assert (await post(client, "remove", {"object": oid})).status == 200 and oid not in st.world.objects
    r = await post(client, "weather", {"weather": "rain", "ticks": 100})
    assert r.status == 200 and st.world.weather == "rain" and st.world.weather_until == st.world.tick + 100
    assert sum(1 for e in st.world.events if e.kind == "steward") >= 5
    await ws.close()
