"""Pack sound: the world's noises, told to creatures as text ("You hear chopping, about 6 steps north.") and sent to
viewers as sound events (web/sound.js plays them). Two sources, one system:
- the tick's new events (a gather beside a tree is chopping, beside rock knocking, a catch is a splash, a placed
  thing a thud), each kind of noise from one creature on a cooldown;
- ambience: a lit fire crackling, the river, a crowd talking, crickets at night, an animal now and then. Each has a
  long cooldown and only sounds where an awake creature is near enough to hear it.
Cooldowns live in world.ext["sound"]["cd"] (key -> tick it last sounded), so they survive a save."""
import random

from ..actions import TOOLS_AXE, _has_tool
from ..events import hearers
from ..perception import dist
from ..registry import ANIMALS, register_system

EVERY = 5  # ticks between ambience checks
ACTION_COOLDOWN = 8  # one creature's chopping (or knocking...) is heard at most this often
FIRE_COOLDOWN = 40
RIVER_COOLDOWN = 80
CROWD_COOLDOWN = 90
CRICKET_COOLDOWN = 60
ANIMAL_COOLDOWN = 120
RIVER_REACH = 4  # a creature this close to water hears the river
CROWD_SIZE = 3
CROWD_REACH = 4
TREES = ("tree", "pine")
STONES = ("rock", "copper_vein", "iron_vein", "clay")


def _state(world) -> dict:
    return world.ext.setdefault("sound", {}).setdefault("cd", {})


def _ready(world, key: str, wait: int) -> bool:
    cd = _state(world)
    last = cd.get(key)
    if last is not None and 0 <= world.tick - last < wait:
        return False
    cd[key] = world.tick
    if len(cd) > 400:  # forget what has long since cooled down
        for k in [k for k, t in cd.items() if world.tick - t > 1000]:
            del cd[k]
    return True


def _awake_near(world, x: int, y: int, radius: int) -> list:
    return [c for c in hearers(world, x, y, radius) if not c.asleep]


def _near_kinds(world, x: int, y: int, kinds) -> bool:
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            o = world.object_at(x + dx, y + dy)
            if o and o.kind in kinds:
                return True
    return False


def _from_events(sim, t: int) -> None:
    w = sim.world
    events = w.events
    last = getattr(sim, "_sound_last", None)
    start = 0
    if last is not None:
        for i in range(len(events) - 1, -1, -1):
            if events[i] is last:
                start = i + 1
                break
    else:
        start = max(0, len(events) - 50)
    if events:
        sim._sound_last = events[-1]
    for ev in events[start:]:
        if ev.kind == "gather":
            who = ev.actor or ""
            c = w.creatures.get(who)
            if "caught" in ev.text:
                if _ready(w, f"splash:{who}", ACTION_COOLDOWN):
                    w.sound(ev.x, ev.y, "a splash of water", radius=7, kind="splash", source=ev.actor)
            elif _near_kinds(w, ev.x, ev.y, TREES):
                if _ready(w, f"chop:{who}", ACTION_COOLDOWN):
                    axe = c is not None and _has_tool(c, TOOLS_AXE)
                    w.sound(ev.x, ev.y, "chopping" if axe else "branches snapping", radius=9, kind="chop", source=ev.actor)
            elif _near_kinds(w, ev.x, ev.y, STONES):
                if _ready(w, f"knock:{who}", ACTION_COOLDOWN):
                    w.sound(ev.x, ev.y, "knocking on stone", radius=8, kind="knock", source=ev.actor)
        elif ev.kind == "place":
            who = ev.actor or ""
            if _ready(w, f"build:{who}", ACTION_COOLDOWN):
                w.sound(ev.x, ev.y, "something being set down with a thud", radius=6, kind="build", source=ev.actor)


def _ambience(sim, t: int) -> None:
    w = sim.world
    rng = random.Random(t * 7919 + 13)  # its own rng: the world's stays untouched
    awake = [c for c in w.creatures.values() if not c.asleep and not c.collapsed]
    if not awake:
        return
    for o in list(w.objects.values()):
        if o.kind == "campfire" and o.data.get("lit") and _awake_near(w, o.x, o.y, 6):
            if _ready(w, f"fire:{o.id}", FIRE_COOLDOWN):
                w.sound(o.x, o.y, "a fire crackling", radius=6, kind="fire")
        elif o.kind in ANIMALS and _awake_near(w, o.x, o.y, 9) and rng.random() < 0.15:
            if _ready(w, f"animal:{o.kind}", ANIMAL_COOLDOWN):
                w.sound(o.x, o.y, f"a {o.kind.replace('_', ' ')} calling", radius=9, kind=f"animal:{o.kind}")
    for c in awake:
        spot = next(((x, y) for y in range(c.y - RIVER_REACH, c.y + RIVER_REACH + 1)
                     for x in range(c.x - RIVER_REACH, c.x + RIVER_REACH + 1)
                     if w.in_bounds(x, y) and w.tile(x, y) in "wW"), None)
        if spot:
            if _ready(w, "river", RIVER_COOLDOWN):
                w.sound(spot[0], spot[1], "water rushing", radius=8, kind="river")
            break
    if w.clock()["phase"] == "night" and _ready(w, "crickets", CRICKET_COOLDOWN):
        c = rng.choice(awake)
        for _ in range(8):  # a grassy spot a few steps from someone
            x, y = c.x + rng.randint(-5, 5), c.y + rng.randint(-5, 5)
            if w.in_bounds(x, y) and w.tile(x, y) in "gf":
                w.sound(x, y, "crickets chirping", radius=9, kind="crickets")
                break
    for c in awake:
        group = [o for o in awake if dist(o.x, o.y, c.x, c.y) <= CROWD_REACH]
        if len(group) >= CROWD_SIZE:
            if _ready(w, "crowd", CROWD_COOLDOWN):
                w.sound(c.x, c.y, "a crowd talking", radius=8, kind="crowd")
            break


def sound_system(sim, t: int) -> None:
    _from_events(sim, t)
    if t % EVERY == 0:
        _ambience(sim, t)


register_system("sound", 1, sound_system)
