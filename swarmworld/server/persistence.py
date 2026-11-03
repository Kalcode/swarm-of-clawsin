"""Save and restore the whole world, including every creature's memory, so a world can live for days."""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING

from ..mind.memory import Entry, Memory
from ..mind.recall import RecallIndex
from ..world.catalog import Catalog
from ..world.model import Creature, World, WorldObject
from .wishes import Wishes

if TYPE_CHECKING:
    from .state import ServerState

VERSION = 1


def _creature_dict(c: Creature) -> dict:
    return {
        "id": c.id, "name": c.name, "x": c.x, "y": c.y, "model": c.model, "color": c.color, "persona": c.persona,
        "inventory": dict(c.inventory), "satiety": c.satiety, "energy": c.energy, "health": c.health,
        "collapsed_until": c.collapsed_until, "known_recipes": sorted(c.known_recipes), "stats": dict(c.stats),
        "spots": {k: list(v) for k, v in c.spots.items()},
        "minds": c.minds, "stats_base": dict(c.stats_base), "harness": dict(c.harness),
        "landmarks_seen": sorted(c.landmarks_seen), "ext": c.ext,
    }


def snapshot(st: "ServerState") -> dict:
    w = st.world
    return {
        "version": VERSION,
        "world": {
            "width": w.width, "height": w.height, "tiles": ["".join(r) for r in w.tiles], "tick": w.tick,
            "weather": getattr(w, "weather", "clear"), "weather_until": getattr(w, "weather_until", 0),
            "next_id": w._next_id, "discoveries": w.discoveries,
            "objects": [{"id": o.id, "kind": o.kind, "x": o.x, "y": o.y, "data": o.data} for o in w.objects.values()],
            "ground": [{"x": x, "y": y, "items": dict(p)} for (x, y), p in w.ground.items()],
            "creatures": [_creature_dict(c) for c in w.creatures.values()], "ext": w.ext,
        },
        "memories": {
            cid: {"entries": [[e.tick, e.text, e.importance] for e in m.entries], "summary": m.summary, "goal": m.goal,
                  "plan": m.plan, "plan_step": m.plan_step, "thought_back": m.thought_back,
                  "people": m.people, "thinks_since_reflect": m.thinks_since_reflect,
                  "entries_since_reflect": m.entries_since_reflect}
            for cid, m in st.memories.items()
        },
        "recall": st.recall.to_dict(),
        "owner": st.owner,
        "model_colors": st.model_colors,
        "chronicle": st.chronicle,
        "sky_words": st.sky_words,
        "relations": {k: dict(v) for k, v in st.relations.items()},
        "history": st.history,
        "wishes": st.wishes.to_dict(),
        "inventions": getattr(st.world.catalog, "inventions", []),
        "metrics": {m: dict(cnt) for m, cnt in st.metrics.models.items()},
        "metric_items": {m: sorted(v) for m, v in st.metrics.items.items()},
        "metric_retired": {m: dict(v) for m, v in st.metrics.retired.items()},
        "metric_verbs": {m: dict(v) for m, v in st.metrics.verbs.items()},
        "metric_verbs_ok": {m: dict(v) for m, v in st.metrics.verbs_ok.items()},
        "metric_verbs_since": st.metrics.verbs_since,
    }


def save(st: "ServerState", path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(snapshot(st)))
    os.replace(tmp, path)


def restore(st: "ServerState", path: Path) -> None:
    data = json.loads(path.read_text())
    wd = data["world"]
    w = World(wd["width"], wd["height"], [list(r) for r in wd["tiles"]], Catalog.load())
    from ..world.actions import invention_effects, is_toolish
    for inv in data.get("inventions", []):
        words = inv["name"] + " " + inv.get("desc", "")
        if not inv.get("effects") and not inv.get("food"):  # re-check older saves against the current rules
            inv["effects"] = invention_effects(words)
            if inv["effects"]:
                inv["tool"], inv["placeable"] = False, True
            elif not inv.get("tool") and is_toolish(words):
                inv["tool"], inv["placeable"] = True, False
        w.catalog.add_invention(inv)
    w.tick = wd["tick"]
    w.weather = wd.get("weather", "clear")
    w.weather_until = wd.get("weather_until", 0)
    w._next_id = wd["next_id"]
    w.discoveries = wd.get("discoveries", {})
    w.ext = dict(wd.get("ext") or {})  # packs' world state (saves from before the packs: none)
    effects_by_item = {inv["id"]: inv.get("effects", []) for inv in data.get("inventions", [])}
    from ..world.terrain import TABLET_TEXT, TERMINAL_READY
    for o in wd["objects"]:
        if o["kind"] == "tablet" and o["data"].get("text") != TABLET_TEXT and "TERMINAL" in o["data"].get("text", ""):
            o["data"]["text"] = TABLET_TEXT  # older, wordier tablets
        if o["kind"] == "terminal" and o["data"].get("screen") == ["The terminal hums. Its screen is blank."]:
            o["data"]["screen"] = list(TERMINAL_READY)  # older saves had a blank, unhelpful screen
        if o["kind"] == "creation" and o["data"].get("item") in effects_by_item:
            o["data"]["effects"] = effects_by_item[o["data"]["item"]]
            if "light" in o["data"]["effects"]:
                o["data"]["lit"] = True
        obj = WorldObject(o["id"], o["kind"], o["x"], o["y"], o["data"])
        w.objects[obj.id] = obj
        w.grid[(obj.x, obj.y)] = obj.id
    w.reindex()
    for g in wd["ground"]:
        w.ground[(g["x"], g["y"])] = Counter(g["items"])
    for cd in wd["creatures"]:
        c = Creature(cd["id"], cd["name"], cd["x"], cd["y"], model=cd["model"], color=cd["color"], persona=cd["persona"],
                     inventory=Counter(cd["inventory"]), satiety=cd["satiety"], energy=cd["energy"], health=cd["health"],
                     collapsed_until=0 if not cd.get("collapsed_until") else w.tick + 5,
                     known_recipes=set(cd["known_recipes"]), stats=Counter(cd["stats"]),
                     spots={k: tuple(v) for k, v in cd.get("spots", {}).items()},
                     minds=cd.get("minds", []), stats_base=Counter(cd.get("stats_base", {})), harness=dict(cd.get("harness", {})),
                     landmarks_seen=set(cd.get("landmarks_seen", [])), ext=dict(cd.get("ext") or {}))
        c.asleep = True
        if "initiative" not in c.persona:  # saves from before temperaments: assign one, stable per creature
            import random as _r
            from ..mind.prompts import make_temperament
            c.persona.update(make_temperament(_r.Random(c.id + c.name)))
        w.creatures[c.id] = c
    from ..world.terrain import place_wishing_stone, spawn_animals
    spawn_animals(w, w.rng)  # older saves predate animals
    if not any(o.kind == "wishing_stone" for o in w.objects.values()):  # nor did they have a wishing stone
        place_wishing_stone(w)
    from ..world.registry import run_populate
    run_populate(w, w.rng, fresh=False)  # packs add what a world from before them lacks (idempotent)
    w.changed_objects.clear()
    st.world = w
    st.sim.world = w
    st.sim._event_cursor = 0
    st.sim._returned_cursor = 0
    st.memories = {}
    for cid, md in data.get("memories", {}).items():
        m = Memory(entries=[Entry(t, txt, imp) for t, txt, imp in md["entries"]], summary=md["summary"], goal=md["goal"],
                   people=md["people"], thinks_since_reflect=md["thinks_since_reflect"],
                   entries_since_reflect=md["entries_since_reflect"],
                   plan=list(md.get("plan", [])), plan_step=md.get("plan_step", 0),
                   thought_back=list(md.get("thought_back", [])))
        st.memories[cid] = m
    st.world.recall_hook = st._recall_hook
    if "recall" in data:
        st.recall.load(data["recall"])
    else:  # a save from before recall: what the creatures remember becomes searchable
        st.recall = RecallIndex()
        for cid, m in st.memories.items():
            for e in m.entries:
                st.recall.add(cid, "memory", e.text, e.tick, e.importance)
            if m.summary:
                st.recall.add(cid, "memory", f"You reflected: {m.summary}", w.tick, 3)
    st.load_lore()  # the current lore wins over whatever the save held
    st.owner = data.get("owner", {})
    st.model_colors = data.get("model_colors", {})
    st.chronicle = data.get("chronicle", [])
    st.sky_words = data.get("sky_words", [])
    st.relations = {k: Counter(v) for k, v in data.get("relations", {}).items()}
    st.history = data.get("history", [])
    st.wishes = Wishes(w.catalog)
    st.wishes.people = {c.name.lower() for c in w.creatures.values()}
    st.wishes.load(data.get("wishes"))
    for m, cnt in data.get("metrics", {}).items():
        st.metrics.models[m].update(cnt)
    for m, r in data.get("metric_retired", {}).items():
        st.metrics.retired[m].update(r)
    for m, items in data.get("metric_items", {}).items():
        st.metrics.items[m].update(items)
    for m, n in data.get("metric_verbs", {}).items():
        st.metrics.verbs[m].update(n)
    for m, n in data.get("metric_verbs_ok", {}).items():
        st.metrics.verbs_ok[m].update(n)
    st.metrics.verbs_since = data.get("metric_verbs_since", 0) if "metric_verbs" in data else w.tick  # older saves
    st.harness.assign(w.creatures.values())
    st.chronicle_from = w.tick
    st.chronicle_due = w.tick + 600
