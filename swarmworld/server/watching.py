"""The public viewer's "watching" count. Edge caching hides each watcher's poll from this Mac, so every open public page
also sends a small uncached check-in (POST /public/here) with a random id it made for the tab. This counts the distinct
ids heard from lately and sets how often pages should check in, so the origin hears about TARGET_RPS check-ins a second
however many people watch. Memory only: ids and salted address hashes are never saved, logged or published."""

from __future__ import annotations

import hashlib
import math
import secrets
import time

WINDOW = 90.0          # seconds an id counts after it was last seen
PER_ADDRESS = 5        # ids counted per address (a household, an office)
MAX_IDS = 100_000
EVERY = 30             # seconds between a page's check-ins
TARGET_RPS = 10.0
SMOOTH_S = 60.0        # the estimate's moving average
MIN_SAMPLE = 0.001
PRUNE_EVERY = 1.0


class Watching:
    def __init__(self, clock=time.monotonic, window: float = WINDOW, per_address: int = PER_ADDRESS,
                 max_ids: int = MAX_IDS):
        self.clock = clock
        self.window, self.per_address, self.max_ids = window, per_address, max_ids
        self._salt = secrets.token_bytes(16)   # made at boot, never written anywhere
        self._seen: dict[str, tuple[float, bytes]] = {}   # id -> (last seen, address hash)
        self._per: dict[bytes, int] = {}
        self._pruned = -math.inf
        self._estimate: float | None = None
        self._estimated_at = 0.0
        self.sample = 1.0

    def _hash(self, address: str) -> bytes:
        return hashlib.blake2b(address.encode("utf-8", "replace"), key=self._salt, digest_size=8).digest()

    def _prune(self, now: float) -> None:
        if now - self._pruned < PRUNE_EVERY:
            return
        self._pruned = now
        for wid in [w for w, (seen, _) in self._seen.items() if now - seen > self.window]:
            self._drop(wid)

    def _drop(self, wid: str) -> None:
        _, addr = self._seen.pop(wid)
        left = self._per[addr] - 1
        if left > 0:
            self._per[addr] = left
        else:
            del self._per[addr]

    def note(self, wid: str, address: str) -> None:
        """Hear from an id. One beyond its address's cap, or past the hard cap, is accepted and not counted."""
        now = self.clock()
        self._prune(now)
        addr = self._hash(address)
        known = self._seen.get(wid)
        if known is not None:
            if known[1] == addr:
                self._seen[wid] = (now, addr)
            return
        if len(self._seen) >= self.max_ids or self._per.get(addr, 0) >= self.per_address:
            return
        self._seen[wid] = (now, addr)
        self._per[addr] = self._per.get(addr, 0) + 1

    def count(self) -> int:
        self._prune(self.clock())
        return len(self._seen)

    def snapshot(self) -> tuple[int, dict]:
        """(watching, here) for a live document. Each page checks in every EVERY seconds with probability `sample`, so
        over the window it is heard with probability 1-(1-sample)^(window/EVERY): the count is divided by that, not by
        sample itself (which would overcount several times over at low rates). The rate follows a smoothed estimate."""
        now = self.clock()
        heard = self.count()
        chances = max(1.0, self.window / EVERY)
        seen_p = 1.0 - (1.0 - self.sample) ** chances
        raw = heard / seen_p
        if self._estimate is None:
            self._estimate = raw
        else:
            a = 1.0 - math.exp(-max(0.0, now - self._estimated_at) / SMOOTH_S)
            self._estimate += a * (raw - self._estimate)
        self._estimated_at = now
        watching = round(raw)
        self.sample = sample_rate(self._estimate)
        return watching, {"every": EVERY, "sample": self.sample}


def sample_rate(estimate: float) -> float:
    return max(MIN_SAMPLE, round(min(1.0, TARGET_RPS * EVERY / max(1.0, estimate)), 3))
