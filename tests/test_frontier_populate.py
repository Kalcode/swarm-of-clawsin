"""Populate hooks that fill one land: food and nature place their things inside given bounds."""
import logging
import random

from swarmworld.world import registry
from swarmworld.world.packs import food, nature
from swarmworld.world.terrain import generate_world


def _cleared(seed=7):
    w = generate_world(seed, 64, 64)
    for o in [o for o in w.objects.values() if o.x < 32 and o.y < 32]:
        w.remove_object(o.id)
    return w


def test_land_hooks_place_inside_their_bounds_only():
    w = _cleared()
    before = set(w.objects)
    registry.run_populate_land(w, random.Random(1), (0, 0, 32, 32))
    new = [w.objects[i] for i in set(w.objects) - before]
    assert new and all(o.x < 32 and o.y < 32 for o in new)
    kinds = {o.kind for o in new}
    assert kinds & set(nature.PLANTS) and kinds & set(food.habitat_kinds())


def test_land_hooks_grow_the_renewal_targets():
    w = _cleared()
    t0 = dict(w.ext["nature"]["targets"])
    before = set(w.objects)
    registry.run_populate_land(w, random.Random(1), (0, 0, 32, 32))
    added = [w.objects[i].kind for i in set(w.objects) - before]
    for k in nature.RENEWING:
        assert w.ext["nature"]["targets"][k] == t0.get(k, 0) + added.count(k)
    assert any(added.count(k) for k in nature.RENEWING)


def test_land_hooks_roll_only_the_rng_given():
    w = _cleared()
    state = w.rng.getstate()
    registry.run_populate_land(w, random.Random(1), (0, 0, 32, 32))
    assert w.rng.getstate() == state


def test_a_failing_land_hook_is_skipped(caplog):
    w = _cleared()
    with registry.sandbox():
        def boom(w, rng, bounds):
            raise RuntimeError("land boom")
        registry.register_populate("boom", lambda w, r, f: None, land=boom)
        before = len(w.objects)
        with caplog.at_level(logging.ERROR, logger="swarmworld.packs"):
            registry.run_populate_land(w, random.Random(1), (0, 0, 32, 32))
        assert "land boom" in caplog.text and len(w.objects) > before


def test_the_whole_world_populates_as_before():
    a, b = generate_world(7), generate_world(7)
    key = lambda w: sorted((o.id, o.kind, o.x, o.y) for o in w.objects.values())
    assert key(a) == key(b)
