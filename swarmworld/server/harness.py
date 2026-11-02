"""Which harness layers this world has, and which creatures get each: the live trial split."""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Iterable
from itertools import combinations

from ..world.model import Creature

LAYERS = ("plan", "disclose", "recall")


def _draw(layer: str, cid: str) -> str:
    """A stable, per-layer shuffle key: each layer orders a model's creatures differently."""
    return hashlib.sha1(f"{layer}:{cid}".encode()).hexdigest()


def _groups(c: Creature, groupings: list[tuple[str, ...]]) -> list[tuple]:
    """The groups a creature belongs to: its setting for each set of earlier layers, finest first."""
    return [(s, tuple(bool(c.harness.get(layer)) for layer in s)) for s in groupings]


class Harness:
    def __init__(self, available: set[str] | None = None, everyone: set[str] | None = None):
        self.available = set(available or ())
        self.everyone = set(everyone or ())

    def layers_for(self, c: Creature) -> set[str]:
        return {layer for layer in self.available if layer in self.everyone or c.harness.get(layer)}

    def assign(self, creatures: Iterable[Creature]) -> None:
        """Give each trial layer to half of each model's undecided creatures, and remember who got it.

        Layers are crossed: a layer is split half and half among the creatures that share the earlier layers'
        settings (falling back to coarser groups, then the whole model, to break ties), so no two layers land on
        the same creatures, each one's effect can be told apart, and each layer stays balanced per model. The order
        within a group is a stable hash of (layer, creature id). Decisions are kept and never revisited."""
        by_model: dict[str, list[Creature]] = {}
        for c in creatures:
            by_model.setdefault(c.model, []).append(c)
        trial = sorted(self.available - self.everyone)
        for i, layer in enumerate(trial):
            earlier = trial[:i]
            groupings = [s for n in range(len(earlier), -1, -1) for s in combinations(earlier, n)]  # finest first
            for members in by_model.values():
                given: Counter = Counter()  # (group, layer setting) -> creatures
                for c in members:
                    if layer in c.harness:
                        given.update((g, c.harness[layer]) for g in _groups(c, groupings))
                undecided = [c for c in members if layer not in c.harness]
                undecided.sort(key=lambda c: (_groups(c, groupings)[0], _draw(layer, c.id)))
                for c in undecided:
                    mine = _groups(c, groupings)
                    give = next((given[g, True] < given[g, False] for g in mine if given[g, True] != given[g, False]), True)
                    c.harness[layer] = give
                    given.update((g, give) for g in mine)
