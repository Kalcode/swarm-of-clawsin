"""The underground pack I (Task 6): a deep under every world, old saves too, with cave mouths, portals and named caves.

A fresh 128x128 world is 128x288: the surface (rows 0-127), a band of rock (128-159) and the deep (160-287). An old
64x64 save gains its deep (rows 96-159) once, on load, carved from a seed read off its land."""

import json
import random
import zlib
from collections import Counter, deque
from itertools import combinations

from swarmworld.mind.memory import Memory
from swarmworld.mind.prompts import build_act_messages
from swarmworld.server.persistence import restore, save
from swarmworld.server.state import ServerState
from swarmworld.world import registry
from swarmworld.world.actions import Intention, apply_intention, step_activity
from swarmworld.world.caves import carve_deep
from swarmworld.world.model import Creature
from swarmworld.world.packs import underground
from swarmworld.world.perception import REMEMBERED_KINDS, direction, dist, perceive
from swarmworld.world.simulation import Simulation
from swarmworld.world.terrain import generate_world

PORTAL_KINDS = {"cave_mouth": ("cave mouth", {"cave", "cave mouth", "cave entrance", "way down"}),
                "cave_exit": ("cave exit", {"exit", "way up", "way out"}),
                "mine_shaft": ("mine shaft", {"shaft", "mine shaft", "way down"}),
                "ladder": ("ladder", {"ladder", "way up"}),
                "open_pit": ("open pit", {"pit", "open pit", "hole", "way down"})}
CAVE_NAMES = ("the dripping hall", "the crystal cave", "the black seam", "the echoing gallery")


def deep_rows(w):
    _, y0, _, y1 = w.region_bounds("deep")
    return ["".join(w.tiles[y]) for y in range(y0, y1)]


def reachable(w, start):
    """Every tile a creature can walk to from start (orthogonal steps: walking never cuts a corner)."""
    seen, q = {start}, deque([start])
    while q:
        x, y = q.popleft()
        for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if n not in seen and w.walkable(*n) and w.same_region(start, n):
                seen.add(n)
                q.append(n)
    return seen


def person(w, name, x, y, **kw):
    c = Creature(f"c{len(w.creatures) + 1}", name, x, y, asleep=False, **kw)
    w.creatures[c.id] = c
    return c


def test_fresh_world_has_a_deep_below_a_band_of_rock():
    w = generate_world(7)
    assert (w.width, w.height) == (128, 288)
    s, d = w.region("surface"), w.region("deep")
    assert (s.y0, s.y1, s.level, s.sky, s.weather) == (0, 128, 0, True, True)
    assert (d.y0, d.y1, d.level, d.sky, d.weather) == (160, 288, -1, False, False)
    assert all(set(w.tiles[y]) == {"R"} for y in range(128, 160))
    assert not any(128 <= o.y < 160 for o in w.objects.values())
    floor = sum(row.count("c") + row.count("u") for row in deep_rows(w))
    assert 0.3 * 128 * 128 <= floor and "u" in "".join(deep_rows(w))
    assert w.ext["underground"]["seed"] == 7
    assert not w.changed_tiles  # viewers get the whole map in init, not as changes


def test_cave_mouths_pair_with_exits_connected_to_the_caves():
    w = generate_world(7)
    caves = [p for p in underground.portals(w) if p["kind"] == "cave"]
    assert 3 <= len(caves) == len(underground.portals(w)) <= 5
    cx, cy = w.center
    deep = w.region("deep")
    dm = carve_deep(random.Random(underground.deep_seed(w)), w.width, w.region("surface").height)
    mx, my, _ = dm.caverns[0]
    middle = (mx, deep.y0 + my)  # the largest cavern's middle
    seen = Counter()
    for p in caves:
        up, down = tuple(p["up"]), tuple(p["down"])
        mouth, exit_ = w.object_at(*up), w.object_at(*down)
        assert (mouth.kind, exit_.kind) == ("cave_mouth", "cave_exit")
        assert mouth.data["portal"] == exit_.data["portal"] == p["id"]
        assert down == w.below(*up) and w.region_at(*up).name == "surface" and w.region_at(*down) is deep
        assert dist(*up, cx, cy) >= 20 and w.tile(*up) not in "wWRO"
        assert middle in reachable(w, down)
        d = direction(up[0] - cx, up[1] - cy)
        seen[d] += 1
        assert p["name"] == (f"the {d} cave" if seen[d] == 1 else
                             f"the {('second', 'third', 'fourth', 'fifth')[seen[d] - 2]} {d} cave")
    assert all(dist(*a["up"], *b["up"]) >= 12 for a, b in combinations(caves, 2))
    assert [p["id"] for p in caves] == [f"p{i + 1}" for i in range(len(caves))]


def test_cave_mouths_keep_clear_of_what_creatures_made():
    w = generate_world(7, 48, 48, deep=False)
    made = []
    for y in range(0, 48, 7):  # the west half: every tile within 3 of a crop or a campfire someone made
        for x in range(0, 24, 7):
            if (x, y) not in w.grid:
                made.append(w.add_object("crop", x, y, planter="Ana", stage=0) if (x + y) % 2 else
                            w.add_object("campfire", x, y, builder="Bo", lit=False))
    hut = {"x0": 26, "y0": 26, "x1": 45, "y1": 45}  # and a building over the southeast
    w.ext["building"] = {"built": {"b1": hut}}
    underground.grow_deep(w)
    ups = [p["up"] for p in underground.portals(w)]
    assert ups and all(dist(*up, o.x, o.y) > 3 for up in ups for o in made)
    assert not any(hut["x0"] <= x <= hut["x1"] and hut["y0"] <= y <= hut["y1"] for x, y in ups)


def test_named_caves_are_landmarks():
    w = generate_world(7)
    Simulation(w).tick()
    marks = {lm["name"]: lm for lm in w.landmarks}
    deep = w.region("deep")
    for name in (*CAVE_NAMES, "the still pool"):
        assert marks[name]["kind"] == "cave" and w.region_at(marks[name]["x"], marks[name]["y"]) is deep, name
        assert w.tile(marks[name]["x"], marks[name]["y"]) in "cu", name
    assert [c["name"] for c in w.ext["underground"]["caves"]] == [*CAVE_NAMES, "the still pool"]
    for p in underground.portals(w):
        assert (marks[p["name"]]["kind"], [marks[p["name"]]["x"], marks[p["name"]]["y"]]) == ("way down", p["up"])
        up = marks[f"the way up to {p['name']}"]
        assert (up["kind"], [up["x"], up["y"]]) == ("way up", p["down"])
    hall = marks["the dripping hall"]
    low = person(w, "Low", hall["x"], hall["y"])
    top = person(w, "Top", *w.center)
    assert "you are at the dripping hall" in perceive(w, low)
    assert "dripping hall" not in perceive(w, top)  # landmarks are heard of only in their own region


def test_portals_add_and_remove(two_levels):
    w = two_levels(24, gap=0)  # the surface is rows 0-23, the deep 24-47, right below it
    p = underground.add_portal(w, "shaft", "the test shaft", (5, 23), (5, 47))
    assert p == {"id": "p1", "kind": "shaft", "name": "the test shaft", "up": [5, 23], "down": [5, 47]}
    assert underground.portals(w) == [p]
    top, low = w.object_at(5, 23), w.object_at(5, 47)
    assert (top.kind, low.kind) == ("mine_shaft", "ladder") and top.data["portal"] == low.data["portal"] == "p1"
    assert underground.portal_near(w, 6, 22) == (p, "up") and underground.portal_near(w, 5, 23) == (p, "up")
    assert underground.portal_near(w, 4, 46) == (p, "down")
    assert underground.portal_near(w, 5, 24) is None  # a step from the shaft, but in the deep
    assert underground.portal_near(w, 8, 23) is None and underground.portal_near(w, 8, 23, reach=3) == (p, "up")
    pit = underground.add_portal(w, "pit", "the test pit", (15, 10), (15, 34))
    assert pit["id"] == "p2" and w.object_at(15, 10).kind == "open_pit" and w.object_at(15, 34).kind == "ladder"
    underground.remove_portal(w, "p1")
    assert underground.portals(w) == [pit] and w.object_at(5, 23) is None and w.object_at(5, 47) is None
    assert w.object_at(15, 34).data["portal"] == "p2" and underground.portal_near(w, 5, 23) is None
    assert underground.add_portal(w, "shaft", "another shaft", (5, 23), (5, 47))["id"] == "p3"
    for kind, (name, aliases) in PORTAL_KINDS.items():
        spec = registry.KINDS[kind]
        assert spec["name"] == name and set(spec["aliases"]) == aliases and not spec["blocking"], kind
        assert spec["look"] and spec["glyph"]["char"] and kind in REMEMBERED_KINDS, kind


def test_deep_is_the_same_for_the_same_seed():
    a, b, c = generate_world(7, 48, 48), generate_world(7, 48, 48), generate_world(8, 48, 48)
    assert deep_rows(a) == deep_rows(b) and a.ext["underground"] == b.ext["underground"]
    assert underground.portals(a) and underground.portals(a) == underground.portals(b)
    assert deep_rows(c) != deep_rows(a)


def test_old_save_deep_seed_comes_from_its_land(prepack_save):
    saved = json.loads(prepack_save.read_text())["world"]
    assert saved.get("seed") is None  # a save from before seeds were kept
    worlds = []
    for seed in (1, 2):  # whatever world the server made first
        st = ServerState(seed=seed)
        restore(st, prepack_save)
        worlds.append(st.world)
    a, b = worlds
    land = zlib.crc32("\n".join(saved["tiles"]).encode())  # the old save's rows
    assert a.ext["underground"]["seed"] == b.ext["underground"]["seed"] == land
    assert deep_rows(a) == deep_rows(b) and underground.portals(a) == underground.portals(b)


def test_old_save_gains_a_deep_once(prepack_save, tmp_path):
    saved = json.loads(prepack_save.read_text())["world"]
    st = ServerState(seed=1)
    restore(st, prepack_save)
    w = st.world
    assert (w.width, w.height) == (64, 160)
    assert [(r.name, r.y0, r.y1) for r in w.regions] == [("surface", 0, 64), ("deep", 96, 160)]
    assert ["".join(w.tiles[y]) for y in range(64)] == saved["tiles"]  # the old land is untouched
    old = {(o["id"], o["kind"], o["x"], o["y"]) for o in saved["objects"]}
    assert old <= {(o.id, o.kind, o.x, o.y) for o in w.objects.values()}
    ps = underground.portals(w)
    assert ps and all(dist(*p["up"], *w.center) >= 64 // 4 for p in ps)
    assert all((w.object_at(*p["up"]).kind, w.object_at(*p["down"]).kind) == ("cave_mouth", "cave_exit") for p in ps)
    built = [o for o in w.objects.values() if o.data.get("builder") or o.data.get("planter")]
    assert built and all(dist(*p["up"], o.x, o.y) > 3 for p in ps for o in built)
    tiles, portals = ["".join(r) for r in w.tiles], [dict(p) for p in ps]
    ends = sorted((o.kind, o.x, o.y, o.data["portal"]) for o in w.objects.values() if "portal" in o.data)
    save(st, tmp_path / "w.json")
    st2 = ServerState(seed=5)
    restore(st2, tmp_path / "w.json")
    w2 = st2.world
    assert [(r.name, r.y0, r.y1) for r in w2.regions] == [("surface", 0, 64), ("deep", 96, 160)]
    assert ["".join(r) for r in w2.tiles] == tiles and underground.portals(w2) == portals
    assert sorted((o.kind, o.x, o.y, o.data["portal"]) for o in w2.objects.values() if "portal" in o.data) == ends


def test_underground_never_draws_from_the_worlds_rng():
    w = generate_world(7, 48, 48, deep=False)
    assert w.region("deep") is None and "underground" not in w.ext
    world_dice, given = w.rng.getstate(), random.Random(3)
    given_dice = given.getstate()
    populate = next(p.fn for p in registry.POPULATE if p.name == "underground")
    populate(w, given, False)  # as on a restored save: the world's rng, or the generator's, is handed in
    assert w.region("deep") is not None and underground.portals(w)
    assert w.rng.getstate() == world_dice and given.getstate() == given_dice
    rows, ends = deep_rows(w), len(w.objects)
    underground.grow_deep(w)  # once is all
    assert len(w.regions) == 2 and deep_rows(w) == rows and len(w.objects) == ends


def test_surface_unchanged_by_the_underground_pack():
    with registry.sandbox():
        registry.POPULATE[:] = [p for p in registry.POPULATE if p.name != "underground"]
        a = generate_world(7, 48, 48)
    b = generate_world(7, 48, 48)
    assert a.region("deep") is None and b.region("deep") is not None
    assert a.tiles == b.tiles[:48]
    ends = {o.id for o in b.objects.values() if "portal" in o.data}
    assert ends and sorted((o.kind, o.x, o.y) for o in a.objects.values()) == sorted(
        (o.kind, o.x, o.y) for o in b.objects.values() if o.id not in ends and o.y < 48)  # the deep's own things aside
    persona = {"traits": ["curious", "patient"], "drive": "curious", "initiative": "proactive"}
    tams = [person(w, "Tam", *w.center, persona=dict(persona)) for w in (a, b)]
    for w in (a, b):
        Simulation(w).tick()  # the landmarks are worked out
    assert any(lm["kind"] == "way down" for lm in b.landmarks)
    views = [perceive(w, c) for w, c in zip((a, b), tams)]
    assert views[0] == views[1]
    msgs = [build_act_messages(w, c, Memory(), v) for w, c, v in zip((a, b), tams, views)]
    assert msgs[0] == msgs[1]


# ------------------------------------------------------------------ Task 7: what lies in the deep
SURFACE_VEINS = ("iron_vein", "copper_vein")
DEEP_KINDS = {"iron_vein", "copper_vein", "coal_seam", "crystal_cluster", "cave_mushrooms", "rock", "cave_exit", "ladder",
             "terminal", "tablet"}  # the ancient terminal and its tablet


def count_kinds(w, region):
    y0, y1 = w.region(region).y0, w.region(region).y1
    return Counter(o.kind for o in w.objects.values() if y0 <= o.y < y1)


def gather(w, c, target):
    res = apply_intention(w, c, Intention("gather", target=target))
    while c.activity:
        step_activity(w, c)
    return res


def test_deep_objects_lie_on_cave_floor_only():
    w = generate_world(7)
    y0, y1 = w.region("deep").y0, w.region("deep").y1
    things = [o for o in w.objects.values() if o.y >= y0]
    assert things and {o.kind for o in things} <= DEEP_KINDS
    assert {o.kind for o in things} >= DEEP_KINDS - {"ladder"}
    assert all(y0 <= o.y < y1 and w.tile(o.x, o.y) == "c" for o in things)
    n = count_kinds(w, "deep")
    assert n["crystal_cluster"] >= 2 and n["coal_seam"] >= 2 and n["cave_mushrooms"] >= 2
    spots = [(o.x, o.y) for o in things if o.kind not in ("cave_exit", "ladder")]
    exits = [(o.x, o.y) for o in things if o.kind == "cave_exit"]
    assert all(dist(*a, *b) >= 2 for a in spots for b in exits)
    for o in things:
        if o.kind in ("iron_vein", "copper_vein", "coal_seam", "crystal_cluster"):
            assert any(w.tile(o.x + dx, o.y + dy) in "R" for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))), o
            if "vein" in o.kind:
                assert o.data["ore"] == 8


def test_the_deep_keeps_its_caves_connected_around_what_lies_in_it():
    w = generate_world(7)
    start = tuple(underground.portals(w)[0]["down"])
    open_floor = {(x, y) for y in range(w.region("deep").y0, w.region("deep").y1) for x in range(w.width)
                  if w.walkable(x, y)}
    assert all(p in reachable(w, start) for p in [tuple(q["down"]) for q in underground.portals(w)])
    assert len(reachable(w, start)) >= 0.9 * len(open_floor)


def test_the_deep_is_richer_in_ore():
    w = generate_world(7)
    top, low = count_kinds(w, "surface"), count_kinds(w, "deep")
    for kind in SURFACE_VEINS:
        assert low[kind] > top[kind], kind


def test_coal_and_crystal_are_mined_with_any_pickaxe(two_levels):
    w = two_levels(24)
    c = person(w, "Tam", 5, 5)
    w.add_object("coal_seam", 6, 5)
    w.add_object("crystal_cluster", 5, 6)
    res = gather(w, c, "coal seam")
    assert not res.ok and res.message == "You'd need a pickaxe to gather from the coal seam."
    assert not c.inventory.get("coal")
    c.inventory["copper_pickaxe"] = 1
    assert gather(w, c, "coal seam").ok and 1 <= c.inventory["coal"] <= 2
    assert gather(w, c, "crystal cluster").ok and c.inventory["crystal"] == 1
    d = person(w, "Bo", 8, 8)
    d.inventory["stone_pickaxe"] = 1
    w.add_object("coal_seam", 9, 8)
    assert gather(w, d, "coal seam").ok and d.inventory["coal"] >= 1


def test_coal_means_coal_not_charcoal(two_levels):
    cat = two_levels(8).catalog
    assert cat.resolve("coal") == "coal" and cat.resolve("charcoal") == "charcoal"
    for alias in ("lump of coal", "coal lump", "black rock"):
        assert cat.resolve(alias) == "coal"
    assert "fuel" in cat.items["coal"].tags
    assert cat.name("crystal") == "crystal" and all(cat.resolve(a) == "crystal" for a in ("crystals", "glowing crystal", "quartz"))
    for kind, glow in (("coal_seam", None), ("crystal_cluster", 2)):
        assert registry.KINDS[kind]["blocking"] and registry.KINDS[kind].get("glow") == glow
        assert kind in REMEMBERED_KINDS


def test_cave_mushrooms_glow_and_regrow(two_levels):
    w = two_levels(24)
    c = person(w, "Tam", 5, 5)
    assert registry.KINDS["cave_mushrooms"]["glow"] == 1 and "glowcaps" in registry.KINDS["cave_mushrooms"]["aliases"]
    patch = w.add_object("cave_mushrooms", 6, 5)
    sim = Simulation(w)
    for _ in range(3):
        assert gather(w, c, "cave mushrooms").ok
    assert patch.kind == "cave_mushrooms_picked" and c.inventory["mushroom"] >= 3
    assert not gather(w, c, "cave mushrooms").ok
    back = patch.data["regrow_at"]
    assert back - w.tick == 900
    sim._regrow(back - 1)
    assert patch.kind == "cave_mushrooms_picked"
    sim._regrow(back)
    assert patch.kind == "cave_mushrooms" and gather(w, c, "cave mushrooms").ok


def test_deep_things_placed_once(prepack_save, tmp_path):
    st = ServerState(seed=1)
    restore(st, prepack_save)
    first = Counter(o.kind for o in st.world.objects.values())
    assert st.world.ext["underground"]["placed"] and first["coal_seam"] >= 2 and first["crystal_cluster"] >= 2
    save(st, tmp_path / "a.json")
    st2 = ServerState(seed=9)
    restore(st2, tmp_path / "a.json")
    assert Counter(o.kind for o in st2.world.objects.values()) == first
    assert sorted((o.kind, o.x, o.y) for o in st2.world.objects.values()) == sorted(
        (o.kind, o.x, o.y) for o in st.world.objects.values())


def test_placement_rolls_the_packs_own_dice():
    a, b = generate_world(7, 48, 48), generate_world(7, 48, 48)
    deep = lambda w: sorted((o.kind, o.x, o.y) for o in w.objects.values() if o.y >= w.region("deep").y0)
    assert deep(a) == deep(b)
    n = count_kinds(a, "deep")
    assert all(n[k] >= 2 for k in ("iron_vein", "copper_vein", "coal_seam", "crystal_cluster", "cave_mushrooms", "rock"))


def test_ore_clusters_near_their_named_caves():
    w = generate_world(7)
    marks = {c["name"]: c for c in w.ext["underground"]["caves"]}
    for kind, cave in (("crystal_cluster", "the crystal cave"), ("coal_seam", "the black seam")):
        mine = [o for o in w.objects.values() if o.kind == kind]
        near = [o for o in mine if dist(o.x, o.y, marks[cave]["x"], marks[cave]["y"]) <= 6]
        assert len(near) >= 4, kind  # a third were asked for, as many as the room allows


def test_portal_ids_are_never_reused(two_levels):
    w = two_levels(24, gap=0)
    a = underground.add_portal(w, "shaft", "a", (5, 23), (5, 47))
    b = underground.add_portal(w, "shaft", "b", (9, 23), (9, 47))
    underground.remove_portal(w, b["id"])
    c = underground.add_portal(w, "shaft", "c", (12, 23), (12, 47))
    assert (a["id"], b["id"], c["id"]) == ("p1", "p2", "p3")
    assert w.ext["underground"]["next_portal"] == 4
    del w.ext["underground"]["next_portal"]  # an older state: counts on from the highest there is
    assert underground.add_portal(w, "shaft", "d", (15, 23), (15, 47))["id"] == "p4"


def test_named_caves_stand_on_dry_floor_apart():
    for seed in (7, 8, 9):
        w = generate_world(seed)
        caves = w.ext["underground"]["caves"]
        spots = [(c["x"], c["y"]) for c in caves]
        assert all(w.tile(*s) == "c" for s in spots), seed
        assert len(set(spots)) == len(spots)
        ends = {tuple(p["down"]) for p in underground.portals(w)}
        assert not ends & set(spots)
        assert all(w.region_at(*s).name == "deep" for s in spots)
