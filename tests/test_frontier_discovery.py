"""The frontier's words: the edge line, exploring to the edge, first entry and names, the explorers' pull."""
import logging

from swarmworld.mind.memory import Memory
from swarmworld.mind.prompts import build_act_messages
from swarmworld.server import state as server_state
from swarmworld.server.almanac import world_now
from swarmworld.world.actions import Intention, apply_intention, step_activity
from swarmworld.world.model import DAY_TICKS, Creature, FrontierSettings
from swarmworld.world.packs import frontier, underground
from swarmworld.world.packs.frontier import (ANOTHER_DAY, EDGE_LINE, FOUND, LAND_EVENT, PULL, grow, land_at,
                                             land_rect, why_not_grow)
from swarmworld.world.perception import perceive
from swarmworld.world.simulation import Simulation
from swarmworld.world.terrain import generate_world
from tests.test_frontier_growth import _free_tile, world48


def person(w, name, x, y, **kw):
    c = Creature(f"c{len(w.creatures) + 1}", name, x, y, asleep=False, **kw)
    w.creatures[c.id] = c
    return c


def at(w, name, x, y, **kw):
    ok = w.walkable(x, y) and (x, y) not in w.grid and not w.occupied(x, y)
    return person(w, name, *((x, y) if ok else _free_tile(w, (x, y))), **kw)


def run_walk(w, c, limit=200):
    for _ in range(limit):
        res = step_activity(w, c)
        if res is not None:
            return res
    raise AssertionError("the walk never ended")


def test_the_edge_is_sensed_only_within_sight():
    w = world48()
    c = at(w, "Ada", 43, 20)
    assert w.width - 1 - c.x <= 6
    line = EDGE_LINE.format(side="east")
    assert line in perceive(w, c)
    c.wake_reason = None
    assert line not in perceive(w, c)
    c.wake_reason = "woke"
    assert line in perceive(w, c)
    far = at(w, "Bo", 30, 20)
    assert "fades into unknown country" not in perceive(w, far)
    off = world48()
    off.frontier_settings = FrontierSettings(on=False)
    assert "fades into unknown country" not in perceive(off, at(off, "Ada", 43, 20))
    w.tick = w.tick - w.tick % DAY_TICKS + 21 * DAY_TICKS // 24 + 60  # deep night
    assert w.clock()["phase"] == "night"
    night = at(w, "Cy", 43, 24)
    assert "fades into unknown country" not in perceive(w, night)


def test_explore_toward_a_near_edge_walks_there_and_lays_land():
    w = world48(pace=1200)
    c = at(w, "Ada", 28, 20)
    res = apply_intention(w, c, Intention("explore", target="east"))
    assert res.ok and res.message == "You head off east, toward the edge of the known land."
    done = run_walk(w, c)
    assert done.message == ("You reach the edge of the known land to the east. "
                            "New country opens before you to the east; you walk on into it.")
    assert w.width == 80 and c.x >= 48


def test_another_day():
    w = world48(pace=1200)
    ada, bo = at(w, "Ada", 46, 20), at(w, "Bo", 1, 30)
    assert apply_intention(w, ada, Intention("explore", target="east")).message.startswith("New country opens")
    w.tick += 10
    res = apply_intention(w, bo, Intention("explore", target="west"))
    assert not res.ok and res.message == ANOTHER_DAY and w.width == 80


def test_two_arrivals_lay_one_strip():
    w = world48(pace=1200)
    ada, bo = at(w, "Ada", 46, 20), at(w, "Bo", 1, 30)
    r1 = apply_intention(w, ada, Intention("explore", target="east"))
    r2 = apply_intention(w, bo, Intention("explore", target="west"))
    assert r1.ok and not r2.ok and r2.message == ANOTHER_DAY
    assert w.width == 80 and w.ext["frontier"]["strips"] == {"east": 1, "west": 0}


def test_a_walker_keeps_its_way_through_a_west_growth():
    w = world48(pace=1200)
    bush = next(o for o in w.objects.values() if o.kind == "bush" and 15 < o.x < 30)
    bo = at(w, "Bo", bush.x + 5, bush.y)
    ada = at(w, "Ada", 1, 30)
    res = apply_intention(w, bo, Intention("walk_to", target="bush"))
    assert res.ok
    for _ in range(3):
        step_activity(w, bo)
    assert apply_intention(w, ada, Intention("explore", target="west")).message.startswith("New country")
    assert bush.x >= 32
    end = run_walk(w, bo)
    assert end.ok and max(abs(bo.x - bush.x), abs(bo.y - bush.y)) <= 1


def test_the_first_to_step_in_finds_and_names_the_land():
    w = world48()
    grow(w, "east", theme="stony_hills")
    memories = []
    sim = Simulation(w, memory_sink=lambda c, text, imp: memories.append((c.name, text)))
    ada, bo = person(w, "Ada", 1, 1), person(w, "Bo", 1, 2)
    x0, y0, x1, y1 = land_rect(w, "1,0")
    ada.x, ada.y = x0 + 3, y0 + 3
    frontier._discover(sim, 3)
    assert memories == [("Ada", "You found new country to the east: stony hills. From now on it is the Eastern Hills.")]
    assert [e.kind for e in w.events].count("land") == 1
    assert w.events[-1].text == LAND_EVENT.format(who="Ada", side="east", label="stony hills", name="the Eastern Hills")
    sim._landmarks()
    hills = next(lm for lm in w.landmarks if lm["name"] == "the Eastern Hills")
    assert hills["kind"] == "land" and land_at(w, hills["x"], hills["y"]) == "1,0"
    assert w.ext["frontier"]["lands"]["1,0"]["found_by"] == "Ada"
    bo.x, bo.y = x0 + 4, y0 + 4
    frontier._discover(sim, 6)
    assert len(memories) == 1
    grow(w, "east", theme="stony_hills")
    x0, y0, _, _ = land_rect(w, "2,0")
    ada.x, ada.y = x0 + 3, y0 + 3
    frontier._discover(sim, 9)
    assert w.ext["frontier"]["lands"]["2,0"]["name"] == "Ada's Hills"
    grow(w, "east", theme="stony_hills")
    x0, y0, _, _ = land_rect(w, "3,0")
    ada.x, ada.y = x0 + 3, y0 + 3
    frontier._discover(sim, 12)
    assert w.ext["frontier"]["lands"]["3,0"]["name"] == "Ada's second Hills"


def test_a_ruin_terminal_is_named_by_its_land(monkeypatch):
    w = world48()
    grow(w, "east", theme="ruins")
    x0, y0, _, _ = land_rect(w, "1,0")
    term = w.add_object("terminal", x0 + 5, y0 + 5, code="", screen=[], memory={}, ruin=True)
    sim = Simulation(w)
    sim._landmarks()
    assert not any(lm["x"] == term.x and lm["y"] == term.y for lm in w.landmarks)
    w.ext["frontier"]["lands"]["1,0"].update(name="the Eastern Ruins", found_by="Ada")
    sim._landmarks()
    assert any(lm["name"] == "the old terminal in the Eastern Ruins" for lm in w.landmarks)


def test_land_events_reach_the_chronicle_and_the_census():
    w = world48()
    grow(w, "east", theme="marsh")
    sim = Simulation(w)
    ada = person(w, "Ada", *land_rect(w, "1,0")[:2])
    ada.x += 2
    ada.y += 2
    frontier._discover(sim, 3)
    lines = server_state.ServerState.chronicle_digest(type("S", (), {"world": w})(), -1)
    assert LAND_EVENT.format(who="Ada", side="east", label="a marsh", name="the Eastern Marsh") in lines
    st = type("S", (), {"world": w, "metrics": type("M", (), {"verbs_since": {}})()})()
    assert world_now(st, [])["lands"] == {"strips": {"east": 1, "west": 0}, "count": 2,
                                          "found": [{"name": "the Eastern Marsh", "theme": "marsh", "by": "Ada"}]}


def test_explorers_feel_the_pull_once_a_day():
    w = world48(pace=1200)
    memories = []
    sim = Simulation(w, memory_sink=lambda c, text, imp: memories.append(text))
    ada = at(w, "Ada", *w.center, persona={"drive": "explorer"})
    cur = at(w, "Cy", w.center[0], w.center[1] + 3, persona={"drive": "curious"})
    w.tick = 1000
    frontier._pull(sim, 1000)
    assert memories == ["The unknown country to the east calls to you, some 25 steps away: explore east to go and see."]
    frontier._pull(sim, 1000 + DAY_TICKS - 20)
    assert len(memories) == 1
    frontier._pull(sim, 1000 + DAY_TICKS)
    assert len(memories) == 2
    ada.activity = {"type": "walk", "path": [], "label": "x", "result": "x"}
    frontier._pull(sim, 1000 + 3 * DAY_TICKS)
    assert len(memories) == 2 and cur.ext == {}
    ada.activity = None
    w.tick = 1000 + 3 * DAY_TICKS
    grow(w, "east")  # now the pace holds every side
    frontier._pull(sim, w.tick)
    assert len(memories) == 2


def test_at_the_cap_the_edge_is_the_end():
    w = world48(cap=80)
    grow(w, "east")
    assert w.width == 80 and why_not_grow(w, "east") == "cap"
    c = at(w, "Ada", w.width - 1, 20)
    assert c.x == w.width - 1
    assert "fades into unknown country" not in perceive(w, c)
    res = apply_intention(w, c, Intention("explore", target="east"))
    assert res.message.startswith("The land ends to the east, so you turn")
    sim = Simulation(w)
    memories = []
    sim.memory_sink = lambda c, text, imp: memories.append(text)
    c.activity = None
    c.persona = {"drive": "explorer"}
    frontier._pull(sim, 5000)
    assert not any("east" in m for m in memories)
    assert grow(w, "east", ignore_pace=True) == []


def test_a_failed_growth_cools_down(monkeypatch, caplog):
    w = world48(pace=1200)
    ada, bo = at(w, "Ada", 46, 20), at(w, "Bo", 47, 30)

    def boom(*a, **k):
        raise RuntimeError("no land today")
    monkeypatch.setattr(underground, "grow_under", boom)
    with caplog.at_level(logging.ERROR):
        res = apply_intention(w, ada, Intention("explore", target="east"))
    assert not res.ok and res.message == ANOTHER_DAY and w.width == 48
    assert w.ext["frontier"]["failed"] == w.tick
    calls = []
    monkeypatch.setattr(frontier, "_lay", lambda *a: calls.append(a))
    res = apply_intention(w, bo, Intention("explore", target="east"))
    assert not res.ok and res.message == ANOTHER_DAY and calls == []
    assert why_not_grow(w, "east") == "pace"
    w.tick += 1200
    assert why_not_grow(w, "east") is None


def test_a_failed_growth_holds_at_least_300_ticks_at_pace_zero(monkeypatch, caplog):
    w = world48(pace=0)
    ada = at(w, "Ada", 47, 20)
    monkeypatch.setattr(underground, "grow_under", lambda *a, **k: 1 / 0)
    with caplog.at_level(logging.ERROR):
        assert grow(w, "east", by=ada) == []
    assert why_not_grow(w, "east") == "pace"
    w.tick += 299
    assert why_not_grow(w, "east") == "pace"
    w.tick += 1
    assert why_not_grow(w, "east") is None


def test_far_from_an_edge_nothing_changes():
    a, b = generate_world(7), generate_world(7)
    b.frontier_settings = FrontierSettings(on=True, pace=0)
    persona = {"traits": ["curious", "patient"], "drive": "curious", "initiative": "proactive"}
    tams = [person(w, "Tam", *w.center, persona=dict(persona)) for w in (a, b)]

    def same():
        views = [perceive(w, c) for w, c in zip((a, b), tams)]
        assert views[0] == views[1]
        assert build_act_messages(a, tams[0], Memory(), views[0]) == build_act_messages(b, tams[1], Memory(), views[1])
        assert a.rng.getstate() == b.rng.getstate()

    same()
    sims = [Simulation(a), Simulation(b)]
    for _ in range(300):
        for sim in sims:
            sim.tick()
    for w, c in zip((a, b), tams):  # the 300 ticks may have moved Tam: put back
        c.x, c.y, c.activity = *w.center, None
    same()
    grow(b, "east")
    grow(b, "west")
    for w, c in zip((a, b), tams):
        c.x, c.y = w.center
    same()
    for d in ("north", "east"):
        results = []
        for w, c in zip((a, b), tams):
            c.x, c.y, c.activity = *w.center, None
            res = apply_intention(w, c, Intention("explore", target=d))
            results.append((res.ok, res.message, res.instant))
        assert results[0] == results[1]


def test_a_near_walk_longer_than_twice_the_edge_reach_falls_back_to_core_explore(monkeypatch):
    w = world48()
    ada = at(w, "Ada", 40, 20)
    monkeypatch.setattr(frontier, "bfs_path", lambda *a, **k: [(41, 20)] * (2 * frontier.EDGE_NEAR + 1))
    res = apply_intention(w, ada, Intention("explore", target="east"))
    assert not res.message.startswith("You head off east, toward the edge")
    monkeypatch.setattr(frontier, "bfs_path", lambda *a, **k: [(41, 20)] * (2 * frontier.EDGE_NEAR))
    ada.activity = None
    res = apply_intention(w, ada, Intention("explore", target="east"))
    assert res.message.startswith("You head off east, toward the edge")


def test_an_explorer_far_from_the_edge_heads_all_the_way_there():
    # a day and a half of the fresh world: the explorers stayed 60 steps from either edge, where explore was the
    # core 8-step wander, and no land grew; an explorer's explore toward an edge now goes there from anywhere
    w = generate_world(7)
    w.frontier_settings = FrontierSettings(on=True, pace=0)
    holt = at(w, "Holt", *w.center, persona={"drive": "explorer"})
    assert frontier.edge_distance(w, holt, "east") > frontier.EDGE_NEAR
    res = apply_intention(w, holt, Intention("explore", target="east"))
    assert res.ok and res.message == "You head off east, toward the edge of the known land."
    done = run_walk(w, holt, limit=600)
    assert "New country opens before you to the east" in done.message and w.width > 128


def test_others_far_from_the_edge_still_wander():
    w = generate_world(7)
    w.frontier_settings = FrontierSettings(on=True, pace=0)
    tam = at(w, "Tam", *w.center, persona={"drive": "curious"})
    res = apply_intention(w, tam, Intention("explore", target="east"))
    assert not res.message.startswith("You head off east, toward the edge")
