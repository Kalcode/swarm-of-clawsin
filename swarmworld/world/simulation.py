"""The world clock: needs, activities, regrowth, fire, terminals, and deciding who should wake up and think."""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from typing import Callable

from .actions import ActionResult, step_activity
from .events import hearers
from .model import ANIMALS, Creature, World
from .perception import visible_creatures

INSPIRATION_CHANCE = {"curious": 0.12, "tinkerer": 0.12, "builder": 0.07, "teacher": 0.05}  # per thought
SATIETY_EVERY = 24  # one point every 12 s: about 20 minutes from full to starving
ENERGY_EVERY = 30  # about 40 energy a day: a creature needs a good rest roughly once a day
STARVE_EVERY = 4
IDLE_TICKS = 30
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
        self._event_cursor = len(world.events)
        self.on_result: Callable[[Creature, ActionResult], None] | None = None
        self.inspiration = True  # occasional vague hunches for curious minds; off = purely unassisted

    # ------------------------------------------------------------------
    def wake(self, c: Creature, reason: str) -> None:
        if c.collapsed or c.asleep:
            return
        prio = {"heard": 0, "hungry": 1, "result": 2, "woke": 2, "met": 3, "idle": 4}
        if c.wake_reason is None or prio.get(reason, 5) < prio.get(c.wake_reason, 5):
            c.wake_reason = reason

    def remember(self, c: Creature, text: str, importance: int = 1) -> None:
        self.memory_sink(c, text, importance)

    def recipes_in_words(self, line: str) -> list:
        return self.world.catalog.recipes_in_words(line)

    def take_heard(self, c: Creature) -> list[str]:
        lines = self.heard.pop(c.id, [])
        return lines[-6:]

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
            res = step_activity(w, c)
            if res is not None:
                if self.on_result:
                    self.on_result(c, res)
                else:
                    self.remember(c, res.message, 1)
                self.wake(c, "result")
            self._notice_others(c, t)
            if c.activity is None and not c.thinking and c.wake_reason is None and t - c.last_think_tick >= IDLE_TICKS:
                self.wake(c, "idle")
        self._process_events()
        if t % 10 == 0:
            self._regrow(t)
        if t % 4 == 0:
            self._animals()
        if t % 50 == 0:
            self._weather(t)
        if t % 10 == 5:
            self._separate()
        if t % 60 == 0 or not hasattr(self.world, "landmarks"):
            self._landmarks()
        if t % 600 == 0:
            from .terrain import spawn_animals
            spawn_animals(self.world, self.world.rng, limit=2)
        self._terminals(t)
        new = w.events[self._event_cursor_out:] if hasattr(self, "_event_cursor_out") else list(w.events)
        self._event_cursor_out = len(w.events)
        if len(w.events) > 5000:
            del w.events[:4000]
            self._event_cursor = max(0, self._event_cursor - 4000)
            self._event_cursor_out = max(0, self._event_cursor_out - 4000)
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
        if self.inspiration and self.world.rng.random() < INSPIRATION_CHANCE.get((c.persona or {}).get("drive"), 0.02):
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

    def _reflex_eat(self, c: Creature) -> None:
        """A survival reflex that needs no thought: a starving body eats whatever food it carries."""
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
        if eaten:
            what = ", ".join(f"{n} {w.catalog.name(i)}" for i, n in eaten.items())
            w.emit("eat", c.id, c.x, c.y, f"{c.name}, starving, wolfed down {what}.")
            self.remember(c, f"Starving, you wolfed down {what} without thinking. Eat before it gets that bad.", 3)

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
                        self.wake(h, "heard")
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
            elif ev.kind == "place":
                for h in hearers(w, ev.x, ev.y, WITNESS_RADIUS):
                    if h.id != ev.actor:
                        self.remember(h, ev.text, 1)
        self._event_cursor = len(w.events)

    def _regrow(self, t: int) -> None:
        w = self.world
        raining = getattr(w, "weather", "clear") == "rain"
        for o in list(w.objects.values()):
            if raining:  # rain makes everything grow faster
                for key in ("grow_at", "regrow_at"):
                    if o.data.get(key):
                        o.data[key] -= 10
            ra = o.data.get("regrow_at")
            if ra and t >= ra:
                if o.kind == "stump":
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
                 for o in w.objects.values() if o.kind == "terminal" and o.data.get("builder") is None]
        water = [(x, y) for y in range(w.height) for x in range(w.width) if w.tile(x, y) == "W"]
        if water:
            lx = sum(x for x, _ in water) // len(water)
            ly = sum(y for _, y in water) // len(water)
            fixed.append({"name": "the lake", "x": lx, "y": ly, "kind": "lake", "size": 1})
        fixed.append({"name": "the meadow", "x": cx, "y": cy, "kind": "meadow", "size": 1})
        w.landmarks = camps + fixed

    def _weather(self, t: int) -> None:
        w = self.world
        if getattr(w, "weather", "clear") == "rain":
            if t >= getattr(w, "weather_until", 0):
                w.weather = "clear"
                w.emit("weather", None, *w.center, "The rain stops and the clouds drift apart.")
        elif w.rng.random() < 0.05:
            w.weather = "rain"
            w.weather_until = t + w.rng.randint(200, 450)
            w.emit("weather", None, *w.center, "Clouds gather, and rain begins to fall.")

    def exposure(self, c: Creature) -> str | None:
        """What the weather is doing to you right now, if you're out in it."""
        from .actions import station_near
        from .perception import near_lit_fire
        w = self.world
        night = w.clock()["phase"] == "night"
        rain = getattr(w, "weather", "clear") == "rain"
        if not (night or rain):
            return None
        if near_lit_fire(w, c.x, c.y, 3) or station_near(w, c, "bed"):
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
        w = self.world
        for o in list(w.objects.values()):
            if o.kind not in ANIMALS or w.rng.random() > 0.35:
                continue
            dx, dy = w.rng.choice(((1, 0), (-1, 0), (0, 1), (0, -1)))
            nx, ny = o.x + dx, o.y + dy
            home = o.data.get("home")
            if home and max(abs(nx - home[0]), abs(ny - home[1])) > 3:
                continue
            if not w.occupied(nx, ny):
                w.move_object(o, nx, ny)

    def _terminals(self, t: int) -> None:
        if not self.terminal_runner:
            return
        for o in list(self.world.objects.values()):
            if o.kind == "terminal" and o.data.get("code") and t >= o.data.get("next_run", 0):
                o.data["next_run"] = t + TERMINAL_EVERY
                self.terminal_runner(self.world, o)
