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
ENERGY_EVERY = 40
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
        """Recipes fully spelled out in a spoken line: the product and every ingredient are named."""
        text = " " + line.lower().replace("-", " ") + " "
        def named(item_id: str) -> bool:
            it = self.world.catalog.items.get(item_id)
            names = [it.name, *it.aliases] if it else [item_id.replace("_", " ")]
            return any(f" {n.lower()}" in text for n in names if len(n) > 2)
        out = []
        for r in self.world.catalog.recipes:
            if r.known_at_start:
                continue
            if named(r.output) and all(named(i) for i in r.inputs):
                out.append(r)
        return out

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
        if t % 10 == 5:
            self._separate()
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
                        learned = " Now you know how to make it too."
                    self.remember(h, f"You watched {maker.name if maker else 'someone'} make {w.catalog.name(item)}{how}.{learned}", 3 if learned else 2)
            elif ev.kind == "place":
                for h in hearers(w, ev.x, ev.y, WITNESS_RADIUS):
                    if h.id != ev.actor:
                        self.remember(h, ev.text, 1)
        self._event_cursor = len(w.events)

    def _regrow(self, t: int) -> None:
        w = self.world
        for o in list(w.objects.values()):
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
