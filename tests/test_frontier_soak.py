"""The soak, short: mock explorers on a small frontier."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from frontier_soak import soak  # noqa: E402

from swarmworld.world.model import FrontierSettings  # noqa: E402


def test_a_short_soak_grows_both_ways_and_keeps_its_gates():
    r = soak(ticks=1200, creatures=4, settings=FrontierSettings(on=True, pace=200, cap=256), start_near_edges=True,
             log=lambda *a: None)
    assert r["strips"]["east"] >= 1 and r["strips"]["west"] >= 1
    assert r["errors"] == 0 and r["stuck"] == 0 and r["round_trip"] and r["uncovered"] == []
    assert all(g["width"] == g["width_before"] + 32 for g in r["growths"])
