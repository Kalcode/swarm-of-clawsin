"""Which harness layers this world has, and which creatures get each: the live trial split."""

from __future__ import annotations

from collections.abc import Iterable

from ..world.model import Creature

LAYERS = ("plan", "disclose", "recall")


class Harness:
    def __init__(self, available: set[str] | None = None, everyone: set[str] | None = None):
        self.available = set(available or ())
        self.everyone = set(everyone or ())

    def layers_for(self, c: Creature) -> set[str]:
        return {layer for layer in self.available if layer in self.everyone or c.harness.get(layer)}

    def assign(self, creatures: Iterable[Creature]) -> None:
        """Give each trial layer to half of each model's undecided creatures, and remember who got it."""
        by_model: dict[str, list[Creature]] = {}
        for c in sorted(creatures, key=lambda c: c.id):
            by_model.setdefault(c.model, []).append(c)
        for layer in sorted(self.available - self.everyone):
            for group in by_model.values():
                on = sum(1 for c in group if c.harness.get(layer) is True)
                off = sum(1 for c in group if c.harness.get(layer) is False)
                for c in group:
                    if layer in c.harness:
                        continue
                    c.harness[layer] = on <= off
                    on, off = on + (on <= off), off + (on > off)
