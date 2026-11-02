import importlib.util
from pathlib import Path

from swarmworld.node.brain import MockBrain

spec = importlib.util.spec_from_file_location("world_bench", Path(__file__).resolve().parent.parent / "bench" / "world_bench.py")
world_bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(world_bench)


async def test_turn_based_episode_with_mock_brain():
    r = await world_bench.episode("mock", MockBrain(1), seed=100, creatures=3, ticks=200, slots=8)
    assert r["thinks"] > 50 and r["parse_failures"] == 0
    assert "rope" in r["first"]
    assert {"noop_rate", "collapses", "inventions"} <= set(r)
    table = world_bench.summarize([r], 200)
    assert "| mock |" in table and "no-op" in table and "collapses" in table
