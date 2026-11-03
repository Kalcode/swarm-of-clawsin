"""What a watcher may see: allowlists for every document the public viewer gets.

Each document is built by picking named keys from what the server already computes, never by removing the private
ones, so a field added later stays private until it is listed here. Left out on purpose: the join token, brain node
names and hardware, error text from model servers, raw model output, the steward log, the roadmap, and the prompt
text (techniques, systems, perception lines). tests/test_public_view.py checks that every source field is either listed
here or named private, so a new field forces a choice."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..world.events import Event

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
                              "granted", "creatures", "total", "score", "exists")
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

WISHES_SHOWN = 40
TIES_SHOWN = 200
HISTORY_POINTS = 400


def pick(d: dict, keys) -> dict:
    return {k: d[k] for k in keys if k in d}


def public_card(cre: dict) -> dict:
    return pick(cre, CARD_KEYS)


def public_object(o: dict) -> dict:
    return pick(o, OBJECT_KEYS)


def public_event(ev: Event) -> dict | None:
    if ev.kind == "steward" or ev.data.get("brain_node"):
        return None
    return pick(ev.to_dict(), EVENT_KEYS)


def public_detail(st: ServerState, cid: str) -> dict | None:
    d = st.creature_detail(cid)
    if d is None:
        return None
    out = pick(d, DETAIL_KEYS)
    if st.last.get(cid, {}).get("unparsed"):
        out["last_intention"] = ""  # the raw model output of a misparsed turn
    return out


def public_wishes(st: ServerState) -> list[dict]:
    return [{**pick(w, WISH_KEYS), "quotes": w.get("quotes", [])[-1:]} for w in st.wishes.ranked(WISHES_SHOWN)]


def public_society(st: ServerState) -> dict:
    soc = st.society()
    return {**soc, "edges": soc["edges"][:TIES_SHOWN]}


def public_metrics(st: ServerState) -> dict:
    return pick(st.metrics.snapshot(st.world, st.started), METRICS_KEYS)


def public_inventions(st: ServerState) -> list[dict]:
    return [pick(inv, INVENTION_KEYS) for inv in getattr(st.world.catalog, "inventions", [])]


def public_history(rows: list[dict]) -> list[dict]:
    n = len(rows)
    if n <= HISTORY_POINTS:
        return list(rows)
    last = HISTORY_POINTS - 1
    return [rows[i * (n - 1) // last] for i in range(HISTORY_POINTS)]


def public_almanac(full: dict) -> dict:
    out = pick(full, ALMANAC_KEYS)
    out["verbs"] = [pick(v, VERB_KEYS) for v in full.get("verbs", [])]
    out["packs"] = [pick(p, PACK_KEYS) for p in full.get("packs", [])]
    return out
