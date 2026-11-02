# How to write a pack

*(Current as of `72898c2`, after both fix rounds.)*

A pack is **one module**, `swarmworld/world/packs/<pack>.py`, plus **data** in `swarmworld/data/packs/<pack>/` (any
of `items.json`, `recipes.json`, `objects.json`). Nothing needs registering in core files: the folders are scanned.
The registry's docstring (`swarmworld/world/registry.py`) is the reference.

| You add | How |
|---|---|
| items, recipes | `items.json`, `recipes.json` (merged after the base files) |
| object kinds | `objects.json`: `name, aliases, blocking, animal, gatherable, carvable, store, gives, yields, look`; `glow` (steps) makes a soft night light, like fireflies |
| a verb | `register_verb(name, handler, aliases=(), *, replaces_alias=False)` |
| its disclosure | `register_technique(Technique(name, line, trigger))`, shown to every creature when the trigger fits |
| world behaviour | `register_system(name, every, fn(sim, tick))` |
| a perception line | `register_perception(fn(world, c) -> str or None, priority=50)` |
| placing things | `register_populate(name, fn(world, rng, fresh))`, run on new worlds and restored saves |
| state | `c.ext[<pack>]` and `world.ext[<pack>]`: JSON-able, saved automatically |
| a sound | `world.sound(x, y, text, radius=8, kind=..., loud=False, source=c.id)`; kinds from `registry.SOUND_KINDS` |

Worked example, pack `marsh` (installed and run end to end at `72898c2`, then removed): one item, one recipe, one
data-only kind with yields, one verb with its technique, one system, one perception line, one sound, plus populate
and per-creature state.

`swarmworld/data/packs/marsh/items.json`
```json
{
  "reed": {"name": "reed", "aliases": ["reeds"], "tags": ["plant"], "desc": "A long hollow stem; it bends without breaking."},
  "reed_mat": {"name": "reed mat", "aliases": ["mat"], "desc": "A woven mat, soft to sit or sleep on."}
}
```

`swarmworld/data/packs/marsh/recipes.json` (one recipe per output: a variant gets its own output, e.g. `berry_stew`
and `fish_stew`)
```json
[
  {"output": "reed_mat", "inputs": {"reed": 4, "plant_fiber": 1}}
]
```

`swarmworld/data/packs/marsh/objects.json`. A gatherable with no code: 3 uses of 1-3 reeds each, then it becomes cut
reeds, and it grows back after 600 ticks. `look` is the art stream's hint. The kind only appears in worlds where
something places it (populate, below).
```json
{
  "reed_bed": {"name": "reed bed", "aliases": ["reeds", "reed bed", "rushes"], "look": "reeds",
               "yields": {"items": {"reed": [1, 3]}, "uses": 3, "becomes": "reed_stubble", "regrow": 600}},
  "reed_stubble": {"name": "cut reeds", "aliases": ["stubble", "cut reeds"], "look": "reeds_cut"}
}
```

`swarmworld/world/packs/marsh.py`
```python
"""Marsh: reed beds along the shore (data: swarmworld/data/packs/marsh/), skimming stones, frogs at night."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..actions import ActionResult
from ..perception import visible_objects
from ..registry import (Technique, register_perception, register_populate, register_system, register_technique,
                        register_verb)

if TYPE_CHECKING:  # never at the top for real: simulation imports the packs (see registry.py)
    from ..model import Creature, World
    from ..simulation import Simulation


def _water_beside(world: World, x: int, y: int) -> bool:
    return any(world.in_bounds(x + dx, y + dy) and world.tile(x + dx, y + dy) in "wW"  # off the map is not water
               for dx in (-1, 0, 1) for dy in (-1, 0, 1))


def _skim(world: World, c: Creature, it) -> ActionResult:          # the verb's handler
    if not _water_beside(world, c.x, c.y):
        return ActionResult(False, "There's no water beside you to skim a stone on.")
    if c.inventory.get("stone", 0) <= 0:
        return ActionResult(False, "You'd need a flat stone to skim.")
    c.inventory["stone"] -= 1
    if c.inventory["stone"] <= 0:
        del c.inventory["stone"]
    hops = world.rng.randint(1, 6)
    mine = c.ext.setdefault("marsh", {})  # this pack's state for this creature, saved with the world
    best, mine["best_hops"] = mine.get("best_hops", 0), max(mine.get("best_hops", 0), hops)
    world.sound(c.x, c.y, "a stone skipping across the water", radius=6, kind="splash", source=c.id)  # the sound
    record = " Your best yet!" if hops > best else ""
    return ActionResult(True, f"You skim a stone across the water. It hops {hops} times before it sinks.{record}")


def _skim_fits(world: World, c: Creature) -> float | None:          # the technique's trigger: None = not now
    return 2.0 if c.inventory.get("stone") and _water_beside(world, c.x, c.y) else None


def _frogs(sim: Simulation, t: int) -> None:                         # the system: sparing ambient sound
    """At night a few reed beds croak: a sound for whoever is near, never an action for anyone."""
    w = sim.world
    if w.clock()["phase"] != "night":
        return
    beds = [o for o in w.objects.values() if o.kind == "reed_bed"]
    for o in w.rng.sample(beds, min(3, len(beds))):
        w.sound(o.x, o.y, "frogs croaking", radius=6, kind="animal:frog")


def _soft_ground(world: World, c: Creature) -> str | None:          # the perception line: only when relevant
    if any(o.kind in ("reed_bed", "reed_stubble") for o, _, _ in visible_objects(world, c, 1)):
        return "The ground is soft and wet among the reeds."
    return None


def _place_reeds(world: World, rng, fresh: bool) -> None:           # populate: new worlds and older saves alike
    mine = world.ext.setdefault("marsh", {})
    if mine.get("reeds_placed"):  # idempotent: once per world
        return
    shore = [(x, y) for y in range(world.height) for x in range(world.width)
             if world.tile(x, y) in "gd" and (x, y) not in world.grid and _water_beside(world, x, y)]
    for x, y in rng.sample(shore, min(12, len(shore))):
        world.add_object("reed_bed", x, y)
    mine["reeds_placed"] = True


register_verb("skim", _skim, aliases=("skip_stone", "skim_stone"))
register_technique(Technique("skim", "skim: skip a stone you carry across the water beside you.", _skim_fits))
register_system("marsh frogs", 40, _frogs)
register_perception(_soft_ground, priority=70)  # ambience: more urgent lines (lower numbers) come first
register_populate("marsh reeds", _place_reeds)
```

What it did when run:
- a fresh world got 12 reed beds;
- gather gave "You gathered 2 reed.";
- the perception line showed;
- the skim tip reached a creature without the disclose layer;
- skimming twice left `c.ext == {"marsh": {"best_hops": 2}}`, which survived save and restore;
- restoring kept 12 beds, and the pre-pack save got 12, once.

`tests/test_pack_marsh.py` (shape; the fixtures `prepack_save` and `data_dir` come from `tests/conftest.py`):
```python
from swarmworld.server.persistence import restore
from swarmworld.server.state import ServerState
from swarmworld.world import registry


def test_marsh_old_save_loads(prepack_save):
    st = ServerState(seed=1)
    restore(st, prepack_save)                     # populate runs with fresh=False: reeds get placed once
    assert st.world.ext["marsh"]["reeds_placed"]
    for c in st.world.creatures.values():
        c.asleep = False
    for _ in range(200):
        st.tick_message(st.sim.tick())


def test_something_test_only():
    with registry.sandbox():                      # anything registered here is undone afterwards
        ...
```

Rules of thumb:
- **Imports.** At its top a pack module imports only from `swarmworld.world` (`actions`, `model`, `perception`,
  `catalog`, `events`, `registry`, `terrain`). Import `simulation`, `swarmworld.mind.*` and `swarmworld.server.*`
  only under `TYPE_CHECKING` or inside a function. `test_packs_import_whichever_module_comes_first` catches a mistake.
- **Every verb needs a technique.** `test_mind` and `test_techniques` fail otherwise. The system prompts describe only
  the core verbs. Pack techniques are shown to every creature, ranked with the core ones for creatures that have the
  disclose layer.
- **Names are global.** Verbs, aliases, kinds, techniques, systems, populate hooks, item ids and recipe outputs are
  shared across packs; a clash fails at import, naming both. Prefer specific words.
  - A word that is a core alias (tell, show, chop, dig, harvest, sleep, look, search, build...) raises unless you pass
    `replaces_alias=True`. Then you own the word, so hand what your verb doesn't cover to the core verb
    (`HANDLERS["craft"]` for S6's `build`).
  - An item name or alias that already names another item logs a warning and fails
    `test_installed_data_is_consistent`; the first item keeps the name.
- **Perception lines** say something only when it's relevant right now or has changed: not the same line every turn.
  At most 2 a turn for all packs together; lower `priority` wins (urgent below 50, ambience above), then the first
  registered. Once the lines are full, later functions aren't called that turn.
- **Sounds.**
  - Pass `source=c.id` for a creature's own action, so it isn't echoed back.
  - `loud=True` only for what should wake sleepers (thunder).
  - `kind` comes from `registry.SOUND_KINDS`, which is advisory: chop, knock, splash, fire, thunder, rain, river,
    crickets, bird, `animal:<kind>`, crowd, footsteps, build, music, dance, hunt.
  - Every sound is an event, logged and sent to viewers, so emit ambient ones from systems sparingly (cooldowns, a few
    at a time).
  - A creature hears at most 2 sounds a turn, the latest of each kind. Sounds aren't memories and don't make anyone
    think.
- **Systems** run after the world's built-in steps, every `every` ticks, in registration order. They change the world;
  they never choose actions for creatures. A sound a system emits is heard on the next tick.
- **State** goes under your pack's name: `c.ext["play"]["joy"]`, `world.ext["nature"][...]`. Keep it JSON-able (it's
  saved as is). Older saves start with `{}`, so read it with defaults.
- **Populate** must be idempotent (a flag in `world.ext[<pack>]`). It runs at the end of `generate_world` with the
  generator's rng and `fresh=True`, and after every restore with `fresh=False`. S1, which owns terrain.py: keep the
  `run_populate` call at the end of `generate_world`.
- **Failures are contained, not hidden.** A system, perception function, trigger or populate hook that raises is
  logged (logger `swarmworld.packs`, once a minute per callback) and skipped; the world keeps running. Because nothing
  crashes, test that your callbacks actually do their job.
- **Tests.** Use `with registry.sandbox():` for test-only registrations, `data_dir` for throwaway data folders, and
  `prepack_save` for `test_<pack>_old_save_loads`.
- **Report your kinds** with their `look` hints, for S7.
