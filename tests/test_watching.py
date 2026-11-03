"""The public "watching" count: POST /public/here, the counting, the self-limiting sample rate, and live.json."""

import json
import logging

import pytest

from swarmworld.server.app import STATE, create_app
from swarmworld.server.public import PUBLISHER
from swarmworld.server.watching import MAX_IDS, MIN_SAMPLE, WINDOW, Watching, sample_rate

TUNNEL = {"CF-Connecting-IP": "203.0.113.9"}
ID = "0123456789abcdef0123456789abcdef"


class Clock:
    t = 100.0

    def __call__(self):
        return self.t


def ids(n, start=0):
    return [f"{start + i:032x}" for i in range(n)]


@pytest.fixture
async def client(aiohttp_client):
    return await aiohttp_client(create_app(seed=7, tick_seconds=0.02, public_every=3600))


# ---- the route ----------------------------------------------------------------------------------------------------

async def test_a_check_in_is_a_204_that_is_never_cached(client):
    r = await client.post("/public/here", json={"id": ID})
    assert r.status == 204 and r.headers["Cache-Control"] == "no-store" and await r.read() == b""
    assert client.app[PUBLISHER].watching.count() == 1


@pytest.mark.parametrize("body", [
    b"", b"not json", b"[]", b'"x"', b"{}", b'{"id": 5}', b'{"id": null}',
    b'{"id": "0123456789abcde"}',                      # 15 chars
    b'{"id": "' + b"a" * 33 + b'"}',                   # 33 chars
    b'{"id": "0123456789abcdeg"}',                     # not hex
    b'{"id": "0123456789ABCDEF"}',                     # upper case: the page sends lower case
    b'{"id": "' + b"a" * 300 + b'"}',                  # over 256 bytes
    b'{"id": "0123456789abcdef", "pad": "' + b" " * 300 + b'"}',
    b"\xff\xfe",
])
async def test_a_malformed_check_in_is_a_400(client, body):
    r = await client.post("/public/here", data=body)
    assert r.status == 400 and r.headers["Cache-Control"] == "no-store"
    assert client.app[PUBLISHER].watching.count() == 0


async def test_a_chunked_oversized_body_is_a_400(client):
    async def gen():
        yield b'{"id": "0123456789abcdef", "pad": "'
        yield b" " * 1000
        yield b'"}'
    assert (await client.post("/public/here", data=gen())).status == 400


async def test_other_methods_get_a_405_with_no_body(client):
    for method in ("get", "put", "delete", "patch", "head"):
        r = await getattr(client, method)("/public/here")
        assert r.status == 405 and r.headers["Allow"] == "POST" and await r.read() == b"", method
    assert client.app[PUBLISHER].watching.count() == 0


async def test_reachable_through_the_proxy_and_nothing_else_widens(client):
    assert (await client.post("/public/here", json={"id": ID}, headers=TUNNEL)).status == 204
    assert (await client.get("/public/here", headers=TUNNEL)).status == 405
    for path in ("/public/here/", "/api/here", "/here", "/public/hereby", "/api/state"):
        assert (await client.post(path, json={"id": ID}, headers=TUNNEL)).status == 404, path
    assert (await client.post("/api/voice", json={}, headers=TUNNEL)).status == 404
    assert (await client.post("/public/live.json", json={}, headers=TUNNEL)).status == 404  # as before


async def test_nothing_is_logged(client, caplog):
    caplog.set_level(logging.DEBUG)
    await client.post("/public/here", json={"id": ID}, headers=TUNNEL)
    await client.post("/public/here", data=b"junk", headers=TUNNEL)
    assert ID not in caplog.text and "203.0.113.9" not in caplog.text


async def test_the_address_is_the_tunnel_header_when_present(client):
    w = client.app[PUBLISHER].watching
    for i in ids(7):   # same tunnel address, though the socket peer is 127.0.0.1
        await client.post("/public/here", json={"id": i}, headers=TUNNEL)
    assert w.count() == 5
    await client.post("/public/here", json={"id": ids(1, 50)[0]}, headers={"CF-Connecting-IP": "198.51.100.1"})
    assert w.count() == 6


# ---- the counting -------------------------------------------------------------------------------------------------

def test_distinct_ids_count_and_one_id_twice_counts_once():
    w = Watching(clock=Clock())
    for i, a in zip(ids(3), "abc"):
        w.note(i, a)
    w.note(ids(1)[0], "a")
    assert w.count() == 3


def test_an_id_older_than_the_window_drops_out():
    c = Clock()
    w = Watching(clock=c)
    w.note(ids(1)[0], "a")
    c.t += WINDOW - 1
    w.note(ids(1, 1)[0], "b")
    assert w.count() == 2
    c.t += 2                      # the first is now WINDOW + 1 old
    assert w.count() == 1
    c.t += WINDOW
    assert w.count() == 0 and not w._per   # and the per-address tally is released with it


def test_a_repeat_check_in_keeps_an_id_alive():
    c = Clock()
    w = Watching(clock=c)
    for _ in range(5):
        w.note(ID, "a")
        c.t += 60
    assert w.count() == 1


def test_the_per_address_cap_holds_and_frees_with_time():
    c = Clock()
    w = Watching(clock=c)
    for i in ids(8):
        w.note(i, "same")
    assert w.count() == 5
    w.note(ids(1)[0], "same")     # an id already counted stays counted
    assert w.count() == 5
    c.t += WINDOW + 5
    for i in ids(8, 100):
        w.note(i, "same")
    assert w.count() == 5


def test_the_hard_cap_holds():
    w = Watching(clock=Clock(), max_ids=10, per_address=100)
    for i in ids(15):
        w.note(i, "a")
    assert w.count() == 10
    assert MAX_IDS == 100_000


def test_nothing_about_an_address_is_kept_or_published():
    w = Watching(clock=Clock())
    w.note(ID, "203.0.113.9")
    state = repr(vars(w)).encode() + b"".join(a for _, a in w._seen.values())
    assert b"203.0.113.9" not in state
    assert Watching(clock=Clock())._salt != w._salt


# ---- the sampling -------------------------------------------------------------------------------------------------

def test_the_sample_rate_follows_the_estimate():
    assert sample_rate(100) == 1.0
    assert sample_rate(300) == 1.0
    assert sample_rate(3000) == 0.1
    assert sample_rate(10**9) == MIN_SAMPLE
    assert sample_rate(0) == 1.0


def test_watching_scales_the_counted_ids_by_the_chance_of_being_heard():
    c = Clock()
    w = Watching(clock=c, per_address=1000)
    for i in ids(40):
        w.note(i, "a")
    n, here = w.snapshot()
    assert n == 40 and here == {"every": 30, "sample": 1.0}
    w.sample = 0.5               # three chances a window at half: heard with probability 1 - 0.5**3
    n, _ = w.snapshot()
    assert n == round(40 / 0.875)


def test_the_rate_settles_where_the_crowd_is_and_the_count_follows():
    import random
    rng = random.Random(1)
    c = Clock()
    w = Watching(clock=c, per_address=10**6)
    crowd, here, rates = 6000, {"sample": 1.0}, []
    for step in range(300):                      # 15 minutes in 3-second steps; each page checks in every 30 s
        for i in range(crowd):
            if rng.random() < here["sample"] * 3 / 30:
                w.note(f"{i:032x}", f"a{i}")
        c.t += 3
        n, here = w.snapshot()
        rates.append(here["sample"])
    assert here["sample"] == pytest.approx(0.05, abs=0.01) and abs(n - crowd) < crowd * 0.15
    assert max(rates[-60:]) / min(rates[-60:]) < 1.5          # and no longer swinging


# ---- live.json and the private viewer -----------------------------------------------------------------------------

async def test_live_json_carries_watching_and_here_and_nothing_more(client):
    app = client.app
    pub = app[PUBLISHER]
    for i, a in zip(ids(4), ("a", "b", "c", "d")):
        pub.watching.note(i, a)
    pub.publish()
    live = json.loads((await (await client.get("/public/live.json")).read()))
    assert live["watching"] == 4 and live["here"] == {"every": 30, "sample": 1.0}
    assert "203.0.113" not in json.dumps(live) and ids(1)[0] not in json.dumps(live)
    msg = json.loads(app[STATE].metrics_message())
    assert msg["watching"] == 4
