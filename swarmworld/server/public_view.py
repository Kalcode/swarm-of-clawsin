"""What a watcher may see: allowlists for every document the public viewer gets.

Each document is built by picking named keys from what the server already computes, never by removing the private
ones, so a field added later stays private until it is listed here. Left out on purpose: the join token, brain node
names and hardware, error text from model servers, raw model output, the steward log, the roadmap, and the prompt
text (techniques, systems, perception lines). tests/test_public_view.py checks that every source field is either listed
here or named private, so a new field forces a choice."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..world.events import Event
from .almanac import PACK_ABOUT

if TYPE_CHECKING:
    from .state import ServerState

CARD_KEYS: tuple[str, ...] = ("id", "name", "x", "y", "model", "color", "activity", "thinking", "asleep", "sleeping",
                              "say", "satiety", "energy", "health", "holding", "light")
OBJECT_KEYS: tuple[str, ...] = ("id", "kind", "x", "y", "label", "lit", "stage", "crop", "tamed_by", "text")
EVENT_KEYS: tuple[str, ...] = ("tick", "kind", "actor", "x", "y", "text", "sound", "radius", "loud")
DETAIL_KEYS: tuple[str, ...] = ("id", "name", "model", "minds", "color", "persona", "x", "y", "asleep", "thinking",
                                "activity", "perception", "last_thought", "last_intention", "last_result", "reflection",
                                "inventory", "satiety", "energy", "health", "goal", "plan", "plan_step", "summary",
                                "known_recipes", "people", "recent", "stats", "harness")
DETAIL_PRIVATE: tuple[str, ...] = ("node", "last_error")
WISH_KEYS: tuple[str, ...] = ("id", "thing", "kinds", "by", "quotes", "first_tick", "last_tick", "status", "answer",
                              "granted", "creatures", "total", "score", "exists", "reflected_only")
INVENTION_KEYS: tuple[str, ...] = ("id", "name", "desc", "food", "placeable", "tool", "depth", "effects", "inputs",
                                   "station", "by", "model", "tick")
METRICS_KEYS: tuple[str, ...] = ("tick", "uptime_s", "thinks_per_min", "models", "discoveries")
METRICS_PRIVATE: tuple[str, ...] = ("type", "tick_ms")
ALMANAC_KEYS: tuple[str, ...] = ("tick", "day", "items", "recipes", "processes", "designs", "kinds", "verbs", "packs",
                                 "tree", "inventions", "world")
ALMANAC_PRIVATE: tuple[str, ...] = ("techniques", "systems", "perception", "populate", "harness", "roadmap")
VERB_KEYS: tuple[str, ...] = ("name", "pack", "aliases", "core", "about", "used")
VERB_PRIVATE: tuple[str, ...] = ("tip", "shown", "uses")
# the public almanac's packs are only names and counts (enough for its index and filter chips)
PACK_KEYS: tuple[str, ...] = ("id", "about", "items", "recipes", "kinds", "verbs", "designs")
PACK_PRIVATE: tuple[str, ...] = ("techniques", "systems", "perception", "populate")

# the nested parts of the almanac, metrics, history, wishes and society: every key the server produces today is listed
# (creature names and ids are public by design: sites' "by", discoveries' "by_id"); a new one fails the tests until
# it is added here or declared private. Dicts keyed by data (item ids, kinds, model tags) are copied whole.
ITEM_KEYS: tuple[str, ...] = ("id", "name", "aliases", "tags", "food", "placeable", "desc", "pack", "tier", "reached",
                              "status", "discovered", "sources", "hint", "used_in", "kind")
SOURCE_KEYS: tuple[str, ...] = ("how", "source", "tools", "amount", "note")
USED_IN_KEYS: tuple[str, ...] = ("output", "as")
DISCOVERY_KEYS: tuple[str, ...] = ("item", "by", "by_id", "model", "tick", "day", "invented")
RECIPE_KEYS: tuple[str, ...] = ("output", "inputs", "tools", "station", "count", "known_at_start", "pack")
PROCESS_KEYS: tuple[str, ...] = (*RECIPE_KEYS, "how", "note")
DESIGN_KEYS: tuple[str, ...] = ("id", "name", "about", "needs", "work", "kinds", "roof", "over_water", "pack", "tier",
                                "built", "sites", "status")
KIND_KEYS: tuple[str, ...] = ("id", "name", "aliases", "pack", "look", "glyph", "glow", "category", "yields", "gives",
                              "blocking", "animal", "gatherable", "carvable", "store", "station", "water", "over_water",
                              "wild", "wary", "flee", "habitat", "game", "count")
TREE_KEYS: tuple[str, ...] = ("nodes", "edges")
TREE_NODE_KEYS: tuple[str, ...] = ("id", "type", "tier")
TREE_EDGE_KEYS: tuple[str, ...] = ("from", "to", "kind", "n", "how", "back")
WORLD_KEYS: tuple[str, ...] = ("tick", "clock", "kinds", "groups", "items", "tamed", "crops", "buildings", "built",
                               "sites", "discoveries", "creatures", "verbs_since", "lands")
LANDS_KEYS: tuple[str, ...] = ("strips", "count", "found")
LAND_FOUND_KEYS: tuple[str, ...] = ("name", "theme", "by")
CLOCK_KEYS: tuple[str, ...] = ("day", "light", "phase", "weather")
GROUP_KEYS: tuple[str, ...] = ("label", "count", "kinds")
BUILDING_KEYS: tuple[str, ...] = ("id", "design", "x0", "y0", "x1", "y1", "door", "roof", "by", "tick")
SITE_KEYS: tuple[str, ...] = ("design", "needs", "have", "work", "done", "by")
WORLD_CREATURE_KEYS: tuple[str, ...] = ("id", "name", "model", "color", "asleep", "known")
VERB_USED_KEYS: tuple[str, ...] = ("tries", "ok", "by_model")
METRICS_MODEL_KEYS: tuple[str, ...] = ("creatures", "awake", "thinks", "avg_latency_s", "success_rate", "noop_rate",
                                       "parse_failures", "errors", "loops", "tokens_out", "cache_hit", "unique_items",
                                       "discoveries", "crafted", "gathered", "built", "speech", "writing", "programs",
                                       "inventions", "tamed", "planted", "collapses")
METRICS_DISCOVERY_KEYS: tuple[str, ...] = ("item", "by", "model", "tick", "invented")
HISTORY_KEYS: tuple[str, ...] = ("tick", "day", "models", "world")
HISTORY_MODEL_KEYS: tuple[str, ...] = ("creatures", "crafted", "discoveries", "inventions", "speech", "built", "gathered",
                                       "writing", "collapses", "stored", "tended_fire", "learned", "recipes_known", "thinks")
HISTORY_WORLD_KEYS: tuple[str, ...] = ("recipes_known", "firsts", "structures", "camps", "inventions", "ties")
QUOTE_KEYS: tuple[str, ...] = ("tick", "name", "kind", "text")
SOCIETY_KEYS: tuple[str, ...] = ("nodes", "edges", "hubs", "loners")
SOCIETY_NODE_KEYS: tuple[str, ...] = ("id", "name", "model", "color", "asleep", "drive")
SOCIETY_EDGE_KEYS: tuple[str, ...] = ("a", "b", "talk", "gift", "teach", "play", "weight")
SOCIETY_HUB_KEYS: tuple[str, ...] = ("id", "name", "weight")
# the static document's world parts, from World.to_init (creatures and the clock live in live.json); kinds, items and
# regions are picked one by one like everything else, and the tile and nature rows are terrain codes
STATIC_INIT_KEYS: tuple[str, ...] = ("tick", "width", "height", "origin_x", "tiles", "regions", "objects", "items", "kinds", "nature",
                                     "landmarks", "buildings")
STATIC_INIT_PRIVATE: tuple[str, ...] = ("type", "creatures", "clock")
REGION_KEYS: tuple[str, ...] = ("name", "level", "y0", "y1", "sky", "weather")
VIEW_KIND_KEYS: tuple[str, ...] = ("name", "look", "glyph", "glow")
GLYPH_KEYS: tuple[str, ...] = ("char", "color")
NATURE_KEYS: tuple[str, ...] = ("biomes", "flow")
LANDMARK_KEYS: tuple[str, ...] = ("name", "x", "y", "kind", "size")
LANDMARK_PRIVATE: tuple[str, ...] = ("by_sight",)  # how creatures come to know a place; the viewer doesn't use it
CHAPTER_KEYS: tuple[str, ...] = ("tick", "day", "phase", "text")
PERSONA_KEYS: tuple[str, ...] = ("name", "traits", "drive", "initiative", "role", "novelty")
MIND_KEYS: tuple[str, ...] = ("model", "until")
# a creature's counters (Creature.stats); tests/test_public_view.py scans the source so a new one has to be listed.
# The per-day counters (invented_day_N) are left out.
STAT_KEYS: tuple[str, ...] = (
    "built", "collapses", "crafted", "discoveries", "dug", "errors", "failed_combos", "gathered", "gifts", "hunted",
    "inspirations", "inventions", "learned_by_listening", "learned_by_reading", "learned_by_watching", "nights_slept",
    "planted", "programs", "speech", "stored", "tamed", "taught", "tended_fire", "thinks", "took_from_store",
    "wishes", "writing")

WISHES_SHOWN = 40
REFLECTED_SHOWN = 15
TIES_SHOWN = 200
HISTORY_POINTS = 400


def pick(d: dict, keys) -> dict:
    return {k: d[k] for k in keys if k in d}


def pick_all(rows, keys) -> list[dict]:
    return [pick(r, keys) for r in rows]


def public_card(cre: dict) -> dict:
    return pick(cre, CARD_KEYS)


def public_object(o: dict) -> dict:
    return pick(o, OBJECT_KEYS)


def public_buildings(rows) -> list[dict]:
    return pick_all(rows, BUILDING_KEYS)


def public_landmarks(rows) -> list[dict]:
    return pick_all(rows, LANDMARK_KEYS)


def public_chronicle(chapters) -> list[dict]:
    return pick_all(chapters, CHAPTER_KEYS)


def _view_kind(spec: dict) -> dict:
    out = pick(spec, VIEW_KIND_KEYS)
    if isinstance(out.get("glyph"), dict):
        out["glyph"] = pick(out["glyph"], GLYPH_KEYS)
    return out


def public_static(init: dict) -> dict:
    """The world parts of static.json, from World.to_init(): every part picked."""
    out = pick(init, ("tick", "width", "height", "origin_x", "tiles"))
    out["regions"] = pick_all(init.get("regions", []), REGION_KEYS)
    out["objects"] = [public_object(o) for o in init.get("objects", [])]
    out["items"] = {i: name for i, name in init.get("items", {}).items() if isinstance(name, str)}
    out["kinds"] = {k: _view_kind(spec) for k, spec in init.get("kinds", {}).items()}
    if isinstance(init.get("nature"), dict):
        out["nature"] = pick(init["nature"], NATURE_KEYS)
    out["landmarks"] = public_landmarks(init.get("landmarks", []))
    out["buildings"] = public_buildings(init.get("buildings", []))
    return out


def public_event(ev: Event) -> dict | None:
    if ev.kind == "steward" or ev.data.get("brain_node"):
        return None
    return pick(ev.to_dict(), EVENT_KEYS)


def _pick_in(d: dict, key: str, keys) -> None:
    if isinstance(d.get(key), list):
        d[key] = pick_all(d[key], keys)


def public_detail(st: ServerState, cid: str) -> dict | None:
    d = st.creature_detail(cid)
    if d is None:
        return None
    out = pick(d, DETAIL_KEYS)
    if st.last.get(cid, {}).get("unparsed"):
        out["last_intention"] = ""  # the raw model output of a misparsed turn
    _pick_in(out, "minds", MIND_KEYS)
    if isinstance(out.get("persona"), dict):
        out["persona"] = pick(out["persona"], PERSONA_KEYS)
    if isinstance(out.get("stats"), dict):
        out["stats"] = pick(out["stats"], STAT_KEYS)
    return out


def public_wishes(st: ServerState) -> list[dict]:
    return [{**pick(w, WISH_KEYS), "quotes": pick_all(w.get("quotes", [])[-1:], QUOTE_KEYS)}
            for w in st.wishes.ranked(WISHES_SHOWN, REFLECTED_SHOWN)]


def public_society(st: ServerState) -> dict:
    soc = pick(st.society(), SOCIETY_KEYS)
    soc["nodes"] = pick_all(soc["nodes"], SOCIETY_NODE_KEYS)
    soc["edges"] = pick_all(soc["edges"][:TIES_SHOWN], SOCIETY_EDGE_KEYS)
    soc["hubs"] = pick_all(soc["hubs"], SOCIETY_HUB_KEYS)
    return soc


def public_metrics(st: ServerState) -> dict:
    out = pick(st.metrics.snapshot(st.world, st.started), METRICS_KEYS)
    out["models"] = {m: pick(v, METRICS_MODEL_KEYS) for m, v in out.get("models", {}).items()}
    _pick_in(out, "discoveries", METRICS_DISCOVERY_KEYS)
    return out


def public_inventions(st: ServerState) -> list[dict]:
    return pick_all(getattr(st.world.catalog, "inventions", []), INVENTION_KEYS)


def _history_row(row: dict) -> dict:
    out = pick(row, HISTORY_KEYS)
    if isinstance(out.get("models"), dict):
        out["models"] = {m: pick(v, HISTORY_MODEL_KEYS) for m, v in out["models"].items()}
    if isinstance(out.get("world"), dict):
        out["world"] = pick(out["world"], HISTORY_WORLD_KEYS)
    return out


def public_history(rows: list[dict]) -> list[dict]:
    n = len(rows)
    if n > HISTORY_POINTS:
        rows = [rows[i * (n - 1) // (HISTORY_POINTS - 1)] for i in range(HISTORY_POINTS)]
    return [_history_row(r) for r in rows]


def _item(it: dict) -> dict:
    out = pick(it, ITEM_KEYS)
    _pick_in(out, "sources", SOURCE_KEYS)
    _pick_in(out, "used_in", USED_IN_KEYS)
    if isinstance(out.get("discovered"), dict):
        out["discovered"] = pick(out["discovered"], DISCOVERY_KEYS)
    return out


def _world(w: dict) -> dict:
    out = pick(w, WORLD_KEYS)
    if isinstance(out.get("clock"), dict):
        out["clock"] = pick(out["clock"], CLOCK_KEYS)
    if isinstance(out.get("groups"), dict):
        out["groups"] = {g: pick(v, GROUP_KEYS) for g, v in out["groups"].items()}
    if isinstance(out.get("lands"), dict):
        out["lands"] = pick(out["lands"], LANDS_KEYS)
        _pick_in(out["lands"], "found", LAND_FOUND_KEYS)
    _pick_in(out, "buildings", BUILDING_KEYS)
    _pick_in(out, "sites", SITE_KEYS)
    _pick_in(out, "discoveries", DISCOVERY_KEYS)
    _pick_in(out, "creatures", WORLD_CREATURE_KEYS)
    return out


def public_almanac(full: dict) -> dict:
    out = pick(full, ALMANAC_KEYS)
    out["items"] = [_item(i) for i in full.get("items", [])]
    out["recipes"] = pick_all(full.get("recipes", []), RECIPE_KEYS)
    out["processes"] = pick_all(full.get("processes", []), PROCESS_KEYS)
    out["designs"] = pick_all(full.get("designs", []), DESIGN_KEYS)
    out["kinds"] = pick_all(full.get("kinds", []), KIND_KEYS)
    out["verbs"] = [{**pick(v, VERB_KEYS), **({"used": pick(v["used"], VERB_USED_KEYS)} if "used" in v else {})}
                    for v in full.get("verbs", [])]
    out["packs"] = [{**p, "about": PACK_ABOUT.get(p.get("id"), "")} for p in pick_all(full.get("packs", []), PACK_KEYS)]
    tree = pick(full.get("tree", {}), TREE_KEYS)
    out["tree"] = {"nodes": pick_all(tree.get("nodes", []), TREE_NODE_KEYS),
                   "edges": pick_all(tree.get("edges", []), TREE_EDGE_KEYS)}
    out["inventions"] = pick_all(full.get("inventions", []), INVENTION_KEYS)
    out["world"] = _world(full.get("world", {}))
    return out
