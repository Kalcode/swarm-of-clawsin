"""Layer 2: progressive disclosure. The core prompt names only the everyday verbs; the rest are shown
as one-line techniques when something in the creature's surroundings or pockets makes them fit.
This only shows. It never picks an action, and every verb stays valid whether shown or not."""

from __future__ import annotations

from ..world.actions import ANIMAL_FOOD, CARVABLE, STORES
from ..world.events import HEARING
from ..world.model import ANIMALS, Creature, World
from ..world.perception import dist, visible_creatures, visible_objects
# Technique lives in the world's registry so packs can disclose their verbs; TECHNIQUES is the shared list: the core
# techniques below first, then every pack's (register_technique).
from ..world.registry import TECHNIQUES, Technique, register_core_techniques

CORE_VERBS = ["walk_to", "explore", "gather", "eat", "drink", "say", "give", "combine", "craft", "rest", "wait", "wish"]


def _seen(world: World, c: Creature, kinds=None):
    return [(o, d) for o, d, _ in visible_objects(world, c) if kinds is None or o.kind in kinds]


def _near(world: World, c: Creature, kinds, reach: int = 1) -> bool:
    return any(d <= reach for _, d in _seen(world, c, kinds))


def _carved(o) -> bool:
    return o.kind in CARVABLE and bool(o.data.get("text"))


def _read(world, c):
    for o, _ in _seen(world, c):
        if o.kind in {"terminal", "tablet", "sign"} or _carved(o):
            return 6.0
    return None


def _program(world, c):
    return 7.0 if _seen(world, c, {"terminal"}) else None


def _write(world, c):
    if c.inventory.get("sign") or _near(world, c, {"sign"} | CARVABLE):
        return 4.0
    return None


def _store(world, c):
    return 5.0 if _seen(world, c, STORES) else None


def _placeable(world, c) -> bool:
    items = world.catalog.items
    return any(n > 0 and i in items and items[i].placeable for i, n in c.inventory.items())


def _place(world, c):
    return 4.5 if _placeable(world, c) else None


def _plant(world, c):
    items = world.catalog.items
    for i, n in c.inventory.items():
        if n > 0 and (i == "berries" or (i in items and "seed" in items[i].tags)):
            return 5.5
    return None


def _teach(world, c):
    return 3.0 if any(d <= HEARING for _, d, _ in visible_creatures(world, c)) else None


def _invent(world, c):
    kinds = sum(1 for n in c.inventory.values() if n > 0)
    if kinds >= 2 and not c.stats.get(f"invented_day_{world.clock()['day']}"):
        return 3.5
    return None


def _ground(world, c):
    if any(world.ground.get((c.x + dx, c.y + dy)) for dx in (-1, 0, 1) for dy in (-1, 0, 1)):
        return 6.5
    if sum(1 for n in c.inventory.values() if n > 0) >= 6:
        return 2.5
    return None


def _fire(world, c):
    return 5.2 if _seen(world, c, {"campfire"}) else None


def _animal(world, c):
    if _seen(world, c, ANIMALS) and any(n > 0 and i in ANIMAL_FOOD for i, n in c.inventory.items()):
        return 5.8
    return None


register_core_techniques([
    Technique("read", "read (target): read a sign, carving, tablet or terminal.", _read),
    Technique("program", "program (text): enter Lua code into a terminal beside you.", _program),
    Technique("write", "write (text): carve words onto a sign, tree or boulder beside you; they stay for anyone to find.", _write),
    Technique("store", "store (target, items) / take (target, items): put things into a basket or chest for everyone, or take things out.",
              _store, ("store", "take")),
    Technique("place", "place (target): set down a structure you carry: campfire, workbench, sign, wooden wall, furnace, chest, terminal.", _place),
    Technique("plant", "plant (target, count): plant seeds or berries in the soil beside you (needs a tool to break the soil).", _plant),
    Technique("teach", "teach (target, items): show someone within earshot how to make a thing you know, e.g. target \"Mara\", items [\"stone knife\"].", _teach),
    Technique("invent", "invent (target, items, text): create something brand new from 2-4 things you carry, even other inventions. "
                        "target is its name, text says what it is or does. Once a day.", _invent),
    Technique("pick_up", "pick_up (target) / drop (target): take or leave items on the ground.", _ground, ("pick_up", "drop")),
    Technique("fire", "give (target, items): feed sticks to a campfire to keep it burning.", _fire, ()),
    Technique("feed", "give (target, items): feed an animal food it eats; fed often, it may come to trust you.", _animal, ()),
])

# Facts that left the core prompt's "Good to know"; kept for recall.
LORE = [
    ("tools", "Most tools begin with sticks, stone and plant fiber, and trying combinations is how anything new is found."),
    ("night", "Nights are dark, and fire gives light."),
    ("sharing", "Discoveries are precious: tell others what you learn, teach them, write recipes on signs."),
    ("manners", "Only name things you can actually see, carry or remember. Skip empty pleasantries; talk about useful things: "
                "where food and materials are, what you made and how, what you need, plans to work together."),
]


def relevant(world: World, c: Creature, limit: int = 5, packs_only: bool = False) -> list[str]:
    """The lines of the techniques that fit now, best first; packs_only: only those packs registered."""
    scored = [(s, t.line) for t in TECHNIQUES if (t.pack or not packs_only) and (s := t.trigger(world, c)) is not None]
    scored.sort(key=lambda p: -p[0])
    return [line for _, line in scored[:limit]]


def lore() -> list[tuple[str, str]]:
    return [(t.name, t.line) for t in TECHNIQUES] + LORE
