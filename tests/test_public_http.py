"""Serving /public/*: the spec's cache headers, gzip once, ETags; and the proxy guard: a request relayed by a tunnel or
proxy reaches /public/* (and, with the join token, GET /api/almanac) and nothing else."""

import asyncio
import gzip
import json
import re
import subprocess
import sys

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from swarmworld.server.app import (PROXY_HEADERS, STATE, api_admin, api_almanac, api_voice, api_wish_answer,
                                   create_app, token_matches)
from swarmworld.server.public import PUBLISHER

from .test_server import _join

TUNNEL = {"CF-Connecting-IP": "203.0.113.9"}
# one sample value for every header that marks a relayed request
PROXIED = {"CF-Connecting-IP": "203.0.113.9", "CF-Ray": "8f3a1c2b3d4e5f60-LHR", "X-Forwarded-For": "203.0.113.9",
           "X-Real-IP": "203.0.113.9", "Forwarded": "for=203.0.113.9;proto=https", "Cdn-Loop": "cloudflare",
           "Via": "1.1 proxy.example"}


@pytest.fixture
async def client(aiohttp_client):
    return await aiohttp_client(create_app(seed=7, tick_seconds=0.02, public_every=3600))


async def fetch(client, url):
    r = await client.get(url)
    assert r.status == 200, url
    return await r.read()


async def raw_get(client, target: str, headers: bytes = b"") -> tuple[int, bytes]:
    """GET a request-target exactly as written (no client-side normalising or quoting), with raw header lines."""
    reader, writer = await asyncio.open_connection(client.server.host, client.server.port)
    writer.write(f"GET {target} HTTP/1.1\r\nHost: x\r\nConnection: close\r\n".encode() + headers + b"\r\n")
    await writer.drain()
    data = await reader.read()
    writer.close()
    head, _, body = data.partition(b"\r\n\r\n")
    return int(head.split()[1]), body


def test_all_proxy_headers_are_sampled():
    assert set(PROXIED) == set(PROXY_HEADERS)


async def test_a_relay_that_only_says_via_or_cdn_loop_is_still_a_relay(client):
    """Cloudflare marks every request it relays with CDN-Loop, and an HTTP proxy adds Via; header names ignore case."""
    for line in (b"Via: 1.1 proxy.example\r\n", b"via: 1.1 proxy.example\r\n", b"CDN-Loop: cloudflare\r\n",
                 b"cdn-loop: cloudflare; loops=1\r\n"):
        for target in ("/api/state", "/index.html", "/api/wishes"):
            status, _ = await raw_get(client, target, line)
            assert status == 404, (target, line)
        status, _ = await raw_get(client, "/public/live.json", line)
        assert status == 200, line
    status, _ = await raw_get(client, "/api/state")
    assert status == 200


async def test_live_headers_gzip_and_etag(client):
    r = await client.get("/public/live.json", headers={"Accept-Encoding": "gzip"}, auto_decompress=False)
    assert r.status == 200 and r.headers["Cache-Control"] == "public, max-age=2, s-maxage=3, stale-while-revalidate=10"
    assert r.headers["Content-Encoding"] == "gzip" and "Accept-Encoding" in r.headers["Vary"]
    assert r.headers["Content-Type"] == "application/json; charset=utf-8" and r.headers["X-Content-Type-Options"] == "nosniff"
    assert json.loads(gzip.decompress(await r.read()))["schema"] == 1
    again = await client.get("/public/live.json", headers={"If-None-Match": r.headers["ETag"]})
    assert again.status == 304 and again.headers["ETag"] == r.headers["ETag"]
    assert again.headers["Cache-Control"] == r.headers["Cache-Control"] and await again.read() == b""
    weak = await client.get("/public/live.json", headers={"If-None-Match": f'"other", W/{r.headers["ETag"]}'})
    assert weak.status == 304
    assert (await client.get("/public/live.json", headers={"If-None-Match": '"other"'})).status == 200


async def test_odd_requests(client):
    plain = await client.get("/public/live.json", headers={"Accept-Encoding": "identity"})
    assert "Content-Encoding" not in plain.headers and (await plain.json())["type"] == "live"
    refused = await client.get("/public/live.json", headers={"Accept-Encoding": "gzip;q=0, deflate"}, auto_decompress=False)
    assert "Content-Encoding" not in refused.headers and json.loads(await refused.read())["type"] == "live"
    head = await client.head("/public/live.json")
    assert head.status == 200 and await head.read() == b""
    assert (await client.get("/public/live.json?x=8f3a")).status == 200
    nobody = await client.get("/public/creature/zz9.json")
    assert nobody.status == 404 and nobody.headers["Cache-Control"] == "public, max-age=3"
    nope = await client.get("/public/nope")
    assert nope.status == 404 and nope.headers["Cache-Control"] == "public, max-age=3"
    assert (await client.post("/public/live.json")).status == 405
    for path in ("/public", "/public/"):
        r = await client.get(path, allow_redirects=False)
        assert r.status == 302 and r.headers["Location"] == "/public/app/", path


async def test_only_the_current_static_version_is_cached_for_good(client):
    v = (await (await client.get("/public/live.json")).json())["static"]
    now = await client.get(f"/public/static.json?v={v}")
    assert now.headers["Cache-Control"] == "public, max-age=31536000, immutable"
    for url in ("/public/static.json?v=old-1", "/public/static.json"):
        r = await client.get(url)
        assert r.headers["Cache-Control"].startswith("public, max-age=2") and (await r.json())["version"] == v
    cv = (await (await client.get("/public/live.json")).json())["chronicle_version"]
    now = await client.get(f"/public/chronicle.json?v={cv}")
    assert now.headers["Cache-Control"] == "public, max-age=31536000, immutable" and await now.json() == []
    for url in ("/public/chronicle.json?v=old-1", "/public/chronicle.json"):
        r = await client.get(url)
        assert r.headers["Cache-Control"].startswith("public, max-age=2") and await r.json() == []


async def test_one_encode_per_interval_under_concurrent_requests(client):
    pub = client.app[PUBLISHER]
    before = dict(pub.builds)
    bodies = await asyncio.gather(*(fetch(client, "/public/live.json") for _ in range(100)))
    assert len(set(bodies)) == 1 and pub.builds["live"] == before["live"]
    ws, welcome = await _join(client, n=1)
    cid = welcome["creatures"][0]["id"]
    docs = await asyncio.gather(*(fetch(client, f"/public/creature/{cid}.json") for _ in range(50)))
    assert pub.builds["creature"] == 1 and len(set(docs)) == 1 and json.loads(docs[0])["id"] == cid
    await ws.close()


async def test_unknown_creatures_cost_nothing_to_remember(client):
    pub = client.app[PUBLISHER]
    for i in range(200):
        assert (await client.get(f"/public/creature/zz{i}.json")).status == 404
    assert pub._creatures == {} and pub.builds["creature"] == 0


async def test_almanac_and_history(client):
    a = await client.get("/public/almanac.json")
    body = await a.json()
    assert a.headers["Cache-Control"] == "public, max-age=60" and "roadmap" not in body
    assert all(v["about"] for v in body["verbs"]) and isinstance(await (await client.get("/public/history.json")).json(), list)
    assert (await client.get("/public/history.json")).headers["Cache-Control"] == "public, max-age=60"


async def test_proxied_requests_reach_only_public(client):
    for path in ("/api/state", "/api/creature/c1", "/api/nodes", "/api/wishes", "/api/almanac", "/index.html", "/ws",
                 "/almanac.html", "/viewer.js"):
        assert (await client.get(path, headers=TUNNEL)).status == 404, path
    for path in ("/api/voice", "/api/admin/weather", "/api/wishes/w1"):
        assert (await client.post(path, json={}, headers=TUNNEL)).status == 404, path
    for path in ("/ws/view", "/ws/node"):
        with pytest.raises(aiohttp.WSServerHandshakeError) as e:
            await client.ws_connect(path, headers=TUNNEL)
        assert e.value.status == 404
    root = await client.get("/", headers=TUNNEL, allow_redirects=False)
    assert root.status == 302 and root.headers["Location"] == "/public/app/"
    assert (await client.get("/public/live.json", headers=TUNNEL)).status == 200
    assert (await client.get("/api/state")).status == 200          # this machine, no proxy


def private_routes(app, samples: dict) -> list[tuple[str, str]]:
    """Every (method, path) the app answers outside /public/ and /, with real values for the path's parameters."""
    out = []
    for route in app.router.routes():
        canonical = route.resource.canonical
        if route.method == "HEAD" or canonical == "/" or canonical == "/public" or canonical.startswith("/public/"):
            continue
        out.append((route.method, re.sub(r"\{(\w+)\}", lambda m: samples[m.group(1)], canonical)))
    return out


async def test_every_private_route_is_404_through_any_proxy_even_with_the_token(aiohttp_client):
    c = await aiohttp_client(create_app(seed=7, token="secret", tick_seconds=0.02, public_every=3600))
    ws, welcome = await _join(c, n=1, token="secret")
    st = c.app[STATE]
    cid = welcome["creatures"][0]["id"]
    st.wishes.add("Mara", "windmill", "said", "I wish we had a windmill.", st.world.tick)
    wid = st.wishes.ranked(1)[0]["id"]
    routes = private_routes(c.app, {"cid": cid, "wid": wid, "action": "weather", "path": "index.html"})
    assert {("GET", "/ws/node"), ("GET", "/ws/view"), ("POST", "/api/voice"), ("POST", f"/api/wishes/{wid}"),
            ("POST", "/api/admin/weather"), ("GET", "/api/almanac"), ("GET", "/api/state"), ("GET", "/index.html"),
            ("GET", f"/api/creature/{cid}")} <= set(routes)
    # what each steward action would need to change the world, were it to get through
    act = {"text": "hello from outside", "reply": "hi from outside", "weather": "rain"}
    for method, path in routes:
        here = await c.request(method, path, **({"json": {}} if method == "POST" else {}))
        assert here.status != 404, (method, path)  # a handler answers it here, so a 404 below is the guard's
        for name, value in PROXIED.items():
            for token in ({}, {"X-Swarm-Token": "secret"}):
                if token and (method, path) == ("GET", "/api/almanac"):
                    continue
                r = await c.request(method, path, headers={name: value, **token}, **({"json": act} if method == "POST" else {}))
                assert r.status == 404, (method, path, name, token)
    for name, value in PROXIED.items():
        root = await c.get("/", headers={name: value}, allow_redirects=False)
        assert root.status == 302 and root.headers["Location"] == "/public/app/"
        assert (await c.post("/", headers={name: value})).status == 404
        assert (await c.get("/public/live.json", headers={name: value})).status == 200
        assert (await c.get("/api/almanac", headers={name: value, "X-Swarm-Token": "secret"})).status == 200
        with pytest.raises(aiohttp.WSServerHandshakeError) as e:
            await c.ws_connect("/ws/node", headers={name: value, "X-Swarm-Token": "secret"})
        assert e.value.status == 404
    assert not any(e.kind in ("voice", "steward") for e in st.world.events)
    assert not st.wishes.ranked(1)[0]["answer"]
    await ws.close()


async def test_encoded_slashes_and_dot_segments_cannot_slip_out_of_public(client):
    """A naive prefix check on the decoded path would let /public%2F..%2Findex.html through to the file server."""
    cf = b"CF-Connecting-IP: 203.0.113.9\r\n"
    for target in ("/public%2F..%2Findex.html", "/public%2f..%2findex.html", "/public%2F..%2Fviewer.js"):
        status, _ = await raw_get(client, target)
        assert status == 200, target  # from this machine it reaches a file in web/
        status, body = await raw_get(client, target, cf)
        assert status == 404 and b"<html" not in body.lower() and b"function" not in body, target
    for target in ("/public/../index.html", "/public/%2e%2e/index.html", "/public/%2E%2E/api/state",
                   "/public/..%2F..%2Fapi%2Fstate", "/public%2F..%2Fapi%2Fstate", "/public/..%2fapi/voice",
                   "//public/../api/state", "/PUBLIC/live.json", "/public%2Flive.json"):
        status, body = await raw_get(client, target, cf)
        assert status == 404 and b"tiles" not in body and b"<html" not in body.lower(), target
    status, body = await raw_get(client, "/public/live.json", cf)
    assert status == 200


async def test_a_malformed_or_foreign_token_is_refused_never_a_500(aiohttp_client):
    c = await aiohttp_client(create_app(seed=7, token="secret", tick_seconds=0.02, public_every=0))
    cf = b"CF-Connecting-IP: 203.0.113.9\r\n"
    for token in ("sécret".encode(), b"secret\xff", b"\xff\xfe\xfd", b"secret\x80", b"SECRET", b""):
        status, _ = await raw_get(c, "/api/almanac", cf + b"X-Swarm-Token: " + token + b"\r\n")
        assert status == 404, token
    status, _ = await raw_get(c, "/api/almanac", cf + b"X-Swarm-Token: secret\r\n")
    assert status == 200
    odd = await aiohttp_client(create_app(seed=7, token="sécret", tick_seconds=0.02, public_every=0))
    status, _ = await raw_get(odd, "/api/almanac", cf + "X-Swarm-Token: sécret\r\n".encode())
    assert status == 404


def test_token_matches_compares_ascii_bytes():
    assert token_matches("secret", "secret")
    for given, token in (("Secret", "secret"), ("secre", "secret"), ("sécret", "sécret"), ("secret\udcff", "secret"),
                         ("\udcff", "\udcff"), (None, "secret"), ("", ""), ("secret", None), ("secret", ""),
                         (12345, "12345"), (["secret"], "secret"), ({"t": "secret"}, "secret"), (b"secret", "secret"),
                         (True, "secret")):
        assert not token_matches(given, token), (given, token)


async def test_a_node_hello_compares_the_token_as_bytes(aiohttp_client):
    """The brain-node handshake uses the same comparison as the HTTP paths: anything but the exact ASCII token (a
    number, a list, a non-ASCII string, even one equal to a non-ASCII token) is a bad token, never a crash."""
    for token, sent in (("secret", "Secret"), ("secret", 12345), ("secret", ["secret"]), ("secret", {"t": "secret"}),
                        ("secret", None), ("secret", ""), ("secret", "sécret"), ("sécret", "sécret")):
        c = await aiohttp_client(create_app(seed=7, token=token, tick_seconds=0.02, public_every=0))
        ws = await c.ws_connect("/ws/node")
        await ws.send_json({"type": "hello", "node": "x", "token": sent, "slots": 1,
                            "models": [{"tag": "mock", "creatures": 1}], "hardware": {}})
        reply = await ws.receive_json(timeout=5)
        assert reply == {"type": "error", "message": "bad join token"}, (token, sent)
        await ws.close()
        assert not c.app[STATE].nodes, (token, sent)
    c = await aiohttp_client(create_app(seed=7, token="secret", tick_seconds=0.02, public_every=0))
    ws, welcome = await _join(c, n=1, token="secret")
    assert len(welcome["creatures"]) == 1
    await ws.close()


async def test_the_handlers_still_refuse_a_proxied_request_on_their_own(client):
    """The steward checks stay as a second layer behind the guard."""
    app = client.app
    for handler, path, info in ((api_voice, "/api/voice", {}), (api_wish_answer, "/api/wishes/w1", {"wid": "w1"}),
                                (api_admin, "/api/admin/weather", {"action": "weather"}),
                                (api_almanac, "/api/almanac", {})):
        req = make_mocked_request("POST" if handler is not api_almanac else "GET", path, headers=TUNNEL, app=app,
                                  match_info=info)
        with pytest.raises(web.HTTPForbidden):
            await handler(req)


async def test_the_join_token_still_opens_the_almanac_through_a_tunnel(aiohttp_client):
    c = await aiohttp_client(create_app(seed=7, token="secret", tick_seconds=0.02))
    assert (await c.get("/api/almanac", headers={**TUNNEL, "X-Swarm-Token": "secret"})).status == 200
    assert (await c.get("/api/almanac", headers={**TUNNEL, "X-Swarm-Token": "wrong"})).status == 404


async def test_publishing_off(aiohttp_client):
    c = await aiohttp_client(create_app(seed=7, tick_seconds=0.02, public_every=0))
    assert PUBLISHER not in c.app and (await c.get("/public/live.json")).status == 404
    assert (await c.get("/public/live.json", headers=TUNNEL)).status == 404


async def test_publishing_off_still_keeps_public_paths_off_the_file_server(aiohttp_client):
    """With --public-every 0 nothing is published, yet /public/ still never reaches the web/ file server: a dot
    segment can't turn /public/../index.html into a viewer file, and the public app isn't served."""
    c = await aiohttp_client(create_app(seed=7, tick_seconds=0.02, public_every=0))
    for url in ("/public", "/public/", "/public/live.json", "/public/app", "/public/app/", "/public/app/index.html",
                "/public/app/viewer.js", "/public/x"):
        r = await c.get(url)
        assert r.status == 404 and r.headers["Cache-Control"] == "public, max-age=3", url
    for target in ("/public/../index.html", "/public/%2e%2e/viewer.js", "/public/app/../../index.html",
                   "/public/../assets/kenney-1bit/colored_transparent_packed.png"):
        for headers in (b"", b"CF-Connecting-IP: 203.0.113.9\r\n"):
            status, body = await raw_get(c, target, headers)
            assert status == 404 and b"<html" not in body.lower() and b"PNG" not in body, (target, headers)
    assert (await c.get("/index.html")).status == 200   # the private viewer is still there, from this machine


def test_the_cli_has_the_public_flags():
    out = subprocess.run([sys.executable, "-m", "swarmworld.server", "--help"], capture_output=True, text=True).stdout
    assert "--public-every" in out and "--public-link" in out
