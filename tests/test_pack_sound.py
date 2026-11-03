"""Pack sound: creatures hear the world's noises as text, with cooldowns so it is never spammy."""
from swarmworld.server.persistence import restore
from swarmworld.server.state import ServerState
from swarmworld.world import actions, registry
from swarmworld.world.packs import sound
from swarmworld.world.actions import Intention, apply_intention, step_activity
from swarmworld.world.model import DAY_TICKS, START_TICK, Creature, World
from swarmworld.world.catalog import Catalog
from swarmworld.world.simulation import Simulation

NIGHT = DAY_TICKS * 2 + int(DAY_TICKS * 0.8)
DAY = DAY_TICKS * 2 + int(DAY_TICKS * 0.3)


def grass_world(size=40):
    w = World(size, size, [["g"] * size for _ in range(size)], Catalog.load())
    w.tick = START_TICK
    return w


def creature(w, name, x, y):
    c = Creature(f"c{len(w.creatures) + 1}", name, x, y, asleep=False, wake_reason=None, last_think_tick=w.tick)
    c.known_recipes = {r.output for r in w.catalog.recipes if r.known_at_start}
    w.creatures[c.id] = c
    return c


def act(w, c, **kw):
    res = apply_intention(w, c, Intention(**kw))
    while c.activity:
        step_activity(w, c)
    return res


def sounds(w, kind=None):
    return [e for e in w.events if e.kind == "sound" and (kind is None or e.data.get("sound") == kind)]


def test_sound_pack_is_installed():
    [system] = [s for s in registry.SYSTEMS if s.name == "sound"]
    assert system.fn is sound.sound_system and system.every == 1  # every tick: a sound is heard the tick after


def test_chopping_is_heard_nearby_not_far():
    w = grass_world()
    w.tick = DAY
    sim = Simulation(w)
    w.add_object("tree", 10, 10, wood=6)
    chopper = creature(w, "Tam", 10, 11)
    near = creature(w, "Mara", 10, 16)
    far = creature(w, "Pell", 10, 30)
    assert act(w, chopper, action="gather", target="tree").ok
    sim.tick()  # the system turns the gather event into a sound
    assert sounds(w, "chop"), "no chop sound was made"
    sim.tick()  # ...heard on the next tick
    heard = sim.take_heard(near)
    assert any(h.startswith("You hear") and ("chop" in h or "branch" in h) for h in heard), heard
    assert sim.take_heard(far) == [] and sim.take_heard(chopper) == []


def test_knocking_stone_and_fishing_splash(monkeypatch):
    w = grass_world()
    w.tick = DAY
    sim = Simulation(w)
    w.add_object("rock", 10, 10)
    c = creature(w, "Tam", 10, 11)
    act(w, c, action="gather", target="rock")
    sim.tick()
    assert sounds(w, "knock")
    for x in range(40):
        w.tiles[20][x] = "w"
    odo = creature(w, "Odo", 20, 19)
    odo.inventory["fishing_rod"] = 1
    monkeypatch.setattr(actions, "catch_fish", lambda world, c: "fish")
    assert act(w, odo, action="gather", target="fish").ok and odo.inventory["fish"] == 1
    sim.tick()
    [splash] = sounds(w, "splash")
    assert splash.data["source"] == odo.id


def test_crickets_only_at_night():
    w = grass_world()
    w.tick = DAY
    sim = Simulation(w)
    creature(w, "Tam", 10, 10)
    for _ in range(300):
        if w.clock()["phase"] != "day":
            break
        sim.tick()
    assert not sounds(w, "crickets")
    w.tick = NIGHT
    for _ in range(150):
        sim.tick()
        w.creatures["c1"].asleep = False
    assert 1 <= len(sounds(w, "crickets")) <= 150 // sound.CRICKET_COOLDOWN + 1  # sparse: once per cooldown


def test_sound_cooldowns():
    w = grass_world()
    w.tick = DAY
    sim = Simulation(w)
    w.add_object("tree", 10, 10, wood=60)
    chopper = creature(w, "Tam", 10, 11)
    for _ in range(5):  # five gathers in five ticks
        w.emit("gather", chopper.id, 10, 11, "Tam gathered 1 stick.", source_kind="tree")
        sim.tick()
    assert len(sounds(w, "chop")) == 1
    w.tick += 60
    w.emit("gather", chopper.id, 10, 11, "Tam gathered 1 stick.", source_kind="tree")
    sim.tick()
    assert len(sounds(w, "chop")) == 2


def test_fire_river_crowd_and_animals_are_sparse():
    w = grass_world()
    w.tick = DAY
    for x in range(0, 40):
        w.tiles[20][x] = "w"
    sim = Simulation(w)
    fire = w.add_object("campfire", 5, 5, lit=True, lit_until=w.tick + 10_000)
    for i, (x, y) in enumerate([(5, 6), (6, 6), (7, 6), (6, 7)]):
        creature(w, f"C{i}", x, y)
    creature(w, "River", 12, 19)
    for _ in range(400):
        sim.tick()
    for kind, cooldown in (("fire", sound.FIRE_COOLDOWN), ("river", sound.RIVER_COOLDOWN),
                           ("crowd", sound.CROWD_COOLDOWN)):  # about once per cooldown while someone is near
        n = len(sounds(w, kind))
        assert 400 // cooldown - 1 <= n <= 400 // cooldown + 1, (kind, n)
    assert all(e.data["source"] == fire.id for e in sounds(w, "fire"))


def test_unlit_fire_is_silent():
    w = grass_world()
    w.tick = DAY
    sim = Simulation(w)
    w.add_object("campfire", 5, 5, lit=False)
    creature(w, "Tam", 5, 6)
    for _ in range(100):
        sim.tick()
    assert not sounds(w, "fire")


def test_sound_old_save_loads(prepack_save):
    st = ServerState(seed=1)
    restore(st, prepack_save)
    for c in st.world.creatures.values():
        c.asleep = False
    for _ in range(200):
        st.tick_message(st.sim.tick())


def test_animals_call_now_and_then():
    w = grass_world()
    w.tick = DAY
    sim = Simulation(w)
    kind = sorted(registry.ANIMALS)[0]
    w.add_object(kind, 8, 8)
    creature(w, "Tam", 8, 10)
    for _ in range(600):
        sim.tick()
    calls = sounds(w, f"animal:{kind}")
    assert 1 <= len(calls) <= 600 // sound.ANIMAL_COOLDOWN + 1


def test_gathering_sounds_like_what_it_is_gathered_from():
    w = grass_world()
    w.tick = DAY
    sim = Simulation(w)
    tam = creature(w, "Tam", 10, 10)
    assert act(w, tam, action="gather", target="grass").ok
    sim.tick()
    assert [e.text for e in sounds(w, "rustle")] == ["grass swishing"]
    mara = creature(w, "Mara", 20, 20)  # foraging beside a tree and a boulder is neither chopping nor knocking
    w.add_object("tree", 21, 20, wood=6)
    w.add_object("rock", 20, 21)
    w.add_object("mushroom_patch", 19, 20)
    assert act(w, mara, action="gather", target="mushroom patch").ok and mara.inventory["mushroom"]
    w.emit("gather", mara.id, 20, 20, "Mara hunted a deer and took 2 raw meat.", hunted="deer")  # as food.py does
    sim.tick()
    assert not sounds(w, "chop") and not sounds(w, "knock")
    assert [e.data.get("source_kind") for e in w.events if e.kind == "gather" and e.actor == mara.id] == \
        ["mushroom_patch", None]


def test_a_new_site_is_heard_as_stakes_not_a_thud():
    w = grass_world()
    w.tick = DAY
    sim = Simulation(w)
    mira, tam = creature(w, "Mira", 10, 10), creature(w, "Tam", 14, 10)
    mira.inventory["stick"] = 2
    assert act(w, mira, action="build", target="tent").ok
    sim.tick()
    sim.tick()
    assert [e.text for e in sounds(w, "build")] == ["stakes being knocked into the ground"]
    heard = sim.take_heard(tam)
    assert any("stakes" in h for h in heard) and not any("thud" in h for h in heard), heard


def test_a_crowd_does_not_hear_itself_and_a_fire_is_its_own_source():
    w = grass_world()
    w.tick = DAY
    sim = Simulation(w)
    fire = w.add_object("campfire", 5, 5, lit=True, lit_until=w.tick + 10_000)
    group = [creature(w, f"C{i}", x, y) for i, (x, y) in enumerate([(5, 6), (6, 6), (7, 6)])]
    outsider = creature(w, "Far", 13, 6)
    for _ in range(12):
        sim.tick()
    assert sounds(w, "crowd") and sounds(w, "fire")
    assert all(e.data["source"] == fire.id for e in sounds(w, "fire"))
    for c in group:
        assert not any("crowd" in h for h in sim.take_heard(c)), c.name
    assert any("a crowd talking" in h for h in sim.take_heard(outsider))


def test_crickets_wait_for_grass_without_spending_their_turn():
    w = World(40, 40, [["d"] * 40 for _ in range(40)], Catalog.load())
    w.tick = NIGHT
    sim = Simulation(w)
    tam = creature(w, "Tam", 10, 10)
    for _ in range(10):
        sim.tick()
        tam.asleep = False
    assert not sounds(w, "crickets") and "crickets" not in w.ext.get("sound", {}).get("cd", {})
    for row in w.tiles:
        row[:] = ["g"] * 40
    for _ in range(10):
        sim.tick()
        tam.asleep = False
    assert sounds(w, "crickets")
