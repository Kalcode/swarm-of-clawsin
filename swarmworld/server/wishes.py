"""Wishes: what the creatures want that their world doesn't have (yet).

Gathered from what they say ("I wish we had a proper roof", "we need...", "if only..."), from what they
fail to make because the world has never heard of it, from their reflections, and from the wish action.
Ranked so the people running the world can see, answer, grant, or build what is most wanted."""

from __future__ import annotations

import re

from ..world.catalog import Catalog
from ..world.events import Event

SPOKEN = [
    re.compile(r"\b(?:i|we)\s+(?:really\s+|still\s+|do\s+)?(?:wish|need|want)\b"
               r"(?:\s+(?:we|i)\s+(?:had|could have|could make|could find))?\s+(?:for\s+)?(?P<thing>[^.!?;,]+)", re.I),
    re.compile(r"\bif\s+only\s+(?:we|i)\s+(?:had|could have|could make)\s+(?P<thing>[^.!?;,]+)", re.I),
]
FAILED = [
    re.compile(r"don't know of anything called '([^']+)'"),
    re.compile(r"never heard of a '([^']+)'"),
    re.compile(r"No one has ever made a '([^']+)'"),
]
LEAD = {"a", "an", "the", "some", "more", "another", "any", "few", "lot", "lots", "of", "to", "have", "get", "make"}
TRAIL = {"here", "now", "today", "tonight", "too", "again", "soon", "already", "please", "badly", "though"}
NOT_A_THING = re.compile(r"^(to|you|it|that|this|them|him|her|us|me|my|your|our|he|she|they|i|we|someone|something|"
                         r"anything|nothing|help|food|rest|sleep|eat|go|find|know|be|keep|try|talk|learn)\b")
KINDS = ("said", "failed", "wished", "reflected")
QUOTES = 4
MAX_WISHES = 300


def thing_of(text: str) -> str:
    """The thing a phrase asks for, as a short lowercase name: 'a proper roof over us' -> 'proper roof over us'."""
    words = re.findall(r"[a-z][a-z'-]*", text.lower())
    if words and words[0] in ("to",) and len(words) > 1 and words[1] in ("have", "get", "make"):  # "to have a boat"
        words = words[2:]
    while words and words[0] in LEAD - {"to"}:
        words = words[1:]
    while words and words[-1] in TRAIL:
        words = words[:-1]
    thing = " ".join(words[:6])
    if len(thing) < 3 or NOT_A_THING.match(thing):
        return ""
    return thing


class Wishes:
    def __init__(self, catalog: Catalog):
        self.catalog = catalog
        self.items: dict[str, dict] = {}
        self.seq = 0

    # ------------------------------------------------------------ gathering
    def observe(self, ev: Event, names: dict[str, str]) -> None:
        """Pick wishes out of a world event (speech, failures, the wish action)."""
        who = names.get(ev.actor or "", "") or ev.data.get("speaker") or ""
        if not who or ev.data.get("terminal"):
            return
        if ev.kind == "say":
            self._from_words(who, ev.data.get("line") or "", "said", ev.tick)
        elif ev.kind == "fail":
            for rx in FAILED:
                m = rx.search(ev.text)
                if m:
                    self.add(who, thing_of(m.group(1)), "failed", ev.text.split(": ", 1)[-1], ev.tick)
                    return
        elif ev.kind == "wish":
            line = ev.data.get("line") or ""
            if not self._from_words(who, line, "wished", ev.tick):
                self.add(who, thing_of(line), "wished", line, ev.tick)

    def observe_reflection(self, who: str, text: str, tick: int) -> None:
        self._from_words(who, text, "reflected", tick)

    def _from_words(self, who: str, line: str, kind: str, tick: int) -> bool:
        found = False
        for rx in SPOKEN:
            for m in rx.finditer(line):
                found = self.add(who, thing_of(m.group("thing")), kind, line, tick) or found
        return found

    def add(self, who: str, thing: str, kind: str, quote: str, tick: int) -> bool:
        if not thing:
            return False
        key = re.sub(r"(?<=[a-z]{3})s\b", "", thing)  # roofs ~ roof
        w = self.items.get(key)
        if w is None:
            if len(self.items) >= MAX_WISHES:
                return False
            self.seq += 1
            w = self.items[key] = {"id": f"w{self.seq}", "thing": thing, "kinds": dict.fromkeys(KINDS, 0), "by": {},
                                   "quotes": [], "first_tick": tick, "last_tick": tick, "status": "open",
                                   "answer": "", "granted": ""}
        w["kinds"][kind] += 1
        w["by"][who] = w["by"].get(who, 0) + 1
        w["last_tick"] = tick
        w["quotes"] = (w["quotes"] + [{"tick": tick, "name": who, "kind": kind, "text": quote[:200]}])[-QUOTES:]
        return True

    # ------------------------------------------------------------ reading
    def exists(self, thing: str) -> bool:
        return self.catalog.resolve(thing) is not None

    def view(self, w: dict) -> dict:
        exists = self.exists(w["thing"])
        creatures = len(w["by"])
        total = sum(w["kinds"].values())
        score = 3 * w["kinds"]["wished"] + 2 * creatures + min(total, 10)
        if exists:  # they want something the world has: a need, or a recipe nobody has found
            score //= 3
        return {**w, "by": [{"name": n, "n": k} for n, k in sorted(w["by"].items(), key=lambda kv: -kv[1])],
                "creatures": creatures, "total": total, "score": score, "exists": exists}

    def ranked(self, limit: int = 60) -> list[dict]:
        views = [self.view(w) for w in self.items.values()]
        views.sort(key=lambda v: (v["status"] == "closed", -v["score"], -v["last_tick"]))
        return views[:limit]

    def get(self, wid: str) -> dict | None:
        return next((w for w in self.items.values() if w["id"] == wid), None)

    # ------------------------------------------------------------ saving
    def to_dict(self) -> dict:
        return {"seq": self.seq, "items": self.items}

    def load(self, data: dict | None) -> None:
        if data:
            self.seq = int(data.get("seq", 0))
            self.items = dict(data.get("items", {}))
