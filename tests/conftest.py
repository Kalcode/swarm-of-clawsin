import json
import shutil
from pathlib import Path

import pytest

from swarmworld.world.catalog import DATA

PREPACK_SAVE = Path(__file__).parent / "fixtures" / "prepack-64.json"


@pytest.fixture
def prepack_save(tmp_path) -> Path:
    """A copy of a world saved before the content packs: 64x64, 6 mock creatures, tick 1044, with a campfire, basket,
    sign, crops, a tamed animal and an invention (made with the code at c7f6dbc). Restore it with
    swarmworld.server.persistence.restore to check that an old save still loads."""
    copy = tmp_path / PREPACK_SAVE.name
    shutil.copy(PREPACK_SAVE, copy)
    return copy


@pytest.fixture
def data_dir(tmp_path):
    """Make a data folder like swarmworld/data: copies of the base files, plus packs/<pack>/<file>.json for each pack,
    e.g. data_dir({"marsh": {"items": {...}, "recipes": [...], "objects": {...}}}). Read it with Catalog.load(path) or
    swarmworld.world.registry.load_objects(path)."""
    made = []

    def make(packs: dict) -> Path:
        root = tmp_path / f"data{len(made) + 1}"
        made.append(root)
        root.mkdir()
        for name in ("items.json", "recipes.json", "objects.json"):
            shutil.copy(DATA / name, root / name)
        for pack, files in packs.items():
            (root / "packs" / pack).mkdir(parents=True)
            for name, content in files.items():
                (root / "packs" / pack / f"{name}.json").write_text(json.dumps(content))
        return root

    return make


@pytest.fixture
def two_levels():
    """A factory: two_levels(24) is a size x size grass World with a 24-row "deep" region (floor of cave floor, a
    sky-less region without weather) added below the rock band. Rows 0-23 are the surface, 24-55 rock, 56-79 the deep."""
    from swarmworld.world.catalog import Catalog
    from swarmworld.world.model import World

    def make(size: int = 24) -> World:
        w = World(size, size, [["g"] * size for _ in range(size)], Catalog.load())
        w.add_region("deep", -1, [["c"] * size for _ in range(size)], sky=False, weather=False)
        return w
    return make
