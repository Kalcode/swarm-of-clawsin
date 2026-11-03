"""Golden fingerprints: generating the deep is a pure optimization target, so every world must stay identical tile for
tile and object for object. Regenerate GOLDEN only for a deliberate change of the maps:
    uv run python tests/test_deep_golden.py > tests/fixtures/deep_golden.json"""
import hashlib
import json
import random
import sys
from pathlib import Path

import pytest

from swarmworld.world.caves import carve_deep
from swarmworld.world.terrain import generate_world

GOLDEN = Path(__file__).parent / "fixtures" / "deep_golden.json"
WORLD_SEEDS = range(10)
DEEP_SEEDS = range(20)
DEEP_SIZES = (64, 128)


def _sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def world_print(seed: int) -> dict:
    w = generate_world(seed)
    objs = sorted((o.id, o.kind, o.x, o.y, o.data) for o in w.objects.values())
    return {"tiles": _sha(["".join(r) for r in w.tiles]), "objects": _sha(objs), "ext": _sha(w.ext)}


def deep_print(seed: int, size: int) -> str:
    dm = carve_deep(random.Random(seed), size, size)
    return _sha([dm.rows, dm.caverns, dm.pool])


def compute() -> dict:
    return {"worlds": {str(s): world_print(s) for s in WORLD_SEEDS},
            "deeps": {f"{s}:{n}": deep_print(s, n) for n in DEEP_SIZES for s in DEEP_SEEDS}}


@pytest.fixture(scope="module")
def golden():
    return json.loads(GOLDEN.read_text())


@pytest.mark.parametrize("seed", WORLD_SEEDS)
def test_world_is_unchanged(golden, seed):
    assert world_print(seed) == golden["worlds"][str(seed)]


@pytest.mark.parametrize("size", DEEP_SIZES)
def test_carve_deep_is_unchanged(golden, size):
    for seed in DEEP_SEEDS:
        assert deep_print(seed, size) == golden["deeps"][f"{seed}:{size}"], (seed, size)


if __name__ == "__main__":
    json.dump(compute(), sys.stdout, indent=1, sort_keys=True)
