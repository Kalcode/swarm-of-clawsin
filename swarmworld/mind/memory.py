"""Per-creature memory, owned by the world server (brain nodes stay stateless)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

MAX_ENTRIES = 60


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def same_plan(a: list[str], b: list[str]) -> bool:
    """The same steps, ignoring case, punctuation and small rewording."""
    return len(a) == len(b) and all(SequenceMatcher(None, _norm(x), _norm(y)).ratio() >= 0.75 for x, y in zip(a, b))


@dataclass
class Entry:
    tick: int
    text: str
    importance: int = 1


@dataclass
class Memory:
    entries: list[Entry] = field(default_factory=list)
    summary: str = ""
    goal: str = ""
    plan: list[str] = field(default_factory=list)
    plan_step: int = 0
    people: dict[str, str] = field(default_factory=dict)
    thinks_since_reflect: int = 0
    entries_since_reflect: int = 0

    def add(self, tick: int, text: str, importance: int = 1) -> None:
        text = text.strip()
        if not text:
            return
        if self.entries and self.entries[-1].text == text:
            return
        self.entries.append(Entry(tick, text, importance))
        self.entries_since_reflect += 1
        while len(self.entries) > MAX_ENTRIES:
            old = self.entries[: len(self.entries) - 20]
            victim = min(old, key=lambda e: (e.importance, e.tick))
            self.entries.remove(victim)

    def set_plan(self, steps: list[str]) -> bool:
        """Replace the plan unless it is the same plan reworded (which keeps its progress)."""
        if not steps or (self.plan and same_plan(self.plan, steps)):
            return False
        self.plan, self.plan_step = list(steps), 0
        return True

    def advance(self) -> str | None:
        """Finish the current step; the plan is cleared after its last step. Returns the finished step."""
        if not self.plan:
            return None
        done = self.plan[self.plan_step]
        self.plan_step += 1
        if self.plan_step >= len(self.plan):
            self.plan, self.plan_step = [], 0
        return done

    def recent(self, n: int = 10) -> list[str]:
        return [e.text for e in self.entries[-n:]]

    def since(self, n: int) -> list[str]:
        return [e.text for e in self.entries[-n:]]

    def note_person(self, name: str, note: str) -> None:
        self.people[name] = note[:120]
        if len(self.people) > 15:
            self.people.pop(next(iter(self.people)))

    def needs_reflection(self) -> bool:
        return self.thinks_since_reflect >= 12 and self.entries_since_reflect >= 12

    def apply_reflection(self, text: str) -> None:
        text = " ".join(text.split())[:700]
        if text:
            self.summary = text
        self.thinks_since_reflect = 0
        self.entries_since_reflect = 0
