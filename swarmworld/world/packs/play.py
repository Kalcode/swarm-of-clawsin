"""Play and culture: joy, games, dancing at a fire, music, and stories at night (data: swarmworld/data/packs/play/).

Joy (0-100) lives in c.ext["play"]["joy"], default 70. It falls slowly, never harms health, and only shows as one
perception line when low. Playing, dancing, music and stories raise it for everyone involved; playing together
emits "play" events, which the society graph counts as a "play" tie (once per pair per TIE_COOLDOWN ticks: the event's
"tie" says whether it counts)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..actions import ActionResult, find_creature, station_near
from ..events import hearers
from ..registry import Technique, register_perception, register_system, register_technique, register_verb

if TYPE_CHECKING:  # never at the top for real: simulation imports the packs (see registry.py)
    from ..model import Creature, World
    from ..simulation import Simulation

JOY_START = 70.0
JOY_EVERY = 20          # ticks per point of joy lost
LOW_JOY = 30.0          # below this, one perception line
RECOVERED = 45.0        # above this, the line may be shown again
INSTRUMENTS = ("flute", "drum")
STORY_COOLDOWN = 60     # ticks before the same speaker's next tale counts again
TIE_COOLDOWN = 200      # ticks before the same two playing together counts as another tie (the society graph)
FIRE_REACH = 3
GAMES = ("a game of tag", "a clapping game", "a guessing game", "a game of stones and sticks", "a wrestling match")


def _mine(c: Creature) -> dict:
    return c.ext.setdefault("play", {})


def joy(c: Creature) -> float:
    return float(_mine(c).get("joy", JOY_START))


def add_joy(c: Creature, n: float) -> None:
    mine = _mine(c)
    mine["joy"] = max(0.0, min(100.0, joy(c) + n))
    if mine["joy"] >= RECOVERED:
        mine.pop("restless_told", None)


def _awake_near(world: World, c: Creature, radius: int) -> list[Creature]:
    return [o for o in hearers(world, c.x, c.y, radius) if o.id != c.id and not o.asleep]


def _tie(world: World, a: Creature, b: Creature) -> bool:
    """Whether playing together now counts as a 'play' tie between a and b: once per pair per TIE_COOLDOWN ticks."""
    ties = world.ext.setdefault("play", {}).setdefault("ties", {})
    key = "|".join(sorted((a.id, b.id)))
    last = ties.get(key)
    if last is not None and 0 <= world.tick - last < TIE_COOLDOWN:
        return False
    for k in [k for k, t in ties.items() if not 0 <= world.tick - t < TIE_COOLDOWN]:  # forget what has cooled down
        del ties[k]
    ties[key] = world.tick
    return True


def _together(world: World, c: Creature, others: list[Creature], what: str) -> None:
    """Everyone involved is glad of it, remembers it once, and gets a 'play' tie with c (not again for a while)."""
    for o in others:
        add_joy(o, 6)
        _mine(o)["note"] = f"{c.name} {what}; you joined in and your spirits lift."
        world.emit("play", c.id, c.x, c.y, f"{c.name} and {o.name} {what}.", to=o.id, tie=_tie(world, c, o))


# ------------------------------------------------------------------ verbs
def _play(world: World, c: Creature, it) -> ActionResult:
    partner = find_creature(world, c, it.target, max_dist=3) if it.target else None
    if partner is None:
        near = sorted((o for o in _awake_near(world, c, 3)), key=lambda o: max(abs(o.x - c.x), abs(o.y - c.y)))
        partner = near[0] if near else None
    if partner is None or partner.asleep:
        return ActionResult(False, "There's no one near enough to play with. Games need company.")
    game = world.rng.choice(GAMES)
    add_joy(c, 15)
    _together(world, c, [partner], f"played {game}")
    world.sound(c.x, c.y, "laughter and play", radius=6, kind="crowd", source=c.id)
    return ActionResult(True, f"You play {game} with {partner.name}. Both of you laugh; your spirits lift.")


def _dance(world: World, c: Creature, it) -> ActionResult:
    if not station_near(world, c, "campfire", FIRE_REACH):
        return ActionResult(False, "There's no lit campfire to dance by. Dancing needs a fire's glow.")
    others = _awake_near(world, c, 4)
    add_joy(c, 12)
    if others:
        _together(world, c, others, "danced by the fire")
    world.sound(c.x, c.y, "feet stamping around a fire", radius=8, kind="dance", source=c.id)
    who = f" {others[0].name} joins in." if len(others) == 1 else (f" {len(others)} others join in." if others else "")
    return ActionResult(True, f"You dance by the fire, flames throwing your shadow about.{who} Your spirits lift.")


def _instrument(c: Creature) -> str | None:
    return next((i for i in INSTRUMENTS if c.inventory.get(i, 0) > 0), None)


def _music(world: World, c: Creature, it) -> ActionResult:
    want = (it.target or "").strip().lower()
    inst = next((i for i in INSTRUMENTS if i in want and c.inventory.get(i, 0) > 0), None) or _instrument(c)
    if inst is None:
        return ActionResult(False, "You have no instrument. A flute or a drum would do.")
    listeners = _awake_near(world, c, 6)
    add_joy(c, 10)
    if listeners:
        _together(world, c, listeners, f"made music on the {inst}")
    verb = "blow the flute" if inst == "flute" else "beat the drum"
    world.sound(c.x, c.y, "a flute playing" if inst == "flute" else "a drum beating", radius=12, kind="music", source=c.id)
    tail = f" {len(listeners)} nearby listen." if listeners else ""
    return ActionResult(True, f"You {verb}; the sound carries.{tail} Your spirits lift.")


# ------------------------------------------------------------------ techniques
def _play_fits(world: World, c: Creature) -> float | None:
    return 1.5 + (1.0 if joy(c) < LOW_JOY else 0.0) if _awake_near(world, c, 3) else None


def _dance_fits(world: World, c: Creature) -> float | None:
    return 2.0 if station_near(world, c, "campfire", FIRE_REACH) else None


def _music_fits(world: World, c: Creature) -> float | None:
    return 2.0 if _instrument(c) else None


# ------------------------------------------------------------------ systems
def _joy_falls(sim: Simulation, t: int) -> None:
    for c in sim.world.creatures.values():
        if not c.asleep and not c.collapsed:
            mine = _mine(c)
            mine["joy"] = max(0.0, joy(c) - 1)


def _stories(sim: Simulation, t: int) -> None:
    """A say near a lit fire after dark is a tale: listeners near the fire are cheered. Reads this tick's say events."""
    w = sim.world
    state = w.ext.setdefault("play", {})
    last, done = state.get("seen_tick", 0), state.get("seen_n", 0)
    fresh = []
    for ev in reversed(w.events):
        if ev.tick < last:
            break
        fresh.append(ev)
    fresh.reverse()
    skip = done
    for ev in fresh:
        if ev.tick == last and skip > 0:
            skip -= 1
            continue
        if ev.kind != "say" or not ev.actor or w.clock()["phase"] != "night":
            continue
        speaker = w.creatures.get(ev.actor)
        if speaker is None or not station_near(w, speaker, "campfire", FIRE_REACH):
            continue
        mine = _mine(speaker)
        if t - mine.get("last_story", -999) < STORY_COOLDOWN:
            continue
        listeners = [h for h in _awake_near(w, speaker, 5) if station_near(w, h, "campfire", FIRE_REACH + 1)]
        if not listeners:
            continue
        mine["last_story"] = t
        add_joy(speaker, 3)
        for h in listeners:
            add_joy(h, 6)
            _mine(h)["note"] = f"{speaker.name}'s tale by the fire holds you; your spirits lift."
    state["seen_tick"] = t
    state["seen_n"] = sum(1 for ev in fresh if ev.tick == t)


# ------------------------------------------------------------------ perception
def _note(world: World, c: Creature) -> str | None:
    return _mine(c).pop("note", None) if "note" in _mine(c) else None


def _restless(world: World, c: Creature) -> str | None:
    mine = _mine(c)
    if joy(c) < LOW_JOY and not mine.get("restless_told"):
        mine["restless_told"] = True
        return "You feel restless; some company or a game would do you good."
    return None


register_verb("play", _play, aliases=("play_game", "play_games", "game"))
register_verb("dance", _dance, aliases=("dance_by_fire",))
register_verb("make_music", _music, aliases=("music", "play_music", "play_flute", "play_drum", "drum", "flute"))
register_technique(Technique("play", "play: play a game with someone beside you; you both feel the better for it.", _play_fits))
register_technique(Technique("dance", "dance: dance by a lit campfire; anyone beside you may join and be cheered.", _dance_fits))
register_technique(Technique("make_music", "make_music: play the flute or drum you carry; all who hear it are cheered.",
                             _music_fits))
register_system("play joy", JOY_EVERY, _joy_falls)
register_system("play stories", 1, _stories)
register_perception(_note, priority=45)
register_perception(_restless, priority=60)
