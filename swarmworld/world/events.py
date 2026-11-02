"""World events: things that happen at a place and time, which nearby creatures may perceive."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .model import Creature, World

HEARING = 5


@dataclass
class Event:
    tick: int
    kind: str
    actor: str | None
    x: int
    y: int
    text: str
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"tick": self.tick, "kind": self.kind, "actor": self.actor, "x": self.x, "y": self.y, "text": self.text}


def hearers(world: "World", x: int, y: int, radius: int = HEARING) -> list["Creature"]:
    return [
        c for c in world.creatures.values()
        if not c.collapsed and max(abs(c.x - x), abs(c.y - y)) <= radius
    ]
