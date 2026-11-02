"""Item and recipe catalog, loaded from swarmworld/data/*.json."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
ARTICLES = ("a ", "an ", "the ", "some ", "my ", "one ")


@dataclass(frozen=True)
class Item:
    id: str
    name: str
    aliases: tuple[str, ...] = ()
    food: int = 0
    placeable: bool = False
    tags: tuple[str, ...] = ()
    desc: str = ""


@dataclass(frozen=True)
class Recipe:
    output: str
    inputs: dict[str, int]
    tools: list[str] = field(default_factory=list)
    station: str | None = None
    count: int = 1
    known_at_start: bool = False

    @property
    def id(self) -> str:
        return self.output


def _norm(name: str) -> str:
    n = " ".join(name.lower().replace("_", " ").replace("-", " ").split())
    n = re.sub(r"^(\d+|x\d+)\s*x?\s+", "", n)  # "3 stick", "2x stone"
    n = re.sub(r"\s+x?\d+$", "", n)            # "stick x3", "stone 2"
    for art in ARTICLES:
        if n.startswith(art):
            n = n[len(art):]
    return n.strip(" .!?,'\"")


class Catalog:
    def __init__(self, items: dict[str, Item], recipes: list[Recipe]):
        self.items = items
        self.recipes = recipes
        self._names: dict[str, str] = {}
        for item in items.values():
            for n in (item.id, item.name, *item.aliases):
                self._names.setdefault(_norm(n), item.id)

    @classmethod
    @lru_cache(maxsize=1)
    def load(cls) -> "Catalog":
        raw_items = json.loads((DATA / "items.json").read_text())
        items = {
            iid: Item(
                id=iid,
                name=d["name"],
                aliases=tuple(d.get("aliases", [])),
                food=d.get("food", 0),
                placeable=d.get("placeable", False),
                tags=tuple(d.get("tags", [])),
                desc=d.get("desc", ""),
            )
            for iid, d in raw_items.items()
        }
        recipes = [
            Recipe(
                output=r["output"],
                inputs=dict(r["inputs"]),
                tools=list(r.get("tools", [])),
                station=r.get("station"),
                count=r.get("count", 1),
                known_at_start=r.get("known_at_start", False),
            )
            for r in json.loads((DATA / "recipes.json").read_text())
        ]
        return cls(items, recipes)

    def copy(self) -> "Catalog":
        """A private catalog for one world, so inventions don't leak between worlds."""
        cat = Catalog(dict(self.items), list(self.recipes))
        cat.inventions = list(getattr(self, "inventions", []))
        return cat

    def add_invention(self, inv: dict) -> None:
        """Register a creature-invented item and its recipe. `inv` is the JSON-able record saved with the world."""
        tags = ("invention", "tool") if inv.get("tool") else ("invention",)
        item = Item(id=inv["id"], name=inv["name"], aliases=(), food=inv.get("food", 0),
                    placeable=inv.get("placeable", False), tags=tags, desc=inv.get("desc", ""))
        self.items[item.id] = item
        self._names.setdefault(_norm(item.name), item.id)
        self.recipes.append(Recipe(output=item.id, inputs=dict(inv["inputs"]), station=inv.get("station")))
        if not hasattr(self, "inventions"):
            self.inventions = []
        self.inventions.append(inv)

    def resolve(self, name: str) -> str | None:
        n = _norm(name or "")
        if not n:
            return None
        if n in self._names:
            return self._names[n]
        for cand in (n[:-1] if n.endswith("s") else None, n[:-2] if n.endswith("es") else None):
            if cand and cand in self._names:
                return self._names[cand]
        return None

    def name(self, item_id: str) -> str:
        item = self.items.get(item_id)
        return item.name if item else item_id.replace("_", " ")

    def match_combination(self, item_ids: set[str]) -> Recipe | None:
        for r in self.recipes:
            if set(r.inputs) == set(item_ids):
                return r
        return None

    def contained_recipe(self, item_ids: set[str], have: dict | None = None) -> Recipe | None:
        """The best recipe whose ingredients are all among item_ids (at least two kinds): one the holder can
        afford if possible, then the one using the most kinds."""
        cands = [r for r in self.recipes if set(r.inputs) <= item_ids and len(r.inputs) >= 2]
        if not cands:
            return None
        def affordable(r: Recipe) -> bool:
            return have is not None and all(have.get(i, 0) >= n for i, n in r.inputs.items())
        cands.sort(key=lambda r: (not affordable(r), -len(r.inputs)))
        return cands[0]

    def near_miss(self, item_ids: set[str]) -> Recipe | None:
        """A recipe that needs everything given plus exactly one more kind of ingredient."""
        for r in self.recipes:
            keys = set(r.inputs)
            if item_ids < keys and len(keys - item_ids) == 1:
                return r
        return None

    def recipes_in_words(self, line: str) -> list[Recipe]:
        """Recipes fully spelled out in some words: the product and every ingredient are named."""
        text = " " + line.lower().replace("-", " ") + " "

        def named(item_id: str) -> bool:
            it = self.items.get(item_id)
            names = [it.name, *it.aliases] if it else [item_id.replace("_", " ")]
            return any(f" {n.lower()}" in text for n in names if len(n) > 2)

        return [r for r in self.recipes if not r.known_at_start and named(r.output) and all(named(i) for i in r.inputs)]

    def recipe_for(self, output_id: str) -> Recipe | None:
        for r in self.recipes:
            if r.output == output_id:
                return r
        return None

    def describe_recipe(self, r: Recipe) -> str:
        parts = " + ".join(f"{n} {self.name(i)}" if n > 1 else self.name(i) for i, n in r.inputs.items())
        extra = ""
        if r.tools:
            extra += " (holding " + ", ".join(self.name(t) for t in r.tools) + ")"
        if r.station:
            extra += f" (near a {self.name(r.station)})"
        out = f"{r.count} {self.name(r.output)}" if r.count > 1 else self.name(r.output)
        return f"{parts} -> {out}{extra}"
