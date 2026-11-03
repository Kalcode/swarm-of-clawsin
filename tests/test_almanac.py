"""The almanac (GET /api/almanac): everything in the game, this world's discoveries and census, and the roadmap."""

import asyncio
from collections import Counter

import pytest

from swarmworld.server.almanac import Almanac, build, roadmap
from swarmworld.server.app import STATE, create_app
from swarmworld.server.persistence import restore, save
from swarmworld.server.state import ServerState
from swarmworld.world.actions import Intention, apply_intention
from swarmworld.world.registry import KINDS, STORES, VERBS

README = """# Issues

Backlog notes.

| # | Priority | Label | Title | Status |
|---|---|---|---|---|
| [001](001-say.md) | P0 | bug | `say` with empty `text` fails | fixed, live after the next world restart |
| [002](002-gemma.md) | P0 | models | Find a better second mind | open |
| [003](003-almanac.md) | P1 | viewer | An almanac: tech tree, census | in progress |
| 004 | P3 | polish | No file for this one | open |
"""
ISSUES = {
    "001-say.md": "# 001: say\n\n**Priority:** P0 · **Label:** bug · **Status:** fixed\n\n## Problem\n\n"
                  "When a creature picks `say` it often puts its words in **speech**.\nThe world refuses.\n\n## Proposal\n\nUse it.\n",
    "002-gemma.md": "# 002: Gemma\n\n**Priority:** P0 · **Label:** models · **Status:** open\n\n"
                    "How to run it: [docs/distillation.md](../docs/distillation.md).\n\n## Problem\n\n"
                    "Gemma talks but rarely [makes things](notes.md).\n\n| a | b |\n|---|---|\n",
    "003-almanac.md": "# 003: Almanac\n\n**Priority:** P1 · **Label:** viewer · **Status:** in progress\n\n"
                      "- a list item first\n\n\"Maybe a tech tree,\" said the user.\n",
}


@pytest.fixture
def issues_dir(tmp_path):
    d = tmp_path / "issues"
    d.mkdir()
    (d / "README.md").write_text(README)
    for name, text in ISSUES.items():
        (d / name).write_text(text)
    return d


@pytest.fixture
def st():
    return ServerState(seed=7)


def _discover(st):
    """A creature combines its way to a recipe that isn't known at start: the world records the discovery."""
    c = st.new_creature("mock")
    c.asleep = False
    r = next(r for r in st.world.catalog.recipes if not r.known_at_start and not r.station and not r.tools)
    c.inventory.update(r.inputs)
    res = apply_intention(st.world, c, Intention("combine", items=[st.world.catalog.name(i) for i in r.inputs]))
    assert res.ok, res.message
    return c, r


def test_almanac_shape_and_every_recipe_resolves(st, issues_dir):
    a = build(st, issues_dir)
    for key in ("tick", "day", "packs", "items", "recipes", "processes", "designs", "kinds", "verbs", "techniques",
                "systems", "perception", "populate", "harness", "tree", "world", "roadmap", "inventions"):
        assert key in a, key
    items = {i["id"]: i for i in a["items"]}
    assert set(items) == set(st.world.catalog.items)
    for i in items.values():
        assert {"id", "name", "aliases", "tags", "food", "desc", "pack", "tier", "status", "sources"} <= set(i)
    for r in a["recipes"] + a["processes"]:
        assert r["output"] in items, r
        for i in [*r["inputs"], *r.get("tools", [])] + ([r["station"]] if r.get("station") else []):
            assert i in items, (r["output"], i)
        assert {"output", "inputs", "tools", "station", "count", "known_at_start", "pack"} <= set(r)
    for d in a["designs"]:
        assert all(i in items for i in d["needs"]), d
    assert {r["output"] for r in a["recipes"]} == {r.output for r in st.world.catalog.recipes}
    # the tech tree: every edge joins two of its nodes, and a thing sits in a later tier than what it's made from
    nodes = {n["id"]: n for n in a["tree"]["nodes"]}
    assert set(items) <= set(nodes)
    for e in a["tree"]["edges"]:
        assert e["from"] in nodes and e["to"] in nodes and e["kind"] in ("input", "tool", "station", "gather_tool")
        assert nodes[e["from"]]["tier"] < nodes[e["to"]]["tier"] or e.get("back"), e
    assert not any(e.get("back") for e in a["tree"]["edges"] if e["kind"] == "gather_tool")
    assert {"from": "stone_pickaxe", "to": "copper_ore", "kind": "gather_tool"} in a["tree"]["edges"]
    assert items["stick"]["tier"] == 0 and items["stone"]["tier"] == 0
    assert items["log"]["tier"] > items["stone_axe"]["tier"] > 0  # logs need an axe
    assert any(s["how"] == "gather" and s["source"] == "tree" for s in items["stick"]["sources"])
    # kinds, verbs and packs
    kinds = {k["id"]: k for k in a["kinds"]}
    assert set(kinds) == set(KINDS)
    for k in kinds.values():
        assert {"id", "name", "pack", "look", "glyph", "yields", "gives", "blocking", "animal", "store", "station",
                "category", "count"} <= set(k)
    assert kinds["deer"]["pack"] == "food" and kinds["deer"]["wary"] == 5 and kinds["deer"]["habitat"]
    assert kinds["campfire"]["station"] and kinds["tree"]["pack"] == "core"
    verbs = {v["name"]: v for v in a["verbs"]}
    assert set(verbs) == set(VERBS)
    for v in verbs.values():
        assert v["tip"] and v["shown"] and v["pack"], v
    assert verbs["hunt"]["pack"] == "food" and "spear" in verbs["hunt"]["tip"]
    assert verbs["gather"]["pack"] == "core" and verbs["gather"]["shown"].startswith("Always")
    assert "drop (target)" in verbs["drop"]["tip"] and "on the ground" in verbs["drop"]["shown"]
    assert [u["name"] for u in verbs["give"]["uses"]] == ["fire", "feed"]
    packs = {p["id"]: p for p in a["packs"]}
    assert {"core", "food", "building", "nature", "play", "sound", "weather"} <= set(packs)
    assert packs["food"]["verbs"] == 2 and packs["food"]["items"] > 0 and packs["food"]["systems"] >= 1
    assert sum(p["items"] for p in packs.values()) == len(items)
    assert [h["name"] for h in a["harness"]] == ["plan", "disclose", "recall"]
    assert a["roadmap"]["issues"], "the roadmap comes along"


def test_roadmap_is_parsed_from_the_readme(issues_dir):
    rm = roadmap(issues_dir)
    by = {i["number"]: i for i in rm["issues"]}
    assert list(by) == ["001", "002", "003", "004"]
    assert by["001"] == {**by["001"], "priority": "P0", "label": "bug", "title": "`say` with empty `text` fails",
                         "status": "fixed, live after the next world restart", "state": "fixed", "file": "001-say.md"}
    assert by["002"]["state"] == "open" and by["003"]["state"] == "progress"
    # the summary is the first paragraph of prose (not a pointer to another doc, a heading, a list or a table)
    assert by["001"]["summary"] == "When a creature picks `say` it often puts its words in speech. The world refuses."
    assert by["002"]["summary"] == "Gemma talks but rarely makes things."
    assert by["003"]["summary"] == "\"Maybe a tech tree,\" said the user."
    assert by["004"]["file"] is None and by["004"]["summary"] == ""
    assert rm["counts"] == {"open": 2, "progress": 1, "fixed": 1}


def test_roadmap_without_a_backlog(tmp_path):
    assert roadmap(tmp_path / "nowhere")["issues"] == []


def test_discoveries_and_who_knows_what(st, issues_dir):
    c, r = _discover(st)
    a = build(st, issues_dir)
    item = next(i for i in a["items"] if i["id"] == r.output)
    assert item["status"] == "found"
    assert item["discovered"]["by"] == c.name and item["discovered"]["model"] == "mock"
    assert item["discovered"]["tick"] == st.world.tick
    start = next(i for i in a["items"] if i["id"] == next(x.output for x in st.world.catalog.recipes if x.known_at_start))
    assert start["status"] == "start"
    assert any(i["status"] == "unfound" for i in a["items"])
    assert next(i for i in a["items"] if i["id"] == "stick")["status"] == "raw"
    found = a["world"]["discoveries"]
    assert [d["item"] for d in found] == [r.output] and found[0]["by"] == c.name and found[0]["day"] >= 1
    me = next(x for x in a["world"]["creatures"] if x["id"] == c.id)
    assert r.output in me["known"] and me["model"] == "mock"


def test_inventions_join_the_tree(st, issues_dir):
    c = st.new_creature("mock")
    c.asleep = False
    c.inventory.update({"stick": 2, "flower": 1})
    res = apply_intention(st.world, c, Intention("invent", target="flower wand", items=["stick", "flower"],
                                                 text="a stick with a flower that cheers people up"))
    assert res.ok, res.message
    a = build(st, issues_dir)
    inv = next(i for i in a["items"] if i["id"] == "inv_flower_wand")
    assert inv["status"] == "invented" and inv["pack"] == "invented" and inv["discovered"]["by"] == c.name
    assert any(r["output"] == "inv_flower_wand" and r["pack"] == "invented" for r in a["recipes"])
    assert a["inventions"][0]["id"] == "inv_flower_wand"
    assert inv["tier"] > 0


def test_census_counts_the_map_pockets_and_stores(st, issues_dir):
    w = st.world
    c = st.new_creature("mock")
    c.inventory.update({"stick": 3, "berries": 2})
    x, y = next((x, y) for y in range(w.height) for x in range(w.width) if w.walkable(x, y) and not w.object_at(x, y))
    w.add_object("basket", x, y, items={"stick": 4})
    w.ground[(1, 1)] = Counter({"stone": 5})
    a = build(st, issues_dir)
    now = a["world"]
    assert now["kinds"] == dict(Counter(o.kind for o in w.objects.values()))
    assert now["items"]["stick"]["carried"] >= 3 and now["items"]["stick"]["stored"] >= 4
    assert now["items"]["stone"]["ground"] >= 5
    kinds = {k["id"]: k for k in a["kinds"]}
    assert kinds["tree"]["count"] == now["kinds"].get("tree", 0) > 0
    assert set(now["groups"]) >= {"animals", "plants", "built"}
    assert now["groups"]["animals"]["count"] == sum(n for k, n in now["kinds"].items() if KINDS[k]["animal"])


def test_cached_for_the_tick(st, issues_dir):
    alm = Almanac(issues_dir)
    first = alm.get(st)
    assert alm.get(st) is first
    st.world.tick += 1
    assert alm.get(st) is not first


def test_verb_use_is_counted_and_saved(st, tmp_path):
    st.metrics.verb("mock", "gather", True)
    st.metrics.verb("mock", "gather", False)
    st.metrics.verb("qwen", "say", True)
    path = tmp_path / "w.json"
    save(st, path)
    again = ServerState(seed=7)
    restore(again, path)
    a = build(again, tmp_path)
    used = {v["name"]: v["used"] for v in a["verbs"]}
    assert used["gather"] == {"tries": 2, "ok": 1, "by_model": {"mock": 2}}
    assert used["say"]["tries"] == 1 and used["eat"]["tries"] == 0
    assert a["world"]["verbs_since"] == 0


def test_an_old_save_counts_verbs_from_when_it_was_restored(prepack_save, tmp_path):
    st = ServerState(seed=1)
    restore(st, prepack_save)
    assert build(st, tmp_path)["world"]["verbs_since"] == st.world.tick


@pytest.fixture
async def client(aiohttp_client):
    return await aiohttp_client(create_app(seed=7, tick_seconds=0.02))


async def test_api_almanac_counts_what_creatures_do(client):
    ws = await client.ws_connect("/ws/node")
    await ws.send_json({"type": "hello", "node": "laptop", "slots": 4, "models": [{"tag": "mock", "creatures": 1}],
                        "hardware": {}})
    while (job := await asyncio.wait_for(ws.receive_json(), 5))["type"] != "think":
        pass
    await ws.send_json({"type": "result", "job": job["job"], "ok": True, "latency_ms": 10, "tokens_in": 5, "tokens_out": 5,
                        "output": {"thought": "hi", "action": "say", "target": "", "items": [], "text": "Hello",
                                   "count": 1, "goal": ""}})
    for _ in range(100):
        resp = await client.get("/api/almanac")
        assert resp.status == 200
        a = await resp.json()
        say = next(v for v in a["verbs"] if v["name"] == "say")
        if say["used"]["tries"]:
            break
        await asyncio.sleep(0.02)
    assert say["used"] == {"tries": 1, "ok": 1, "by_model": {"mock": 1}}
    assert a["roadmap"]["issues"], "the real backlog, from issues/README.md"
    await ws.close()


async def test_api_almanac_is_for_this_machine_or_the_token(client, aiohttp_client):
    tunnel = {"CF-Connecting-IP": "203.0.113.9"}
    assert (await client.get("/api/almanac", headers=tunnel)).status == 403
    with_token = await aiohttp_client(create_app(seed=7, token="secret", tick_seconds=0.02))
    assert (await with_token.get("/api/almanac", headers=tunnel)).status == 403
    ok = await with_token.get("/api/almanac", headers={**tunnel, "X-Swarm-Token": "secret"})
    assert ok.status == 200 and (await ok.json())["items"]
    page = await client.get("/almanac.html")
    assert page.status == 200 and "almanac.js" in await page.text()
    assert client.app[STATE].world.tick >= 0
