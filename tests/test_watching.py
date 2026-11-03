"""The public "watching" count: POST /public/here, the counting, the self-limiting sample rate, and live.json."""

import json
import logging

import pytest

from swarmworld.server.app import STATE, create_app
from swarmworld.server.public import PUBLISHER
from swarmworld.server.watching import MAX_IDS, MIN_SAMPLE, WINDOW, Watching, client_address, hear_probability, network_of, sample_rate

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
    state = repr(vars(w)).encode() + b"".join(v[1] for v in w._seen.values())
    assert b"203.0.113.9" not in state
    assert Watching(clock=Clock())._salt != w._salt


# ---- the sampling -------------------------------------------------------------------------------------------------

def test_the_sample_rate_follows_the_estimate():
    assert sample_rate(100) == 1.0
    assert sample_rate(300) == 1.0
    assert sample_rate(3000) == 0.1
    assert sample_rate(10**9) == MIN_SAMPLE
    assert sample_rate(0) == 1.0


def test_watching_weights_each_id_by_the_rate_in_force_when_it_checked_in():
    c = Clock()
    w = Watching(clock=c, per_address=1000)
    for i in ids(40):
        w.note(i, "a")
    n, here = w.snapshot()
    assert n == 40 and here == {"every": 30, "sample": 1.0}
    w.sample = 0.5               # three chances a window at half: heard with probability 1 - 0.5**3
    for i in ids(40, 100):
        w.note(i, "b")
    w.sample = 0.1               # a later change does not re-weigh them
    c.t += 300
    for i in ids(40):            # the first forty are long gone; a new reading is taken under the new rate
        w.note(i, "a")
    w._estimate = None
    n, _ = w.snapshot()
    assert n == round(40 / hear_probability(0.1))


def run_crowd(profile, minutes, per_step=3):
    """The real class on an injected clock; a crowd of N pages, each checking in every 30 s at the published rate. Returns
    [(second, true crowd, published watching, sample, check-ins per second)]."""
    import random
    rng = random.Random(3)
    c = Clock()
    w = Watching(clock=c, per_address=10**9)
    here, rows = {"sample": 1.0}, []
    for step in range(int(minutes * 60 / per_step)):
        t = step * per_step
        n = profile(t)
        sent = 0
        for i in range(n):
            if rng.random() < per_step / 30 and rng.random() < here["sample"]:
                w.note(f"{i:032x}", f"a{i}")
                sent += 1
        c.t += per_step
        shown, here = w.snapshot()
        rows.append((t, n, shown, here["sample"], sent / per_step))
    return rows


def test_a_crowd_that_jumps_up_is_never_overcounted_and_is_found_in_three_minutes():
    rows = run_crowd(lambda t: 300 if t < 600 else 20000, 17)
    after = [r for r in rows if r[0] >= 600]
    assert max(r[2] for r in after) <= 1.5 * 20000
    late = [r for r in after if r[0] >= 780]
    assert all(abs(r[2] - 20000) <= 0.15 * 20000 for r in late), [r[2] for r in late[::10]]


def test_a_crowd_that_drops_is_found_and_the_rate_recovers():
    """The brief asked for 15% and a rate above 0.9 after 3 minutes. They cannot both hold with a 90 s window and a 30 s
    smoothing: the old crowd's ids take 90 s to expire, then 20,000 must decay to 300 (a factor of 67, about 4 time
    constants = 126 s). Measured: 552 shown and a rate of 0.54 at 3 minutes; 302 and 0.99 at 4 minutes. So: within 2x at
    3 minutes, within 15% and the rate above 0.9 at 4."""
    rows = run_crowd(lambda t: 20000 if t < 600 else 300, 17)
    at3 = [r for r in rows if 780 <= r[0] < 800]
    assert all(r[2] <= 2 * 300 for r in at3), [r[2] for r in at3]
    late = [r for r in rows if r[0] >= 840]
    assert all(abs(r[2] - 300) <= 0.15 * 300 for r in late), [r[2] for r in late[::10]]
    assert all(r[3] > 0.9 for r in late)


def test_a_short_spike_is_never_shown_larger_than_the_crowd_was():
    rows = run_crowd(lambda t: 20000 if 600 <= t < 660 else 1000, 17)
    assert max(r[2] for r in rows) <= 1.5 * 20000
    assert all(r[2] <= 1.5 * 1000 for r in rows if r[0] >= 900), [r[2] for r in rows[::20]]


def test_the_rate_answers_a_jump_within_two_publishes():
    c = Clock()
    w = Watching(clock=c, per_address=10**9)
    w.snapshot()
    for i in range(20000):
        w.note(f"{i:032x}", f"a{i}")
    for _ in range(2):
        c.t += 3
        _, here = w.snapshot()
    assert here["sample"] < 0.6


def test_a_prune_with_nothing_expired_looks_at_one_entry():
    c = Clock()
    w = Watching(clock=c, per_address=10**9)
    for i in range(1000):
        w.note(f"{i:032x}", f"a{i}")
        c.t += 0.01
    w.pruned = 0
    w.count()
    assert w.pruned == 1
    c.t += WINDOW - 5            # the first few hundred expire: cost follows them, not the table
    w.pruned = 0
    n = w.count()
    assert w.pruned == (1000 - n) + 1 and 0 < n < 1000


def test_a_refreshed_id_moves_to_the_back_and_the_tallies_stay_right():
    c = Clock()
    w = Watching(clock=c)
    a, b = ids(2)
    w.note(a, "x")
    c.t += 50
    w.note(b, "y")
    w.note(a, "x")
    c.t += 50                    # b and a (refreshed with b) are both 50 old
    assert w.count() == 2
    c.t += 45
    assert w.count() == 0 and not w._per and abs(w._weight) < 1e-9


def test_a_lan_client_cannot_pick_its_address_with_a_header():
    assert client_address("127.0.0.1", "203.0.113.9") == "203.0.113.9"      # cloudflared on this machine
    assert client_address("::1", "203.0.113.9") == "203.0.113.9"
    assert client_address("192.168.1.50", "203.0.113.9") == "192.168.1.50"   # a LAN client's header is ignored
    assert client_address("192.168.1.50", None) == "192.168.1.50"
    assert client_address("127.0.0.1", None) == "127.0.0.1"
    w = Watching(clock=Clock())
    for i in ids(8):             # a LAN address sending 8 different spoofed headers: still one address, capped at 5
        w.note(i, client_address("192.168.1.50", f"198.51.100.{int(i, 16) % 250}"))
    assert w.count() == 5


def test_an_ipv6_address_counts_as_its_slash_64():
    w = Watching(clock=Clock())
    for k, i in enumerate(ids(8)):
        w.note(i, f"2001:db8:1:2:{k:x}::{k:x}")
    assert w.count() == 5
    assert network_of("2001:db8:1:2:aaaa::1") == "2001:db8:1:2::/64" and network_of("203.0.113.9") == "203.0.113.9"
    assert network_of("nonsense") == "nonsense"


# ---- live.json and the private viewer -----------------------------------------------------------------------------

async def test_live_json_carries_watching_and_here_and_nothing_more(client):
    app = client.app
    pub = app[PUBLISHER]
    pub.watching.clock = c = Clock()
    for i, a in zip(ids(4), ("a", "b", "c", "d")):
        pub.watching.note(i, a)
    c.t += 300     # the smoothed estimate is long past its first reading
    pub.watching._estimate = 4.0
    pub.publish()
    live = json.loads((await (await client.get("/public/live.json")).read()))
    assert live["watching"] == 4 and live["here"] == {"every": 30, "sample": 1.0}
    assert "203.0.113" not in json.dumps(live) and ids(1)[0] not in json.dumps(live)
    msg = json.loads(app[STATE].metrics_message())
    assert msg["watching"] == 4
