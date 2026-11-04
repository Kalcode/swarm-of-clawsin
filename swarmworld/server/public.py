"""The public viewer's snapshots: documents built once per interval from Task 1's allowlisted projections, encoded
(and gzipped) once, and reused for every request until the next interval. The tick loop feeds `observe` each tick and
calls `publish` when `due`; nothing here runs per request except a lookup (or, for a creature or a slow document,
one build per interval)."""

from __future__ import annotations

import gzip
import json
import math
import secrets
import time
from collections import Counter, deque
from dataclasses import dataclass

from aiohttp import web

from ..world.events import Event
from .almanac import Almanac
from .watching import Watching
from .public_view import (public_almanac, public_buildings, public_card, public_chronicle, public_detail, public_event,
                          public_history, public_inventions, public_landmarks, public_metrics, public_object,
                          public_society, public_static, public_wishes)

SCHEMA = 1
PUBLIC_EVERY = 3.0
STATIC_EVERY_S = 300.0
STATIC_MAX_DELTAS = 500
EVENT_WINDOW_S = 12.0
EVENTS_KEPT = 120
TRAIL_TICKS = 16
CHRONICLE_TAIL = 3
SLOW_EVERY_S = 60.0

LIVE_KEYS = ("schema", "type", "boot", "seq", "every", "tick_seconds", "tick", "from_tick", "clock", "static", "creatures",
             "objects_upsert", "objects_removed", "tiles", "buildings", "landmarks", "events", "chronicle",
             "chronicle_version", "society", "wishes", "metrics", "watching", "here", "frontier")
STATIC_KEYS = ("schema", "type", "version", "tick", "width", "height", "origin_x", "tiles", "regions", "objects", "items", "kinds",
               "nature", "landmarks", "buildings", "inventions")


@dataclass(frozen=True)
class Doc:
    body: bytes
    gz: bytes
    etag: str


def encode(obj, etag: str) -> Doc:
    body = json.dumps(obj, separators=(",", ":"), ensure_ascii=True).encode()  # a lone surrogate (a model can write one) must not fail the build
    return Doc(body, gzip.compress(body, 6, mtime=0), etag)


class Publisher:
    def __init__(self, st, almanac: Almanac | None = None, every: float = PUBLIC_EVERY, clock=time.monotonic,
                 boot: str | None = None, watching: Watching | None = None):
        self.st = st
        self.almanac = almanac or Almanac()
        self.every = every
        self.clock = clock
        self.watching = watching or Watching()
        self.boot = boot or f"{time.time_ns():x}{secrets.token_hex(2)}"
        self.seq = 0
        self.builds: Counter = Counter()
        self._events: deque = deque(maxlen=EVENTS_KEPT)  # (tick, public event with "seq")
        self._event_seq = 0
        self._trails: dict[str, deque] = {}
        self._upsert: dict[str, dict] = {}
        self._removed: set[str] = set()
        self._tiles: dict[tuple, list] = {}
        self._origin_x = st.world.origin_x  # the origin the trails and tile deltas are in
        self._last_publish: float | None = None
        self._last_tick: int | None = None
        self._static_n = 0
        self._static_at = 0.0
        self._static: Doc | None = None
        self._static_shape: tuple | None = None
        self._live: Doc | None = None
        self._creatures: dict[str, Doc] = {}  # only creatures that exist: unknown ids are never remembered
        self._creatures_seq = -1
        self._slow: dict[str, tuple[float, int, Doc]] = {}  # name -> (built at, n, doc)
        self._chronicle: tuple[int, Doc] | None = None

    # ---- per tick -------------------------------------------------------------------------------------------------

    def observe(self, msg: dict, new_events: list[Event]) -> None:
        moved = self.st.world.origin_x - self._origin_x
        if moved:  # land went in west: what was remembered moves with the world
            self._origin_x += moved
            self._trails = {cid: deque(((t, x + moved, y) for t, x, y in trail), maxlen=trail.maxlen)
                            for cid, trail in self._trails.items()}
            self._tiles = {(x + moved, y): [x + moved, y, t] for (x, y), (_, _, t) in self._tiles.items()}
            self._events = deque(((t, {**e, "x": e["x"] + moved}) if isinstance(e.get("x"), int) else (t, e)
                                  for t, e in self._events), maxlen=self._events.maxlen)
        for o in msg.get("objects_upsert") or []:
            self._upsert[o["id"]] = o
            self._removed.discard(o["id"])
        for oid in msg.get("objects_removed") or []:
            self._removed.add(oid)
            self._upsert.pop(oid, None)
        for x, y, t in msg.get("tiles") or []:
            self._tiles[(x, y)] = [x, y, t]
        tick = msg["tick"]
        for c in msg.get("creatures") or []:
            trail = self._trails.get(c["id"])
            if trail is None:
                trail = self._trails[c["id"]] = deque(maxlen=TRAIL_TICKS + 1)
            trail.append((tick, c["x"], c["y"]))
        for ev in new_events:
            pe = public_event(ev)
            if pe is not None:
                self._event_seq += 1
                self._events.append((ev.tick, {**pe, "seq": self._event_seq}))

    # ---- publishing -----------------------------------------------------------------------------------------------

    def due(self) -> bool:
        return self._last_publish is None or self.clock() - self._last_publish >= self.every

    @property
    def static_version(self) -> str:
        return f"{self.boot}-{self._static_n}"

    @property
    def chronicle_version(self) -> str:
        return f"{self.boot}-{len(self.st.chronicle)}"

    def _deltas(self) -> int:
        return len(self._upsert) + len(self._removed) + len(self._tiles)

    def publish(self) -> None:
        now = self.clock()
        try:
            self._publish(now)
        finally:
            self._last_publish = now  # a failing build is retried at the next interval, not at every tick

    def _publish(self, now: float) -> None:
        w = self.st.world
        shape = (len(w.catalog.items), len(w.regions), w.width, w.origin_x)  # a strip of new land changes the map
        if (self._static is None or now - self._static_at >= STATIC_EVERY_S or self._deltas() > STATIC_MAX_DELTAS
                or shape != self._static_shape):
            self._build_static(now, shape)
        self.seq += 1
        self._live = self._build_live()
        self._last_tick = w.tick
        self._creatures, self._creatures_seq = {}, self.seq
        for cid in [c for c in self._trails if c not in w.creatures]:
            del self._trails[cid]

    def _build_static(self, now: float, shape: tuple) -> None:
        n = self._static_n + 1  # taken only once the build has worked: a failed one leaves the version as it was
        version = f"{self.boot}-{n}"
        parts = {"schema": SCHEMA, "type": "static", "version": version,
                 **public_static(self.st.world.to_init()), "inventions": public_inventions(self.st)}
        self._static = encode({k: parts[k] for k in STATIC_KEYS if k in parts}, version)
        self._static_n = n
        self._static_at, self._static_shape = now, shape
        self._upsert.clear()
        self._removed.clear()
        self._tiles.clear()
        self.builds["static"] += 1

    def _paths(self, from_tick: int, tick: int) -> dict[str, list]:
        out = {}
        for cid, trail in self._trails.items():
            span = [(x, y) for t, x, y in trail if from_tick < t <= tick]
            if not span:
                continue
            before = [(x, y) for t, x, y in trail if t <= from_tick]
            start = before[-1] if before else span[0]
            if any(p != start for p in span):
                out[cid] = [list(p) for p in span[-TRAIL_TICKS:]]
        return out

    def _build_live(self) -> Doc:
        st, w = self.st, self.st.world
        tick = w.tick
        from_tick = tick if self._last_tick is None else self._last_tick
        paths = self._paths(from_tick, tick)
        cards = []
        for c in w.creatures.values():
            card = public_card(w.cre_dict(c))
            if c.id in paths:
                card["path"] = paths[c.id]
            cards.append(card)
        watching, here = self.watching.snapshot()
        st.watching = watching  # the home viewer's metrics message carries it too
        horizon = tick - math.ceil(EVENT_WINDOW_S / st.tick_seconds)
        doc = {
            "schema": SCHEMA, "type": "live", "boot": self.boot, "seq": self.seq, "every": self.every,
            "tick_seconds": st.tick_seconds, "tick": tick, "from_tick": from_tick, "clock": w.clock(),
            "static": self.static_version, "creatures": cards,
            "objects_upsert": [public_object(o) for o in self._upsert.values()],
            "objects_removed": sorted(self._removed), "tiles": list(self._tiles.values()),
            "buildings": public_buildings(w.building_dicts()),
            "landmarks": public_landmarks(getattr(w, "landmarks", [])),
            "events": [e for t, e in self._events if t > horizon],
            "chronicle": public_chronicle(st.chronicle[-CHRONICLE_TAIL:]), "chronicle_version": self.chronicle_version,
            "society": public_society(st), "wishes": public_wishes(st), "metrics": public_metrics(st),
            "watching": watching, "here": here,
            "frontier": {"origin_x": w.origin_x, "strips": sum(((w.ext.get("frontier") or {}).get("strips") or {}).get(s, 0)
                                                               for s in ("east", "west"))},
        }
        self.builds["live"] += 1
        return encode(doc, f"{self.boot}-{self.seq}")

    # ---- documents ------------------------------------------------------------------------------------------------

    def live_doc(self) -> Doc:
        return self._live

    def static_doc(self) -> Doc:
        return self._static

    def creature_doc(self, cid: str) -> Doc | None:
        if self._creatures_seq != self.seq:
            self._creatures, self._creatures_seq = {}, self.seq
        doc = self._creatures.get(cid)
        if doc is None:
            detail = public_detail(self.st, cid)
            if detail is None:
                return None  # not cached: a flood of made-up ids costs a dict lookup each and no memory
            doc = self._creatures[cid] = encode(detail, f"{self.boot}-{self.seq}-{cid}")
            self.builds["creature"] += 1
        return doc

    def _slow_doc(self, name: str, tag: str, build) -> Doc:
        now = self.clock()
        built = self._slow.get(name)
        if built is None or now - built[0] >= SLOW_EVERY_S:
            n = (built[1] if built else 0) + 1
            self._slow[name] = built = (now, n, encode(build(), f"{self.boot}-{tag}{n}"))
            self.builds[name] += 1
        return built[2]

    def almanac_doc(self) -> Doc:
        return self._slow_doc("almanac", "a", lambda: public_almanac(self.almanac.get(self.st)))

    def history_doc(self) -> Doc:
        return self._slow_doc("history", "h", lambda: public_history(self.st.history))

    def chronicle_doc(self) -> Doc:
        n = len(self.st.chronicle)
        if self._chronicle is None or self._chronicle[0] != n:
            self._chronicle = (n, encode(public_chronicle(self.st.chronicle), self.chronicle_version))
            self.builds["chronicle"] += 1
        return self._chronicle[1]


PUBLISHER = web.AppKey("publisher", Publisher)
