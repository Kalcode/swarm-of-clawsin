from swarmworld.server.persistence import restore, save
from swarmworld.server.state import ServerState
from swarmworld.world.model import DAY_TICKS
from swarmworld.world.packs import weather as wx
from swarmworld.world.perception import DAY_SIGHT, sight_range
from swarmworld.world import registry


def _world(kind="clear", ticks=10**6):
    st = ServerState(seed=3)
    c = st.new_creature("mock")
    c.asleep = False
    w = st.world
    w.tick = 100  # midday-ish; tests that need a phase set it themselves
    wx.set_weather(w, kind, w.tick + ticks)
    return st, w, c


def _run(st, n):
    for _ in range(n):
        st.sim.tick()


def test_fog_shrinks_sight():
    st, w, c = _world()
    w.tick = int(DAY_TICKS * 0.3)
    assert w.clock()["phase"] == "day"
    assert sight_range(w, c) == DAY_SIGHT
    wx.set_weather(w, "fog", w.tick + 500)
    assert sight_range(w, c) == wx.FOG_SIGHT < DAY_SIGHT
    wx.set_weather(w, "clear", 0)
    assert sight_range(w, c) == DAY_SIGHT


def test_storm_thunders_loudly():
    st, w, c = _world("storm")
    w.rng.seed(1)
    n0 = len(w.events)
    _run(st, 400)
    thunder = [e for e in w.events[n0:] if e.kind == "sound" and e.data.get("sound") == "thunder"]
    assert thunder and all(e.data["loud"] for e in thunder)
    assert all(e.data["radius"] >= wx.THUNDER_RADIUS for e in thunder)  # wind carries it farther


def test_lightning_can_burn_a_tree(monkeypatch):
    st, w, c = _world("storm")
    monkeypatch.setattr(wx, "THUNDER_CHANCE", 1.0)
    monkeypatch.setattr(wx, "STRIKE_CHANCE", 1.0)
    tree = w.add_object("tree", c.x + 1, c.y)
    for o in list(w.objects.values()):
        if o.kind in ("tree", "pine") and o is not tree:
            w.remove_object(o.id)
    w.tick = 110
    wx._step(st.sim, 110)
    assert tree.data["burning"] and any(e.kind == "lightning" for e in w.events)
    assert "on fire" in " ".join(registry.extra_perception(w, c))
    wx._burn(w, tree.data["burning"])
    assert tree.kind == "stump" and "burning" not in tree.data


def test_wind_burns_fires_faster():
    def fire_left(kind):
        st, w, c = _world(kind)
        fire = w.add_object("campfire", c.x + 1, c.y)
        fire.data.update(lit=True, lit_until=w.tick + 1000)
        until = fire.data["lit_until"]
        _run(st, 100)
        return fire.data["lit_until"] - until

    assert fire_left("wind") <= fire_left("clear") - 90  # a hundred ticks of wind: roughly a hundred more burned


def test_heat_makes_creatures_hungrier():
    def hunger(kind):
        st, w, c = _world(kind)
        c.satiety = 90
        c.energy = 100
        _run(st, 96)
        return 90 - c.satiety

    assert hunger("heat") == hunger("clear") + 2  # one extra point at ticks 144 and 192


def test_weather_line_only_when_not_clear():
    st, w, c = _world()
    assert wx._weather_line(w, c) is None
    for kind in ("drizzle", "fog", "wind", "storm", "heat"):
        wx.set_weather(w, kind, w.tick + 100)
        line = wx._weather_line(w, c)
        assert line and len(line) < 100
        assert line in registry.extra_perception(w, c)


def test_weather_rain_cycle_still_works_and_exposure():
    st, w, c = _world("rain")
    w.weather_until = 10
    assert st.sim.exposure(c) == "rain"
    n0 = len(w.events)
    w.tick = 49
    st.sim.tick()  # tick 50
    assert w.weather == "clear"
    assert any(e.kind == "weather" and "rain stops" in e.text for e in w.events[n0:])
    assert st.sim.exposure(c) is None


def test_weather_changes_over_time():
    st, w, c = _world()
    seen = set()
    for _ in range(12000):  # a 5% roll every 50 ticks: 3000 ticks left this to seed luck
        st.sim.tick()
        seen.add(w.weather)
        if len(seen) >= 3:
            break
    assert len(seen) >= 3


def test_weather_saved(tmp_path):
    st, w, c = _world("fog", 700)
    path = tmp_path / "world.json"
    save(st, path)
    st2 = ServerState(seed=99)
    restore(st2, path)
    assert st2.world.weather == "fog" and st2.world.weather_until == w.weather_until
    assert st2.world.ext["weather"]["sight"] == wx.FOG_SIGHT
    c2 = st2.world.creatures[c.id]
    assert sight_range(st2.world, c2) <= wx.FOG_SIGHT


def test_weather_old_save_loads(prepack_save):
    st = ServerState(seed=1)
    restore(st, prepack_save)
    for c in st.world.creatures.values():
        c.asleep = False
    for _ in range(200):
        st.tick_message(st.sim.tick())
    assert st.world.weather in wx.KINDS
