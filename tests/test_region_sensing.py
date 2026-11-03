"""Nothing crosses a region: sight, sound, speech, landmarks, remembered spots and terminals (Task 2).

Most tests use two_levels(24, gap=0): the deep's rows are 24-47, so a surface creature at (12, 22) and a deep one at
(12, 26) are 4 steps apart, within sight and earshot but for the rule."""

import pytest

from swarmworld.scripting.terminal import run_terminal
from swarmworld.world import actions, registry
from swarmworld.world.actions import Intention, apply_intention, find_landmark, landmark_elsewhere
from swarmworld.world.events import hearers
from swarmworld.world.model import START_TICK, Creature
from swarmworld.world.perception import (_far_features, note_spots, perceive, visible_creatures, visible_objects,
                                         visible_piles)
from swarmworld.world.simulation import Simulation


def person(w, name, x, y):
    c = Creature(f"c{len(w.creatures) + 1}", name, x, y, asleep=False)
    w.creatures[c.id] = c
    return c


@pytest.fixture
def pair(two_levels):
    w = two_levels(24, gap=0)
    w.tick = START_TICK + 100  # morning
    return w, person(w, "Top", 12, 22), person(w, "Low", 12, 26)


def test_no_sight_across_regions(pair):
    w, top, low = pair
    w.add_object("rock", 12, 27)  # in the deep, beside Low
    w.add_object("bush", 12, 21)  # on the surface, beside Top
    w.drop_items(13, 26, {"stick": 1})
    w.drop_items(13, 20, {"stone": 1})
    assert [o.kind for o, _, _ in visible_objects(w, top)] == ["bush"]
    assert [o.kind for o, _, _ in visible_objects(w, low)] == ["rock"]
    assert visible_creatures(w, top) == [] and visible_creatures(w, low) == []
    assert [(x, y) for x, y, _, _ in visible_piles(w, top)] == [(13, 20)]
    assert [(x, y) for x, y, _, _ in visible_piles(w, low)] == [(13, 26)]
    text_top, text_low = perceive(w, top), perceive(w, low)
    assert "rock" not in text_top and "Low" not in text_top and "stick" not in text_top
    assert "bush" not in text_low and "Top" not in text_low and "1 stone" not in text_low
    w.tiles[27][14] = "w"  # water in the deep: not "Around you" on the surface
    w.tiles[20][3] = "s"  # sand on the surface, 9 steps away: out of the deep's reach too
    assert "water" not in (_far_features(w, top, 6) or "")
    assert "sand" not in (_far_features(w, low, 12) or "")
    assert "water" in _far_features(w, low, 6)


def test_no_sound_or_speech_across_regions(pair):
    w, top, low = pair
    sim = Simulation(w)
    assert [h.id for h in hearers(w, top.x, top.y, 8)] == [top.id]  # 4 steps off, but not the same region
    assert [h.id for h in hearers(w, low.x, low.y, 8)] == [low.id]
    apply_intention(w, top, Intention("say", text="hello down there"))
    w.sound(12, 22, "a loud crash", radius=8, kind="crash", loud=True, source=top.id)
    w.emit("craft", top.id, top.x, top.y, "Top made a stick", item="stick")
    sim._process_events()
    assert not sim.heard[low.id] and not sim.sounds[low.id]
    assert not any("watched" in m for m in getattr(low, "memories", []))
    apply_intention(w, low, Intention("say", text="can you hear me"))
    sim._process_events()
    assert not sim.heard[top.id]
    # the same region still hears
    near = person(w, "Near", 12, 20)
    apply_intention(w, top, Intention("say", text="over here"))
    w.sound(12, 22, "chopping", radius=8, kind="chop", source=top.id)
    sim._process_events()
    assert any("over here" in h for h in sim.heard[near.id]) and sim.sounds[near.id]


def test_landmarks_stay_in_their_region(pair):
    w, top, low = pair
    w.landmarks = [{"name": "the dripping hall", "x": 12, "y": 28, "kind": "hall", "size": 1},
                   {"name": "the old oak", "x": 12, "y": 19, "kind": "tree", "size": 1}]
    assert "dripping hall" not in perceive(w, top) and "old oak" in perceive(w, top)
    assert "old oak" not in perceive(w, low) and "dripping hall" in perceive(w, low)
    note_spots(w, top, w.tick)
    assert top.landmarks_seen == {"the old oak"}
    assert find_landmark(w, top, "the dripping hall") is None
    assert landmark_elsewhere(w, top, "the dripping hall")["name"] == "the dripping hall"
    assert landmark_elsewhere(w, top, "the old oak") is None
    assert find_landmark(w, low, "the dripping hall")["name"] == "the dripping hall"
    res = apply_intention(w, top, Intention("walk_to", target="the dripping hall"))
    assert not res.ok and res.message.startswith("The deep is below") and top.activity is None


def test_walk_to_a_place_below_says_how_to_get_there(pair, monkeypatch):
    w, top, low = pair
    w.landmarks = [{"name": "the dripping hall", "x": 12, "y": 28, "kind": "hall", "size": 1}]
    monkeypatch.setattr(actions, "way_to_region", lambda w, c, r: f"WAY TO {r.name}")
    assert apply_intention(w, top, Intention("walk_to", target="the dripping hall")).message == "WAY TO deep"


def test_remembered_spots_stay_in_their_region(pair):
    w, top, low = pair
    top.spots["rock"] = (12, 30, w.tick)  # a spot below the surface creature
    low.spots["bush"] = (12, 20, w.tick)  # a spot above the deep creature
    assert "You remember" not in perceive(w, top) and "You remember" not in perceive(w, low)
    assert actions._recall(w, top, "rock") is None and actions._recall(w, low, "bush") is None
    res = apply_intention(w, top, Intention("walk_to", target="rock"))
    assert not res.ok and res.message.startswith("The deep is below")  # the underground pack tells the way
    top.spots["tree"] = (12, 18, w.tick)
    assert "You remember: oak tree" in perceive(w, top)
    assert actions._recall(w, top, "tree") == ("tree", 12, 18)


def test_terminal_scan_and_find_stay_in_region(pair):
    w, top, low = pair
    w.add_object("rock", 12, 24)  # 2 rows below the terminal, in the deep
    term = w.add_object("terminal", 12, 22, code="find('rock')")
    run_terminal(w, term)
    assert term.data["screen"][-1] == "nil"
    term.data["code"] = "scan(5)"
    run_terminal(w, term)
    assert "rock" not in " ".join(term.data["screen"][1:]) and "Low" not in " ".join(term.data["screen"][1:])
    deep_term = w.add_object("terminal", 14, 24, code="find('rock')")
    run_terminal(w, deep_term)
    assert "rock" in deep_term.data["screen"][-1]


def test_voice_with_a_radius_stays_in_its_region():
    from swarmworld.server.state import ServerState
    from swarmworld.world.terrain import generate_world
    st = ServerState(seed=7)
    w = st.world = st.sim.world = generate_world(7, deep=False)  # a surface alone, for a deep right below it
    w.add_region("deep", -1, [["c"] * w.width for _ in range(w.height)], sky=False, weather=False, gap=0)
    top = person(w, "Top", 60, 126)
    low = person(w, "Low", 60, 130)
    reached = st.voice_from_the_sky("hello", 60, 126, 6)
    assert reached == ["Top"]
    assert any("hello" in h for h in st.sim.heard[top.id]) and not st.sim.heard[low.id]
    assert st.voice_from_the_sky("everyone") == ["Top", "Low"]  # no position: the whole world
    w.tiles[10][10] = "u"
    with pytest.raises(ValueError):
        st._free_tile(10, 10)


def test_handoff_routes_a_verb_case(pair):
    w, top, low = pair
    before = list(registry.HANDOFFS)  # the packs' own (walk_to -> climb)
    with registry.sandbox():
        registry.register_handoff("wait", "rest", lambda w, c, it: it.target == "x")
        registry.register_handoff("wait", "gather", lambda w, c, it: True)
        calls = []
        registry.HANDLERS["rest"] = lambda w, c, it: calls.append("rest") or actions.ActionResult(True, "rested")
        registry.HANDLERS["gather"] = lambda w, c, it: calls.append("gather") or actions.ActionResult(True, "gathered")
        registry.HANDLERS["wait"] = lambda w, c, it: calls.append("wait") or actions.ActionResult(True, "waited")
        assert apply_intention(w, top, Intention("wait", target="x")).message == "rested"
        assert apply_intention(w, top, Intention("wait", target="y")).message == "gathered"
        registry.HANDOFFS.clear()
        registry.register_handoff("wait", "rest", lambda w, c, it: 1 / 0)
        assert apply_intention(w, top, Intention("wait", target="x")).message == "waited"
        assert calls == ["rest", "gather", "wait"]
    assert registry.HANDOFFS == before


def test_landmark_sources_join_the_landmarks(pair):
    w, top, low = pair
    sim = Simulation(w)
    with registry.sandbox():
        registry.register_landmarks(lambda world: [{"name": "the probe hall", "x": 12, "y": 30, "kind": "hall"}])
        registry.register_landmarks(lambda world: 1 / 0)
        sim._landmarks()
        assert "the probe hall" in [lm["name"] for lm in w.landmarks]
    sim._landmarks()
    assert "the probe hall" not in [lm["name"] for lm in w.landmarks]


def test_surface_terminals_only_are_named_by_direction(pair):
    w, top, low = pair
    w.add_object("terminal", 20, 5)  # surface, north-east of the meadow
    w.add_object("terminal", 20, 30)  # in the deep
    w.tiles[40][5] = "W"  # deep water doesn't pull the lake
    Simulation(w)._landmarks()
    names = [lm["name"] for lm in w.landmarks]
    assert "the northeast terminal" in names and sum("terminal" in n for n in names) == 1
    assert "the lake" not in names
    w.tiles[3][3] = "W"
    Simulation(w)._landmarks()
    lake = next(lm for lm in w.landmarks if lm["name"] == "the lake")
    assert (lake["x"], lake["y"]) == (3, 3)


def test_collapsed_in_the_deep_wakes_in_the_meadow(pair):
    w, top, low = pair
    sim = Simulation(w)
    low.health = 0
    low.satiety = 0
    sim._collapse(low, w.tick)
    w.tick = low.collapsed_until
    sim.tick()
    assert not low.collapsed and w.region_at(low.x, low.y).name == "surface"


def test_water_in_sight_is_in_the_same_region(pair):
    from swarmworld.world.packs.food import _water_in_sight
    w, top, low = pair
    w.tiles[26][13] = "w"  # deep water beside Low, 4 rows below Top
    assert _water_in_sight(w, top) is None and _water_in_sight(w, low)[:2] == (13, 26)
    w.tiles[20][12] = "W"
    assert _water_in_sight(w, low)[:2] == (13, 26) and _water_in_sight(w, top)[:2] == (12, 20)


def test_news_of_a_rack_or_spoiled_food_stays_in_its_region(pair):
    from swarmworld.world.packs.food import DRY_TICKS, _dry, _went_bad
    w, top, low = pair
    told = []
    sim = Simulation(w, memory_sink=lambda c, text, imp: told.append((c.name, text)))
    rack = w.add_object("drying_rack", 12, 21, items={"meat": 1}, drying={"meat": DRY_TICKS})
    _dry(sim, w.tick)
    assert [n for n, t in told if "drying rack" in t] == ["Top"]
    told.clear()
    _went_bad(sim, 12, 21, "meat", 1, "on the rack")
    assert [n for n, t in told] == ["Top"]


def test_a_fire_in_another_region_is_not_sensed(pair):
    from swarmworld.world.packs.weather import _burning_line
    w, top, low = pair
    tree = w.add_object("tree", 12, 24, burning=w.tick + 100)
    w.ext["weather"] = {"burning": [tree.id]}
    assert _burning_line(w, top) is None and "on fire" in _burning_line(w, low)


def test_animals_do_not_pair_across_regions(pair, monkeypatch):
    from swarmworld.world import simulation
    w, top, low = pair
    monkeypatch.setattr(simulation, "ANIMAL_BREED_CHANCE", 2.0)
    a = w.add_object("sheep", 12, 23, tamed_by="Top", hunger=10)
    b = w.add_object("sheep", 12, 24, tamed_by="Top", hunger=10)
    sim = Simulation(w)
    sim._breed(a, [a, b], {"sheep": 2}, 1)
    assert sum(o.kind == "sheep" for o in w.objects.values()) == 2
    c = w.add_object("sheep", 13, 22, tamed_by="Top", hunger=10)
    sim._breed(a, [a, b, c], {"sheep": 3}, 1)
    assert sum(o.kind == "sheep" for o in w.objects.values()) == 4


def test_places_name_the_level_they_lie_on(pair):
    from swarmworld.server.state import ServerState
    w, top, low = pair
    st = ServerState.__new__(ServerState)
    st.world = w
    assert st._where_is(top, 12, 26) == "below, in the deep" and st._where_is(low, 12, 22) == "above, on the surface"
    assert st._where_is(top, 12, 22) == "right here" and st._where_is(top, 12, 18) == "about 4 steps north of you"
    assert st._where_is(top, 12, 24 + 100) == "in another place"
