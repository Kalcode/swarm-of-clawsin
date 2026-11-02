from collections import Counter

from swarmworld.world.events import hearers
from swarmworld.world.model import Creature
from swarmworld.world.terrain import generate_world


def _summary(w):
    return ["".join(r) for r in w.tiles], sorted((o.kind, o.x, o.y) for o in w.objects.values())


def test_deterministic():
    assert _summary(generate_world(3)) == _summary(generate_world(3))
    assert _summary(generate_world(3)) != _summary(generate_world(4))


def test_resources_present():
    for seed in (1, 7, 42):
        w = generate_world(seed)
        k = Counter(o.kind for o in w.objects.values())
        assert k["tree"] + k["pine"] >= 80, k
        assert k["bush"] >= 25
        assert k["rock"] >= 30
        assert k["copper_vein"] >= 4
        assert k["iron_vein"] >= 3
        assert k["clay"] >= 6
        assert k["terminal"] == 2
        assert k["tablet"] == 2


def test_spawn_walkable():
    w = generate_world(7)
    for _ in range(100):
        x, y = w.spawn_point()
        assert w.walkable(x, y)


def test_hearers_radius():
    w = generate_world(7)
    cx, cy = w.center
    a = Creature("c1", "A", cx, cy)
    b = Creature("c2", "B", cx + 5, cy)
    c = Creature("c3", "C", cx + 6, cy)
    for cr in (a, b, c):
        w.creatures[cr.id] = cr
    names = {h.name for h in hearers(w, cx, cy)}
    assert names == {"A", "B"}
