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
