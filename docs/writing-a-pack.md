# How to write a pack

*(Current as of `72898c2`, after both fix rounds.)*

A pack is **one module**, `swarmworld/world/packs/<pack>.py`, plus **data** in `swarmworld/data/packs/<pack>/` (any
of `items.json`, `recipes.json`, `objects.json`). Nothing needs registering in core files: the folders are scanned.
The registry's docstring (`swarmworld/world/registry.py`) is the reference.

| You add | How |
|---|---|
| items, recipes | `items.json`, `recipes.json` (merged after the base files) |
| object kinds | `objects.json`: `name, aliases, blocking, animal, gatherable, carvable, store, gives, yields, look`; `glow` (steps) makes a soft night light, like fireflies; `glyph` (`{"char": "⌂", "color": "#c8a070"}`) is how the ASCII skin, and any skin without art for the kind, draws it (else `web/tiles.js` GLYPHS, else the name's first letter) |
| a verb | `register_verb(name, handler, aliases=(), *, replaces_alias=False, alias_targets=None)`; `alias_targets={"dig_down": "down"}` gives an alias that also says where its target, when the intention names none |
| its disclosure | `register_technique(Technique(name, line, trigger))`, shown to every creature when the trigger fits |
| world behaviour | `register_system(name, every, fn(sim, tick))` |
| a perception line | `register_perception(fn(world, c) -> str or None, priority=50)` |
| placing things | `register_populate(name, fn(world, rng, fresh), land=fn(world, rng, bounds))`, run on new worlds and restored saves; `land`: fill one new land (the frontier), inside bounds, with no once-flag |
| state | `c.ext[<pack>]` and `world.ext[<pack>]`: JSON-able, saved automatically |
| a sound | `world.sound(x, y, text, radius=8, kind=..., loud=False, source=c.id, makers=None)`; kinds from `registry.SOUND_KINDS` |

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
    x0, y0, x1, y1 = world.region_bounds("surface")  # the surface only: see Regions below
    shore = [(x, y) for y in range(y0, y1) for x in range(x0, x1)
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

## Regions

The map is one grid in bands of rows: the surface on top, then, past a band of solid rock (`REGION_GAP` rows of `R`),
regions below it, like the deep (`world.regions`, `world.region_at(x, y)`). A pack's world stays on the surface unless
it is meant for below:
- Scan and sample `world.region_bounds("surface")` (`x0, y0, x1, y1`, half-open), never `range(world.height)` or
  `rng.randrange(world.height)`: `world.height` counts every region and the rock between them. Counts per area (how
  many of a kind a world holds) use the surface's area. On a world with only a surface, `rng.randrange(y0, y1)` draws
  exactly what `rng.randrange(world.height)` did, so the world's rolls don't change.
- Anything about the sky (weather, the time of day, daylight, night) asks `world.under_sky(x, y)` for the spot it
  touches: no rain, wind, heat or thunder below.
- Sensing already stays in a region: sight, `hearers` (sounds and speech), landmarks, remembered spots and terminals
  never cross one. Your own distance checks between two things add `world.same_region(a, b)`.
- Water to drink, fill a pot at or fish in is `model.WATER_TILES` (`w`, `W` and cave water `u`), not `"wW"`.

Rules of thumb:
- **Imports.** At its top a pack module imports only from `swarmworld.world` (`actions`, `model`, `perception`,
  `catalog`, `events`, `registry`, `terrain`). Import `simulation`, `swarmworld.mind.*` and `swarmworld.server.*`
  only under `TYPE_CHECKING` or inside a function. `test_packs_import_whichever_module_comes_first` catches a mistake.
- **Every verb needs a technique.** `test_mind` and `test_techniques` fail otherwise. The system prompts describe only
  the core verbs. Pack techniques are shown to every creature. For creatures with the disclose layer they share the
  list with the core ones, and the best two that fit keep their slots (at most half the list), so a high score
  matters most when several packs' techniques fit at once.
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
  - Pass `source=c.id` for a creature's own action, so it isn't echoed back (a thing's id, like a fire's, for a
    thing's own noise), and `makers=[ids]` for the others making it with them (a crowd doesn't hear itself).
  - `loud=True` only for what should wake sleepers (thunder).
  - `kind` comes from `registry.SOUND_KINDS`, which is advisory: chop, knock, splash, fire, thunder, rain, river,
    crickets, bird, `animal:<kind>`, crowd, footsteps, build, music, dance, hunt, rustle.
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

## Positions move

When the frontier lays new land in the west, every x in the world moves east by the width added (`World.shift_x`),
so a position a pack keeps in its own state has to move too. The core moves creatures, objects, the ground, tile
changes, landmarks and events. A pack that keeps positions in `ext` (a tile list, an `"x,y"` key, a rectangle's
`x0`/`x1`, a remembered `[x, y]`) registers a hook next to its other registrations:

```python
def _shift(world, n):
    ...  # add n to every stored x; `shift_key("12,5", n)` re-keys an "x,y" string

register_shift_hook("mypack", _shift, stores=("ext.mypack.camps", "creature.ext.mypack.home"))
```

`stores` names what the hook moves, by path (a dotted path from `ext.<pack>`, `creature.ext.<pack>` or `object.data`;
a key that isn't `[a-z_]+` is written `*`, a list's items `[]`). Hooks run in registration order and take no dice.
Unlike the other callbacks, a shift hook that raises isn't skipped: the growth is abandoned and the whole world put
back as it was, so a half-moved world is never saved.
`test_no_store_of_positions_goes_unshifted` walks the world for anything shaped like a position (`{x, y}`, `x0..y1`,
a pair of ints or `[x, y, tick]`, an `"x,y"` key or string) and fails for one that no declared store covers. Put one of
your positions in the `everything` fixture in tests/test_frontier_shift.py, so the canary and the property test see
it. A path that really never moves goes in that test's `IGNORED`, with the reason.
