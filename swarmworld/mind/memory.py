"""Per-creature memory, owned by the world server (brain nodes stay stateless)."""

from __future__ import annotations

from dataclasses import dataclass, field

MAX_ENTRIES = 60


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
