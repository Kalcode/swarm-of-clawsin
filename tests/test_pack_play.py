from swarmworld.server.persistence import restore
from swarmworld.server.state import ServerState
from swarmworld.world import registry
from swarmworld.world.actions import Intention, apply_intention
from swarmworld.world.catalog import Catalog
from swarmworld.world.model import START_TICK, Creature, World
from swarmworld.world.packs import play
from swarmworld.world.simulation import Simulation


def make(n=2, fire=False):
    w = World(40, 40, [["g"] * 40 for _ in range(40)], Catalog.load())
    w.tick = START_TICK + 100
    for i in range(n):
        c = Creature(f"c{i + 1}", ["Tam", "Bo", "Ky"][i], 10 + i, 10, asleep=False)
        w.creatures[c.id] = c
    if fire:
        w.add_object("campfire", 10, 11, lit=True, lit_until=w.tick + 5000)
    return w, Simulation(w)


def do(w, c, action, **kw):
    return apply_intention(w, c, Intention(action, **kw))


def night(w):
    while w.clock()["phase"] != "night":
        w.tick += 1


def test_joy_falls_and_play_raises_it():
    w, sim = make()
    tam, bo = w.creatures["c1"], w.creatures["c2"]
    assert play.joy(tam) == 70
    for _ in range(200):
        sim.tick()
    assert play.joy(tam) < 70 and tam.health >= 99
    before, before_bo = play.joy(tam), play.joy(bo)
    res = do(w, tam, "play", target="Bo")
    assert res.ok and play.joy(tam) > before and play.joy(bo) > before_bo
    assert registry.owner("technique", "play")


def test_play_needs_company():
    w, sim = make(1)
    assert not do(w, w.creatures["c1"], "play").ok


def test_low_joy_shows_one_line_once():
    w, sim = make()
    tam = w.creatures["c1"]
    assert not any("restless" in l for l in registry.extra_perception(w, tam))
    tam.ext["play"] = {"joy": 10}
    lines = registry.extra_perception(w, tam)
    assert any("restless" in l for l in lines)
    assert not any("restless" in l for l in registry.extra_perception(w, tam))


def test_dancing_at_fire_needs_a_fire():
    w, sim = make(fire=False)
    tam = w.creatures["c1"]
    assert not do(w, tam, "dance").ok
    w2, _ = make(fire=True)
    tam2 = w2.creatures["c1"]
    before = play.joy(tam2)
    res = do(w2, tam2, "dance")
    assert res.ok and play.joy(tam2) > before
    assert any(e.kind == "sound" and e.data.get("sound") == "dance" for e in w2.events)


def test_playing_together_bonds():
    st = ServerState(seed=1)
    w, _ = make()
    st.world = w
    a, b = w.creatures["c1"], w.creatures["c2"]
    res = do(w, a, "play", target=b.name)
    assert res.ok
    for ev in w.events:
        st._note_relation(ev)
    edge = next(e for e in st.society()["edges"] if {e["a"], e["b"]} == {a.id, b.id})
    assert edge["play"] >= 1 and edge["weight"] >= 2


def test_playing_again_soon_adds_no_new_tie():
    st = ServerState(seed=1)
    w, _ = make()
    st.world = w
    a, b = w.creatures["c1"], w.creatures["c2"]

    def ties():
        for ev in w.events:
            st._note_relation(ev)
        w.events.clear()
        return next(e for e in st.society()["edges"] if {e["a"], e["b"]} == {a.id, b.id})["play"]

    for _ in range(4):
        assert do(w, a, "play", target=b.name).ok
        assert do(w, b, "play", target=a.name).ok
    assert ties() == 1 and play.joy(b) > 70  # their spirits still lift every time
    w.tick += play.TIE_COOLDOWN
    assert do(w, a, "play", target=b.name).ok
    assert ties() == 2


def test_collapsed_creatures_do_not_join_in():
    w, _ = make(3)
    a, b, c = w.creatures["c1"], w.creatures["c2"], w.creatures["c3"]
    c.collapsed_until = w.tick + 50
    assert play._awake_near(w, a, 3) == [b]


def test_music_with_an_instrument():
    w, sim = make()
    tam, bo = w.creatures["c1"], w.creatures["c2"]
    assert not do(w, tam, "make_music").ok
    r = w.catalog.recipe_for("flute")
    assert r and "stone_knife" in r.tools and w.catalog.recipe_for("drum")
    tam.inventory["flute"] = 1
    before = play.joy(bo)
    res = do(w, tam, "make_music")
    assert res.ok and play.joy(bo) > before
    assert any(e.kind == "sound" and e.data.get("sound") == "music" for e in w.events)
    assert any(t.name == "make_music" and t.trigger(w, tam) for t in registry.TECHNIQUES)


def test_stories_at_night_by_a_fire():
    w, sim = make(fire=True)
    night(w)
    tam, bo = w.creatures["c1"], w.creatures["c2"]
    before = play.joy(bo)
    do(w, tam, "say", text="Once there was a river that sang.")
    sim.tick()
    assert play.joy(bo) > before
    assert any("tale" in l for l in registry.extra_perception(w, bo))


def test_stories_need_a_fire_and_dark():
    w, sim = make(fire=False)
    night(w)
    bo = w.creatures["c2"]
    do(w, w.creatures["c1"], "say", text="Once there was a river.")
    sim.tick()
    assert play.joy(bo) == 70
    w2, sim2 = make(fire=True)  # daytime
    do(w2, w2.creatures["c1"], "say", text="Once there was a river.")
    sim2.tick()
    assert play.joy(w2.creatures["c2"]) == 70


def test_play_old_save_loads(prepack_save):
    st = ServerState(seed=1)
    restore(st, prepack_save)
    creatures = list(st.world.creatures.values())
    assert creatures and all("joy" not in (c.ext.get("play") or {}) for c in creatures)  # nothing saved ...
    assert all(play.joy(c) == play.JOY_START for c in creatures)  # ... so everyone starts at the default
    for c in creatures:
        c.asleep = False
    for _ in range(200):
        st.tick_message(st.sim.tick())
    fallen = play.JOY_START - 200 // play.JOY_EVERY  # a point every JOY_EVERY ticks, and nothing to cheer anyone
    assert all(play.joy(c) == fallen for c in creatures if not c.collapsed), [play.joy(c) for c in creatures]
