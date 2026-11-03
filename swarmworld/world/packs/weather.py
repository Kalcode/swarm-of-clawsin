"""Weather: rain, drizzle, fog, wind, storms and heat. Owns the old Simulation._weather.

State: world.weather (the kind) and world.weather_until (the tick it ends) stay where older saves and the steward API
expect them; world.ext["weather"] holds the derived bits ("sight": a cap on how far anyone sees, in fog).
"""

from __future__ import annotations

from .. import perception
from ..model import World, wet
from ..perception import direction, dist
from ..registry import register_perception, register_system

CLEAR = "clear"
KINDS = ("clear", "rain", "drizzle", "fog", "wind", "storm", "heat")
DURATION = {"rain": (200, 450), "drizzle": (150, 300), "fog": (150, 350), "wind": (150, 350),
            "storm": (120, 260), "heat": (200, 400)}
CHOICES = (("rain", 0.40), ("drizzle", 0.15), ("fog", 0.15), ("wind", 0.12), ("storm", 0.08), ("heat", 0.10))
STARTS = {"rain": "Clouds gather, and rain begins to fall.", "drizzle": "A fine drizzle begins to fall.",
          "fog": "A thick fog rolls in.", "wind": "The wind picks up and begins to howl.",
          "storm": "Dark clouds pile up and a storm breaks.", "heat": "The air turns hot and heavy."}
ENDS = {"rain": "The rain stops and the clouds drift apart.", "drizzle": "The drizzle thins away.",
        "fog": "The fog lifts.", "wind": "The wind dies down.", "storm": "The storm blows itself out.",
        "heat": "The heat breaks at last."}
LINES = {"drizzle": "A fine drizzle is falling.",  # rain and fog are in the core time line (perception.perceive)
         "wind": "Wind tugs at everything; fires eat their fuel faster.",
         "storm": "A storm is raging: rain, wind and thunder.",
         "heat": "The heat is heavy; you hunger faster."}
FOG_SIGHT = 3
WIND_CARRY = 1.5  # sounds carry this much farther on a windy day
FIRE_EXTRA = 10  # extra ticks of fuel a campfire loses per 10 ticks of wind: it burns twice as fast
THUNDER_RADIUS = 16
THUNDER_CHANCE = 0.2  # per 10 ticks of storm
STRIKE_CHANCE = 0.12  # of a thunderclap, a tree is struck
BURN_TICKS = 30
WINDY = ("wind", "storm")


def current(world: World) -> str:
    return getattr(world, "weather", CLEAR)


def _state(world: World) -> dict:
    return world.ext.setdefault("weather", {})


def sync(world: World) -> None:
    """Derive ext from the current kind (the steward or an old save may have set world.weather directly)."""
    st = _state(world)
    if current(world) == "fog":
        st["sight"] = FOG_SIGHT
    else:
        st.pop("sight", None)


def set_weather(world: World, kind: str, until: int, announce: bool = False) -> None:
    if kind not in KINDS:
        raise ValueError(f"weather is one of {', '.join(KINDS)}")
    world.weather, world.weather_until = kind, until
    sync(world)
    if announce and kind != CLEAR:
        world.emit("weather", None, *world.center, STARTS[kind])


def carry(world: World, radius: int) -> int:
    """How far a sound of this radius carries in today's weather."""
    return round(radius * WIND_CARRY) if current(world) in WINDY else radius


def _roll(world: World) -> str:
    x, acc = world.rng.random(), 0.0
    for kind, p in CHOICES:
        acc += p
        if x < acc:
            return kind
    return CHOICES[-1][0]


def _step(sim, t: int) -> None:
    w = sim.world
    sync(w)
    kind = current(w)
    if t % 50 == 0:
        if kind != CLEAR:
            if t >= getattr(w, "weather_until", 0):
                w.weather = CLEAR
                w.emit("weather", None, *w.center, ENDS.get(kind, "The sky clears."))
                sync(w)
            elif kind == "rain" and w.rng.random() < 0.1:  # a long rain can turn into a storm
                set_weather(w, "storm", w.weather_until, announce=True)
        elif w.rng.random() < 0.05:
            new = _roll(w)
            lo, hi = DURATION[new]
            set_weather(w, new, t + w.rng.randint(lo, hi), announce=True)
        kind = current(w)
    if t % 10 == 0:
        if kind in WINDY:
            for o in w.objects.values():
                if o.kind == "campfire" and o.data.get("lit"):
                    o.data["lit_until"] = o.data.get("lit_until", 0) - FIRE_EXTRA
        if kind == "storm":
            _storm(w, t)
        _burn(w, t)
    if t % 48 == 0 and kind == "heat":  # the heat saps appetite faster: about half again as hungry
        for c in w.creatures.values():
            if not c.collapsed and not c.asleep:
                c.satiety = max(0.0, c.satiety - 1)


def _storm(w: World, t: int) -> None:
    if w.rng.random() >= THUNDER_CHANCE:
        return
    x, y = w.rng.randrange(w.width), w.rng.randrange(w.height)
    trees = [o for o in w.objects.values() if o.kind in ("tree", "pine") and not o.data.get("burning")]
    struck = None
    if trees and w.rng.random() < STRIKE_CHANCE:
        struck = w.rng.choice(trees)
        x, y = struck.x, struck.y
    w.sound(x, y, "a crack of thunder" if struck else "thunder rolling", radius=carry(w, THUNDER_RADIUS),
            kind="thunder", loud=True)
    if struck:
        struck.data["burning"] = t + BURN_TICKS
        _state(w).setdefault("burning", []).append(struck.id)
        w.changed_objects.add(struck.id)
        w.emit("lightning", None, x, y, "Lightning strikes a tree and it bursts into flame.")


def _burning(w: World) -> list:
    return w.ext.get("weather", {}).get("burning") or []


def _burn(w: World, t: int) -> None:
    ids = _burning(w)
    if not ids:
        return
    _state(w)["burning"] = [i for i in ids if i in w.objects and w.objects[i].data.get("burning")]
    for oid in ids:
        o = w.objects.get(oid)
        until = o.data.get("burning") if o else None
        if until and t >= until:
            _state(w)["burning"] = [i for i in _state(w)["burning"] if i != oid]
            o.data.pop("burning", None)
            w.change_kind(o, "stump")
            o.data["regrow_at"] = t + 800
            o.data.pop("wood", None)
            w.emit("fire_out", None, o.x, o.y, "A struck tree burned down to a stump.")


def _weather_line(world: World, c) -> str | None:
    if wet(world, drizzle=True) and perception.roof_over(world, c.x, c.y):  # the building's line says it's wet out
        return None
    return LINES.get(current(world))


def _burning_line(world: World, c) -> str | None:
    from ..perception import sight_range
    ids = _burning(world)
    if not ids:
        return None
    r = sight_range(world, c)
    best = None
    for o in (world.objects.get(i) for i in ids):
        if o and o.data.get("burning") and world.same_region((c.x, c.y), (o.x, o.y)):
            d = dist(c.x, c.y, o.x, o.y)
            if d <= max(r, 8) and (best is None or d < best[0]):
                best = (d, o)
    if not best:
        return None
    d, o = best
    return f"A tree is on fire {'right here' if d == 0 else f'about {d} steps ' + direction(o.x - c.x, o.y - c.y)}."


register_system("weather", 2, _step)
register_perception(_burning_line, priority=30)
register_perception(_weather_line, priority=50)
