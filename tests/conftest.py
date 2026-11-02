import shutil
from pathlib import Path

import pytest

PREPACK_SAVE = Path(__file__).parent / "fixtures" / "prepack-64.json"


@pytest.fixture
def prepack_save(tmp_path) -> Path:
    """A copy of a world saved before the content packs: 64x64, 6 mock creatures, tick 1044, with a campfire, basket,
    sign, crops, a tamed animal and an invention (made with the code at c7f6dbc). Restore it with
    swarmworld.server.persistence.restore to check that an old save still loads."""
    copy = tmp_path / PREPACK_SAVE.name
    shutil.copy(PREPACK_SAVE, copy)
    return copy
