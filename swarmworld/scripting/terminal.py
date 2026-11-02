"""Runs creature-written Lua programs on in-world terminals, through the sandbox.

A terminal senses like a body would: scan() sees only what is within a few steps of it,
and say() is ordinary speech heard by whoever is near."""

from __future__ import annotations

from ..world.model import World, WorldObject
from ..world.perception import dist
from .lua_sandbox import LuaSandbox

SCAN_MAX = 6
SAYS_PER_RUN = 2
SCREEN_LINES = 12

_sandbox = LuaSandbox()


def run_terminal(world: World, term: WorldObject) -> None:
    code = term.data.get("code") or ""
    if not code:
        return
    said = {"n": 0}

    def scan(r=5):
        try:
            r = max(1, min(SCAN_MAX, int(r)))
        except (TypeError, ValueError):
            r = 5
        out = []
        for y in range(term.y - r, term.y + r + 1):
            for x in range(term.x - r, term.x + r + 1):
                o = world.object_at(x, y)
                if o and o is not term:
                    out.append({"kind": o.kind, "name": o.name, "dx": o.x - term.x, "dy": o.y - term.y})
        for c in world.creatures.values():
            if dist(c.x, c.y, term.x, term.y) <= r:
                out.append({"kind": "creature", "name": c.name, "dx": c.x - term.x, "dy": c.y - term.y})
        out.sort(key=lambda t: max(abs(t["dx"]), abs(t["dy"])))
        return out[:40]

    def say(msg=""):
        if said["n"] >= SAYS_PER_RUN:
            return False
        said["n"] += 1
        line = str(msg)[:200]
        world.emit("say", None, term.x, term.y, f'Terminal: "{line}"', speaker="The terminal", line=line, terminal=term.id)
        return True

    def time_():
        c = world.clock()
        return {"tick": world.tick, "day": c["day"], "phase": c["phase"]}

    state = term.data.setdefault("memory", {})
    res = _sandbox.run(code, {"scan": scan, "say": say, "time": time_}, state)
    screen = list(term.data.get("screen") or [])
    screen += [str(line) for line in res.output]
    if not res.ok:
        screen.append(f"error: {res.error}")
    term.data["screen"] = screen[-SCREEN_LINES:]
    term.data["runs"] = term.data.get("runs", 0) + 1
    term.data["last_ok"] = res.ok
    if res.output or not res.ok:
        world.changed_objects.add(term.id)
