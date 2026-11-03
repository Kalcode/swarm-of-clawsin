"""The public viewer's "watching" count. Edge caching hides each watcher's poll from this Mac, so every open public page
also sends a small uncached check-in (POST /public/here) with a random id it made for the tab. This counts the distinct
ids heard from lately and sets how often pages should check in, so the origin hears about TARGET_RPS check-ins a second
however many people watch. Memory only: ids and salted address hashes are never saved, logged or published."""

from __future__ import annotations

import hashlib
import ipaddress
import math
import secrets
import time
from collections import OrderedDict

WINDOW = 90.0          # seconds an id counts after it was last seen
PER_ADDRESS = 5        # ids counted per address (a household, an office)
MAX_IDS = 100_000
EVERY = 30             # seconds between a page's check-ins
TARGET_RPS = 10.0
SMOOTH_S = 30.0        # time constant of the published estimate's moving average
MIN_SAMPLE = 0.001
PRUNE_EVERY = 1.0


def client_address(remote: str | None, forwarded: str | None) -> str:
    """The address a check-in counts under: the tunnel's CF-Connecting-IP, but only when the request came from this
    machine (cloudflared); from anywhere else a header is the caller's say-so, so the socket's address is used."""
    try:
        from_here = ipaddress.ip_address(remote or "").is_loopback
    except ValueError:
        from_here = False
    return (forwarded if from_here and forwarded else remote) or ""


def network_of(address: str) -> str:
    """An IPv6 address as its /64 (one household or attacker holds a whole one); anything else as it is."""
    try:
        ip = ipaddress.ip_address(address.strip())
    except ValueError:
        return address
    if ip.version == 6:
        return str(ipaddress.ip_network((ip, 64), strict=False))
    return str(ip)


def hear_probability(sample: float) -> float:
    """The chance a page is heard at least once in a window, when it checks in every EVERY s with probability `sample`."""
    return 1.0 - (1.0 - sample) ** max(1.0, WINDOW / EVERY)


class Watching:
    def __init__(self, clock=time.monotonic, window: float = WINDOW, per_address: int = PER_ADDRESS,
                 max_ids: int = MAX_IDS):
        self.clock = clock
        self.window, self.per_address, self.max_ids = window, per_address, max_ids
        self._salt = secrets.token_bytes(16)   # made at boot, never written anywhere
        # id -> (last seen, address hash, weight), in last-seen order: oldest first, so expiry only looks at the front
        self._seen: OrderedDict[str, tuple[float, bytes, float]] = OrderedDict()
        self._per: dict[bytes, int] = {}
        self._weight = 0.0          # sum of the weights in _seen: the raw estimate of the crowd
        self._estimate: float | None = None
        self._estimated_at = 0.0
        self.sample = 1.0
        self.pruned = 0             # entries looked at by prunes, for the tests

    def _hash(self, address: str) -> bytes:
        return hashlib.blake2b(network_of(address).encode("utf-8", "replace"), key=self._salt, digest_size=8).digest()

    def _prune(self, now: float) -> None:
        """Drop the ids that have expired, from the front; stops at the first fresh one, so it costs O(expired)."""
        while self._seen:
            wid, (seen, addr, weight) = next(iter(self._seen.items()))
            self.pruned += 1
            if now - seen <= self.window:
                return
            del self._seen[wid]
            self._weight -= weight
            left = self._per[addr] - 1
            if left > 0:
                self._per[addr] = left
            else:
                del self._per[addr]
        self._weight = 0.0

    def note(self, wid: str, address: str) -> None:
        """Hear from an id. One beyond its address's cap, or past the hard cap, is accepted and not counted. Each id is
        weighted by how unlikely it was to be heard at the sample rate in force now."""
        now = self.clock()
        self._prune(now)
        addr = self._hash(address)
        weight = 1.0 / hear_probability(self.sample)
        known = self._seen.get(wid)
        if known is not None:
            if known[1] == addr:
                self._weight += weight - known[2]
                self._seen[wid] = (now, addr, weight)
                self._seen.move_to_end(wid)
            return
        if len(self._seen) >= self.max_ids or self._per.get(addr, 0) >= self.per_address:
            return
        self._seen[wid] = (now, addr, weight)
        self._per[addr] = self._per.get(addr, 0) + 1
        self._weight += weight

    def count(self) -> int:
        self._prune(self.clock())
        return len(self._seen)

    def snapshot(self) -> tuple[int, dict]:
        """(watching, here) for a live document. The crowd is estimated as the sum of the ids' weights, smoothed by a
        moving average; the published count is that, and the sample rate follows it."""
        now = self.clock()
        self._prune(now)
        raw = max(0.0, self._weight)
        if self._estimate is None:
            self._estimate = raw
        else:
            a = 1.0 - math.exp(-max(0.0, now - self._estimated_at) / SMOOTH_S)
            self._estimate += a * (raw - self._estimate)
        self._estimated_at = now
        self.sample = sample_rate(self._estimate)
        return round(self._estimate), {"every": EVERY, "sample": self.sample}


def sample_rate(estimate: float) -> float:
    return max(MIN_SAMPLE, round(min(1.0, TARGET_RPS * EVERY / max(1.0, estimate)), 3))
