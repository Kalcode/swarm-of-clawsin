"""The world clock: needs, activities, regrowth, fire, terminals, sounds, the packs' systems, and deciding who should
wake up and think."""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from typing import Callable

from . import perception
from .actions import ANIMAL_LURE, WELL_FED, ActionResult, step_activity
from .events import hearers
from .model import ANIMALS, Creature, World, wet
from .perception import DAY_SIGHT, SOUND_LINES, direction, dist, note_spots, sound_line, visible_creatures
from .registry import KINDS, LANDMARK_SOURCES, SYSTEMS, call_safely

INSPIRATION_CHANCE = {"curious": 0.12, "tinkerer": 0.12, "builder": 0.07, "teacher": 0.05}  # per thought
SATIETY_EVERY = 24  # one point every 12 s: about 20 minutes from full to starving
ENERGY_EVERY = 30  # about 40 energy a day: a creature needs a good rest roughly once a day
STARVE_EVERY = 4
IDLE_TICKS = 30
SLEEP_BELOW = {"reactive": 101, "proactive": 80}  # at night, idle creatures under this energy turn in (reactive: always)
ANIMAL_HUNGER_CHANCE = 0.25  # per evaluation: about 75 hunger a day if never grazing
ANIMAL_GRAZE_FILL = 3
ANIMAL_EVERY = 4  # ticks between animal evaluations
ANIMAL_BREED_CHANCE = 0.08
ANIMAL_CAP = 12  # per kind, world-wide
GRAZING = "gf"  # grass and forest floor: where animals can feed
HOME_RANGE = 3  # a tamed animal grazes within this many tiles of its home
WARY_RANGE = 3  # an untamed animal edges away from a stranger closer than this (a kind's "wary" in its data)
FLEE_STEPS = 1  # steps it takes away each time, one more if they're right beside it (a kind's "flee")
MET_FORGET = 200
WITNESS_RADIUS = 4
TERMINAL_EVERY = 20
COLLAPSE_TICKS = 60
CHAT_WINDOW = 60      # ticks
CHAT_LIMIT = 3        # lines a creature may say in the window before speech stops waking it

MemorySink = Callable[[Creature, str, int], None]
TerminalRunner = Callable[[World, object], list]


class Simulation:
    def __init__(self, world: World, memory_sink: MemorySink | None = None, terminal_runner: TerminalRunner | None = None):
        self.world = world
        self.memory_sink = memory_sink or (lambda c, text, imp: None)
        self.terminal_runner = terminal_runner
        self.heard: dict[str, list[str]] = defaultdict(list)
        self.hunger_alert: dict[str, int] = {}
        self.recent_says: dict[str, deque] = defaultdict(deque)
        self.sounds: dict[str, dict[str, str]] = defaultdict(dict)  # creature -> sound kind -> what it heard, latest last
        self._event_cursor = len(world.events)      # events already turned into hearing, learning and memories
        self._returned_cursor = len(world.events)   # events already handed back to the caller of tick()
        self.on_result: Callable[[Creature, ActionResult], None] | None = None
        self.inspiration = True  # occasional vague hunches for curious minds; off = purely unassisted
        self._lake_cache: tuple[tuple[int, int], tuple[int, int] | None] | None = None  # see _lake

    # ------------------------------------------------------------------
    def wake(self, c: Creature, reason: str, addressed: bool = False) -> None:
        if c.collapsed or c.asleep:
            return
        if (c.activity or {}).get("sleep") and reason not in ("hungry", "result") and not addressed:
            return  # asleep for the night: only hunger, waking up, or being spoken to directly rouses you
        prio = {"heard": 0, "hungry": 1, "result": 2, "woke": 2, "met": 3, "idle": 4}
        if c.wake_reason is None or prio.get(reason, 5) < prio.get(c.wake_reason, 5):
            c.wake_reason = reason

    def remember(self, c: Creature, text: str, importance: int = 1) -> None:
        self.memory_sink(c, text, importance)

    def recipes_in_words(self, line: str) -> list:
        return self.world.catalog.recipes_in_words(line)

    def take_heard(self, c: Creature) -> list[str]:
        """What a creature heard since its last turn: words (the last six), then sounds (perception shows them apart)."""
        lines = self.heard.pop(c.id, [])
        return lines[-6:] + list(self.sounds.pop(c.id, {}).values())

    # ------------------------------------------------------------------
    def tick(self) -> list:
        w = self.world
        w.tick += 1
        t = w.tick
        for c in list(w.creatures.values()):
            if c.collapsed:
                if t >= c.collapsed_until:
                    self._respawn(c)
                continue
            if c.asleep:  # its mind is away (brain node offline): the body waits in stasis
                continue
            self._needs(c, t)
            if c.collapsed:
                continue
            was_bedtime_walk = (c.activity or {}).get("sleep_after")
            res = step_activity(w, c)
            if res is not None and was_bedtime_walk and c.activity is None and w.clock()["phase"] == "night":
                self.remember(c, res.message, 1)
                self._start_sleep(c, self.exposure(c) is None)
                res = None
            if res is not None:
                if self.on_result:
                    self.on_result(c, res)
                else:
                    self.remember(c, res.message, 1)
                self.wake(c, "result")
            self._notice_others(c, t)
            if t % 3 == 0 and not c.asleep:
                note_spots(w, c, t)
            self._maybe_sleep(c)
            idle_after = IDLE_TICKS * (2 if (c.persona or {}).get("initiative") == "reactive" else 1)
            if c.activity is None and not c.thinking and c.wake_reason is None and t - c.last_think_tick >= idle_after:
                self.wake(c, "idle")
        self._process_events()
        if t % 10 == 0:
            self._regrow(t)
        if t % ANIMAL_EVERY == 0:
            self._animals()
        if t % 20 == 0:
            self._wake_sleepers()
        if t % 10 == 5:
            self._separate()
        if t % 60 == 0 or not hasattr(self.world, "landmarks"):
            self._landmarks()
        if t % 600 == 0:
            from .terrain import spawn_animals
            spawn_animals(self.world, self.world.rng, limit=2)
        self._terminals(t)
        for system in SYSTEMS:  # the packs' world behaviour, in registration order; one that fails skips this tick
            if t % system.every == 0:
                call_safely(f"system '{system.name}'", system.fn, self, t)
        new = self.take_events()
        if len(w.events) > 5000:
            del w.events[:4000]
            self._event_cursor = max(0, self._event_cursor - 4000)
            self._returned_cursor = max(0, self._returned_cursor - 4000)
        return new

    def take_events(self) -> list:
        """The events since the last tick (or call): what the server logs and shows next."""
        new = self.world.events[self._returned_cursor:]
        self._returned_cursor = len(self.world.events)
        return new

    # ------------------------------------------------------------------
    def _needs(self, c: Creature, t: int) -> None:
        if t % SATIETY_EVERY == 0:
            c.satiety = max(0.0, c.satiety - 1)
        if t % ENERGY_EVERY == 0 and not (c.activity or {}).get("rest"):
            c.energy = max(0.0, c.energy - 1)
            exposed = self.exposure(c)
            if exposed:  # cold nights and rain wear you down unless you're by a fire or under shelter
                c.energy = max(0.0, c.energy - 1)
        if c.satiety <= 0 and t % STARVE_EVERY == 0:
            c.health = max(0.0, c.health - 1)
        elif c.satiety > 50 and c.health < 100 and t % 8 == 0:
            c.health = min(100.0, c.health + 1)
        if c.satiety > 50:
            self.hunger_alert.pop(c.id, None)
        for level in (40, 20, 5):
            if c.satiety <= level and self.hunger_alert.get(c.id, 101) > level:
                self.hunger_alert[c.id] = level
                self.wake(c, "hungry")
                break
        if c.satiety < 10 and not c.collapsed:
            self._reflex_eat(c)
        if c.health <= 0:
            self._collapse(c, t)

    def maybe_inspire(self, c: Creature) -> None:
        p = c.persona or {}
        chance = INSPIRATION_CHANCE.get(p.get("drive"), 0.02)
        chance *= {"novelty": 1.6, "routine": 0.6}.get(p.get("novelty"), 1.0)
        if self.inspiration and self.world.rng.random() < chance:
            self._inspire(c)

    def _inspire(self, c: Creature) -> None:
        """A vague hunch about an undiscovered recipe that uses something the creature carries. Never the full recipe."""
        w = self.world
        held = {i for i, n in c.inventory.items() if n > 0}
        if not held:
            return
        options = [r for r in w.catalog.recipes
                   if r.output not in c.known_recipes and (set(r.inputs) | set(r.tools)) & held]
        if not options:
            return
        r = w.rng.choice(options)
        parts = sorted((set(r.inputs) | set(r.tools)) & held)
        names = [w.catalog.name(i) for i in parts]
        if len(names) >= 2:
            hunch = f"Looking at your {names[0]} and {names[1]}, you get a hunch that they belong together somehow."
        elif r.station:
            hunch = f"You wonder what would happen to your {names[0]} near a {w.catalog.name(r.station)}."
        else:
            hunch = f"Turning your {names[0]} over in your hands, you sense it could be part of something more."
        self.remember(c, hunch, 2)
        c.stats["inspirations"] += 1

    def _maybe_sleep(self, c: Creature) -> None:
        """At night a tired creature with nothing to do lies down and sleeps until dawn or until it's rested."""
        w = self.world
        bedtime = SLEEP_BELOW.get((c.persona or {}).get("initiative"), 85)
        if c.activity or c.thinking or c.energy >= bedtime or w.clock()["phase"] != "night":
            return
        from .actions import station_near
        snug = station_near(w, c, "bed") or self.exposure(c) is None
        if not snug:  # head for the warmth of a fire or a shelter in sight, then sleep there
            from .actions import _adjacent_goals, bfs_path, occupied_tiles
            from .perception import visible_objects
            warm = next((o for o, d, _ in visible_objects(w, c)
                         if (o.kind == "campfire" and o.data.get("lit")) or o.kind == "bed"
                         or (o.kind == "creation" and {"shelter", "light"} & set(o.data.get("effects", ())))), None)
            if warm:
                goals = {(x, y) for x in range(warm.x - 2, warm.x + 3) for y in range(warm.y - 2, warm.y + 3)
                         if w.walkable(x, y)} - occupied_tiles(w, c.id)
                roof = perception.roof_over(w, warm.x, warm.y)
                if roof:  # a bed inside a building: lie down inside it, not against its outer wall
                    goals = {g for g in goals if perception.roof_over(w, *g) == roof}
                path = bfs_path(w, (c.x, c.y), goals, avoid=occupied_tiles(w, c.id)) if goals else None
                if path:
                    c.activity = {"type": "walk", "path": path, "label": f"heading to the {warm.name} to sleep",
                                  "result": f"You settle down by the {warm.name}.", "sleep_after": True}
                    c.wake_reason = None
                    return
        self._start_sleep(c, snug)

    def _start_sleep(self, c: Creature, snug: bool) -> None:
        from .actions import station_near
        w = self.world
        c.activity = {"type": "busy", "ticks": 10_000, "label": "sleeping" + ("" if snug else " out in the cold"),
                      "result": "You wake up.", "rest": True, "bed": station_near(w, c, "bed"), "sleep": True}
        c.wake_reason = None
        c.stats["nights_slept"] += 1

    def _wake_sleepers(self) -> None:
        w = self.world
        day = w.clock()["phase"] in ("dawn", "day")
        for c in w.creatures.values():
            act = c.activity or {}
            if act.get("sleep") and day:  # sleep through the night; dawn wakes everyone
                c.activity = None
                self.remember(c, "You wake up rested." if c.energy >= 60 else "You wake up, still tired.", 1)
                self.wake(c, "woke")

    def _reflex_eat(self, c: Creature) -> None:
        """A survival reflex that needs no thought: a starving body eats what it carries, or berries within reach, or
        other wild food within reach (a mushroom patch, wild herbs)."""
        w = self.world
        foods = sorted((i for i, n in c.inventory.items() if n > 0 and w.catalog.items[i].food > 0),
                       key=lambda i: -w.catalog.items[i].food)
        eaten: Counter = Counter()
        for i in foods:
            while c.inventory.get(i, 0) > 0 and c.satiety < 60:
                c.inventory[i] -= 1
                c.satiety = min(100.0, c.satiety + w.catalog.items[i].food)
                eaten[i] += 1
            if c.inventory.get(i, 0) <= 0:
                c.inventory.pop(i, None)
        if c.satiety < 60:  # nothing carried: strip berries from a bush within arm's reach
            from .perception import dist
            for o in list(w.objects.values()):
                if o.kind == "bush" and dist(c.x, c.y, o.x, o.y) <= 1:
                    while o.data.get("berries", 0) > 0 and c.satiety < 60:
                        o.data["berries"] -= 1
                        c.satiety = min(100.0, c.satiety + w.catalog.items["berries"].food)
                        eaten["berries"] += 1
                    if o.data.get("berries", 0) <= 0:
                        w.change_kind(o, "bush_empty")
                        o.data["regrow_at"] = w.tick + 400
                    if c.satiety >= 60:
                        break
        if c.satiety < 60:  # then whatever grows within reach and is food: a mushroom patch, wild herbs
            self._reflex_forage(c, eaten)
        if eaten:
            what = ", ".join(f"{n} {w.catalog.name(i)}" for i, n in eaten.items())
            w.emit("eat", c.id, c.x, c.y, f"{c.name}, starving, wolfed down {what}.")
            self.remember(c, f"Starving, you wolfed down {what} without thinking. Eat before it gets that bad.", 3)

    def _reflex_forage(self, c: Creature, eaten: Counter) -> None:
        """Pick from food-giving kinds (objects.json yields) within arm's reach, a use at a time, eating as it goes."""
        from .actions import _gather_yields, _spent
        from .perception import visible_objects
        from .registry import YIELDS
        w = self.world
        items = w.catalog.items
        for o, d, _ in visible_objects(w, c, 1):
            if d > 1 or o.kind not in YIELDS or not any(i in items and items[i].food > 0 for i in YIELDS[o.kind]["items"]):
                continue
            while c.satiety < 60 and o.kind in YIELDS and not _spent(o):
                got: Counter = Counter()
                done = _gather_yields(w, c, o, got)
                for i, n in got.items():
                    food = items[i].food if i in items else 0
                    while n > 0 and food > 0 and c.satiety < 60:
                        n -= 1
                        c.satiety = min(100.0, c.satiety + food)
                        eaten[i] += 1
                    if n > 0:
                        c.inventory[i] += n  # what it couldn't eat, or isn't food, it keeps
                if done is not False:  # used up, or it needs a tool
                    break
            if c.satiety >= 60:
                return

    def _collapse(self, c: Creature, t: int) -> None:
        w = self.world
        if c.inventory:
            w.drop_items(c.x, c.y, Counter(c.inventory))
            c.inventory.clear()
        c.activity = None
        c.collapsed_until = t + COLLAPSE_TICKS
        c.stats["collapses"] += 1
        w.emit("collapse", c.id, c.x, c.y, f"{c.name} collapsed from hunger, dropping everything.")

    def _respawn(self, c: Creature) -> None:
        w = self.world
        c.collapsed_until = 0
        c.x, c.y = w.spawn_point()
        c.satiety, c.health, c.energy = 50.0, 60.0, 70.0
        self.hunger_alert.pop(c.id, None)
        self.remember(c, "You collapsed from hunger and lost everything you carried. You wake up in the meadow, weak and empty-handed. Eat more often.", 3)
        self.wake(c, "woke")

    def _notice_others(self, c: Creature, t: int) -> None:
        for other, d, dirn in visible_creatures(self.world, c):
            last = c.seen.get(other.id)
            if last is None or t - last > MET_FORGET:
                self.wake(c, "met")
            c.seen[other.id] = t
            c.seen_pos[other.name.lower()] = (other.x, other.y, t)

    def _process_events(self) -> None:
        w = self.world
        for ev in w.events[self._event_cursor:]:
            if ev.kind == "say":
                if ev.actor:
                    self.recent_says[ev.actor].append(ev.tick)
                speaker = w.creatures.get(ev.actor) if ev.actor else None
                speaker_name = ev.data.get("speaker") or (speaker.name if speaker else "Someone")
                for h in hearers(w, ev.x, ev.y):
                    if h.id == ev.actor:
                        continue
                    if ev.data.get("to") == h.id:
                        line = f'{speaker_name} says to you: "{ev.data.get("line", "")}"'
                        imp = 3
                    elif ev.data.get("to_name"):
                        line = f'{speaker_name} says to {ev.data["to_name"]}: "{ev.data.get("line", "")}"'
                        imp = 2
                    else:
                        line = f'{speaker_name} says: "{ev.data.get("line", "")}"'
                        imp = 2
                    self.heard[h.id].append(line)
                    self.remember(h, line, imp)
                    for r in self.recipes_in_words(ev.data.get("line", "")):
                        if r.output not in h.known_recipes:
                            h.known_recipes.add(r.output)
                            h.stats["learned_by_listening"] += 1
                            w.emit("learn", h.id, h.x, h.y, f"{h.name} learned to make {w.catalog.name(r.output)} by listening to {speaker_name}.",
                                   teacher=ev.actor, how="listening", item=r.output)
                            self.remember(h, f"From {speaker_name}'s words you understand how to make {w.catalog.name(r.output)}: "
                                             f"{w.catalog.describe_recipe(r)}.", 3)
                    said = self.recent_says[h.id]
                    while said and said[0] < w.tick - CHAT_WINDOW:
                        said.popleft()
                    if len(said) < CHAT_LIMIT or ev.data.get("to") == h.id and len(said) < CHAT_LIMIT + 2:
                        self.wake(h, "heard", addressed=ev.data.get("to") == h.id)
            elif ev.kind == "give":
                rec = w.creatures.get(ev.data.get("to"))
                if rec:
                    self.remember(rec, f"{ev.data.get('giver')} gave you {ev.data.get('n')} {w.catalog.name(ev.data.get('item', ''))}.", 3)
                    self.wake(rec, "heard")
            elif ev.kind in ("craft", "discover", "invent"):
                item = ev.data.get("item")
                r = w.catalog.recipe_for(item) if item else None
                for h in hearers(w, ev.x, ev.y, WITNESS_RADIUS):
                    if h.id == ev.actor:
                        continue
                    maker = w.creatures.get(ev.actor)
                    how = f" ({w.catalog.describe_recipe(r)})" if r else ""
                    learned = ""
                    if r and item not in h.known_recipes:
                        h.known_recipes.add(item)  # seeing it done up close is how you learn
                        h.stats["learned_by_watching"] += 1
                        w.emit("learn", h.id, h.x, h.y, f"{h.name} learned to make {w.catalog.name(item)} by watching {maker.name if maker else 'someone'}.",
                               teacher=ev.actor, how="watching", item=item)
                        learned = " Now you know how to make it too."
                    self.remember(h, f"You watched {maker.name if maker else 'someone'} make {w.catalog.name(item)}{how}.{learned}", 3 if learned else 2)
            elif ev.kind in ("place", "store", "take", "tend"):
                for h in hearers(w, ev.x, ev.y, WITNESS_RADIUS):
                    if h.id != ev.actor:
                        self.remember(h, ev.text, 1)
            elif ev.kind == "sound":
                self._hear_sound(ev)
        self._event_cursor = len(w.events)

    def _hear_sound(self, ev) -> None:
        """A sound (World.sound) reaches awake creatures in range, not its source or makers. Sleepers only hear a loud one, and
        it wakes them. It isn't a memory and doesn't make anyone think; it's in their next perception."""
        w = self.world
        loud = bool(ev.data.get("loud"))
        makers = ev.data.get("makers") or ()
        for h in hearers(w, ev.x, ev.y, ev.data.get("radius", 8)):
            if h.id == ev.data.get("source") or h.id in makers or h.asleep:  # asleep: its mind is away
                continue
            sleeping = bool((h.activity or {}).get("sleep"))
            if sleeping and not loud:
                continue
            line = sound_line(ev.text, dist(h.x, h.y, ev.x, ev.y), direction(ev.x - h.x, ev.y - h.y))
            heard = self.sounds[h.id]
            key = ev.data.get("sound") or ev.text
            heard.pop(key, None)  # the latest of each kind of sound
            heard[key] = line
            while len(heard) > SOUND_LINES:
                del heard[next(iter(heard))]
            if sleeping:
                h.activity = None
                self.remember(h, f"{line} It wakes you.", 2)
                self.wake(h, "woke")

    def _regrow(self, t: int) -> None:
        w = self.world
        raining = wet(w, drizzle=True)
        for o in list(w.objects.values()):
            if raining:  # rain makes everything grow faster
                for key in ("grow_at", "regrow_at"):
                    if o.data.get(key):
                        o.data[key] -= 10
            ra = o.data.get("regrow_at")
            if ra and t >= ra:
                if o.data.get("regrows"):  # a kind with yields from data, used up and now grown back
                    w.change_kind(o, o.data.pop("regrows"))
                    o.data.pop("uses", None)
                elif o.kind == "stump":
                    w.change_kind(o, "tree")
                    o.data["wood"] = 6
                elif o.kind == "bush_empty":
                    w.change_kind(o, "bush")
                    o.data["berries"] = 6
                o.data.pop("regrow_at", None)
            ga = o.data.get("grow_at")
            if ga and t >= ga:
                if o.kind == "crop" and o.data.get("stage", 0) < 2:
                    o.data["stage"] = o.data.get("stage", 0) + 1
                    crop = o.data.get("crop", "wheat")
                    o.data["label"] = f"growing {crop}" if o.data["stage"] == 1 else f"ripe {crop}"
                    o.data["grow_at"] = t + 300 if o.data["stage"] < 2 else None
                    w.changed_objects.add(o.id)
                elif o.kind == "sapling":
                    w.change_kind(o, "bush")
                    o.data.update(berries=6, label=None, grow_at=None)
            if o.kind == "campfire" and o.data.get("lit") and t >= o.data.get("lit_until", 0):
                o.data["lit"] = False
                w.changed_objects.add(o.id)
                w.emit("fire_out", None, o.x, o.y, "A campfire burned out.")

    def _landmarks(self) -> None:
        """Name the places that matter: clusters of things creatures built become someone's camp."""
        from .perception import direction
        w = self.world
        built = [o for o in w.objects.values()
                 if o.kind in ("campfire", "workbench", "furnace", "bed", "creation", "chest", "millstone", "sign", "wall")]
        built.sort(key=lambda o: o.id)  # oldest first, so a camp keeps its founder's name
        camps: list[dict] = []
        for o in built:
            home = next((cp for cp in camps if max(abs(cp["x"] - o.x), abs(cp["y"] - o.y)) <= 6), None)
            if home:
                home["size"] += 1
            else:
                founder = o.data.get("builder") or "someone"
                camps.append({"name": f"{founder}'s camp", "x": o.x, "y": o.y, "kind": "camp", "size": 1})
        names: dict[str, int] = {}
        for cp in camps:  # two camps by the same founder
            names[cp["name"]] = names.get(cp["name"], 0) + 1
            if names[cp["name"]] > 1:
                cp["name"] = cp["name"].replace("'s camp", f"'s {('second', 'third', 'fourth')[min(names[cp['name']] - 2, 2)]} camp")
        cx, cy = w.center
        fixed = [{"name": f"the {direction(o.x - cx, o.y - cy)} terminal", "x": o.x, "y": o.y, "kind": "terminal", "size": 1}
                 for o in w.objects.values() if o.kind == "terminal" and o.data.get("builder") is None
                 and (w.region_at(o.x, o.y) or w.regions[0]).name == "surface"]
        lake = self._lake()
        if lake:
            fixed.append({"name": "the lake", "x": lake[0], "y": lake[1], "kind": "lake", "size": 1})
        fixed.append({"name": "the meadow", "x": cx, "y": cy, "kind": "meadow", "size": 1})
        for source in LANDMARK_SOURCES:  # what packs know: each a list of {"name", "x", "y", "kind"}
            fixed += [{"size": 1, **lm} for lm in call_safely("landmark source", source, w, default=None) or ()]
        w.landmarks = camps + fixed

    def _lake(self) -> tuple[int, int] | None:
        """The middle of all deep water, worked out again only when the land changes (World.set_tile)."""
        w = self.world
        key = (id(w.tiles), w.tiles_version)
        if self._lake_cache is None or self._lake_cache[0] != key:
            y0, y1 = w.region_bounds()[1::2]  # the surface's rows: deep water is no lake
            water = [(x, y) for y in range(y0, y1) for x, t in enumerate(w.tiles[y]) if t == "W"]
            at = (sum(x for x, _ in water) // len(water), sum(y for _, y in water) // len(water)) if water else None
            self._lake_cache = (key, at)
        return self._lake_cache[1]

    def exposure(self, c: Creature) -> str | None:
        """What the weather is doing to you right now, if you're out in it."""
        from .actions import station_near
        from .perception import near_lit_fire
        w = self.world
        if not w.under_sky(c.x, c.y):
            return None
        night = w.clock()["phase"] == "night"
        rain = wet(w)
        if not (night or rain):
            return None
        if near_lit_fire(w, c.x, c.y, 3) or station_near(w, c, "bed") or perception.roof_over(w, c.x, c.y):
            return None
        return "rain" if rain else "cold"

    def _separate(self) -> None:
        """Nobody shares a tile: an idle creature standing on someone else's spot shuffles to a free neighbor."""
        w = self.world
        seen: set[tuple[int, int]] = set()
        for c in w.creatures.values():
            if c.collapsed:
                continue
            spot = (c.x, c.y)
            if spot not in seen:
                seen.add(spot)
                continue
            if c.activity:
                continue
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1), (1, -1), (-1, 1)):
                nx, ny = c.x + dx, c.y + dy
                if w.walkable(nx, ny) and not w.occupied(nx, ny) and (nx, ny) not in seen:
                    c.x, c.y = nx, ny
                    seen.add((nx, ny))
                    break

    def _animals(self) -> None:
        """Needs-driven animal behaviour (runs every 4 ticks): wary, follow, rest, home or graze."""
        w = self.world
        day = w.clock()["day"]
        night = w.clock()["phase"] == "night"
        animals = [o for o in w.objects.values() if o.kind in ANIMALS]
        counts = Counter(o.kind for o in animals)
        for o in animals:
            d = o.data
            d.setdefault("hunger", 20)
            owner = next((c for c in w.creatures.values() if c.name == d.get("tamed_by")), None) if d.get("tamed_by") else None
            home = d.get("home")
            spec = KINDS.get(o.kind, {})  # shy kinds (wild game) say so in their data: they flee sooner and farther
            wary, flee = spec.get("wary", WARY_RANGE), spec.get("flee", FLEE_STEPS)
            near = [c for c in w.creatures.values() if not c.collapsed and c.name not in d.get("fed_by", ())
                    and max(abs(c.x - o.x), abs(c.y - o.y)) < wary and w.same_region((c.x, c.y), (o.x, o.y))] if not owner and not d.get("tamed_by") else []
            following = bool(owner and max(abs(owner.x - o.x), abs(owner.y - o.y)) <= 6
                             and any(owner.inventory.get(f, 0) > 0 for f in ANIMAL_LURE))
            if near:
                d["state"] = "wary"
                c = min(near, key=lambda c: max(abs(c.x - o.x), abs(c.y - o.y)))
                steps = flee + 1 if max(abs(c.x - o.x), abs(c.y - o.y)) <= 1 else flee
                for _ in range(steps):
                    self._animal_step(o, c.x, c.y, away=True)
            elif following:
                d["state"] = "follow"
                d["following"] = True
                gap = max(abs(owner.x - o.x), abs(owner.y - o.y))
                for _ in range(2 if gap > 3 else 1 if gap > 2 else 0):  # trail 1-2 tiles behind, hurrying if it falls back
                    self._animal_step(o, owner.x, owner.y)
            else:
                if d.pop("following", False) and home and max(abs(o.x - home[0]), abs(o.y - home[1])) > 6:
                    d["home"] = home = [o.x, o.y]
                if night:
                    d["state"] = "rest"
                    mates = [m for m in animals if m is not o and m.kind == o.kind and max(abs(m.x - o.x), abs(m.y - o.y)) <= 5
                             and w.same_region((m.x, m.y), (o.x, o.y))]
                    if mates and w.rng.random() < 0.3:
                        m = min(mates, key=lambda m: max(abs(m.x - o.x), abs(m.y - o.y)))
                        if max(abs(m.x - o.x), abs(m.y - o.y)) > 1:
                            self._animal_step(o, m.x, m.y)
                elif home and max(abs(o.x - home[0]), abs(o.y - home[1])) > 3:
                    d["state"] = "home"
                    self._animal_step(o, home[0], home[1])
                else:
                    d["state"] = "graze"
                    if w.tile(o.x, o.y) in GRAZING:
                        d["hunger"] = max(0, d["hunger"] - ANIMAL_GRAZE_FILL)
                        if w.rng.random() < 0.3:
                            self._wander(o, home)
                    else:  # bare ground: head for the nearest grass in sight, or wander until some comes into view
                        grass = self._nearest_grass(o, home)
                        if not (grass and self._animal_step(o, *grass)) and w.rng.random() < 0.3:
                            self._wander(o, home)
            if d["state"] != "rest" and w.rng.random() < ANIMAL_HUNGER_CHANCE:  # asleep at night: no hunger
                d["hunger"] = min(100, d["hunger"] + 1)
            if d["hunger"] >= WELL_FED and d.get("ready_at", 0) > w.tick:
                d["ready_at"] += ANIMAL_EVERY  # the production timer pauses while hungry
            self._breed(o, animals, counts, day)

    def _free_for_animal(self, x: int, y: int, home) -> bool:
        w = self.world
        return ((x, y) not in w.grid and w.walkable(x, y) and w.tile(x, y) not in "wW" and not w.occupied(x, y)
                and not (home and max(abs(x - home[0]), abs(y - home[1])) > HOME_RANGE))

    def _wander(self, o, home) -> None:
        """A grazing step to a free neighbouring tile of land, grass or forest floor if there is one."""
        w = self.world
        free = [(o.x + dx, o.y + dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                if self._free_for_animal(o.x + dx, o.y + dy, home)]
        grassy = [p for p in free if w.tile(*p) in GRAZING]
        if free:
            w.move_object(o, *w.rng.choice(grassy or free))

    def _nearest_grass(self, o, home) -> tuple[int, int] | None:
        """The closest free grass or forest tile the animal can see (within its home range, if it has a home)."""
        w = self.world
        best = None
        for y in range(o.y - DAY_SIGHT, o.y + DAY_SIGHT + 1):
            for x in range(o.x - DAY_SIGHT, o.x + DAY_SIGHT + 1):
                if w.tile(x, y) in GRAZING and self._free_for_animal(x, y, home):
                    key = (max(abs(x - o.x), abs(y - o.y)), (x - o.x) ** 2 + (y - o.y) ** 2, y, x)
                    if best is None or key < best[0]:
                        best = (key, (x, y))
        return best[1] if best else None

    def _animal_step(self, o, tx: int, ty: int, away: bool = False) -> bool:
        """Move one tile toward (or away from) a target, taking the best free tile; False if boxed in."""
        w = self.world
        def score(p):
            d = (p[0] - tx) ** 2 + (p[1] - ty) ** 2
            return -d if away else d
        here = score((o.x, o.y))
        opts = [(o.x + dx, o.y + dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))]
        w.rng.shuffle(opts)
        for p in sorted(opts, key=score):
            if score(p) >= here:
                break
            if not w.occupied(*p) and w.move_object(o, *p):
                return True
        return False

    def _breed(self, o, animals, counts, day: int) -> None:
        w, d = self.world, o.data
        if not d.get("tamed_by") or d["hunger"] >= WELL_FED or d.get("bred_day") == day or counts[o.kind] >= ANIMAL_CAP:
            return
        mate = next((m for m in animals if m is not o and m.kind == o.kind and m.data.get("tamed_by")
                     and m.data.get("hunger", 20) < WELL_FED and m.data.get("bred_day") != day
                     and max(abs(m.x - o.x), abs(m.y - o.y)) <= 2 and w.same_region((m.x, m.y), (o.x, o.y))), None)
        if not mate or w.rng.random() > ANIMAL_BREED_CHANCE:
            return
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1), (1, -1), (-1, 1)):
            x, y = o.x + dx, o.y + dy
            if w.walkable(x, y) and (x, y) not in w.grid and w.tile(x, y) not in "wW" and not w.occupied(x, y):
                owner = d["tamed_by"]
                w.add_object(o.kind, x, y, tamed_by=owner, home=list(d.get("home") or [o.x, o.y]), label=f"{owner}'s {o.kind}",
                             ready_at=w.tick + 300, hunger=20, fed=2, bred_day=day)
                d["bred_day"] = mate.data["bred_day"] = day
                counts[o.kind] += 1
                return

    def _terminals(self, t: int) -> None:
        if not self.terminal_runner:
            return
        w = self.world
        for oid in list(w.terminals):  # World keeps the index as terminals come and go
            o = w.objects.get(oid)
            if o and o.kind == "terminal" and o.data.get("code") and t >= o.data.get("next_run", 0):
                o.data["next_run"] = t + TERMINAL_EVERY
                self.terminal_runner(w, o)
