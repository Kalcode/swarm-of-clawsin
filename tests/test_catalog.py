import json

from swarmworld.world.catalog import Catalog, data_files


def test_resolve_aliases():
    cat = Catalog.load()
    assert cat.resolve("Stone Axe") == "stone_axe"
    assert cat.resolve("stone axes") == "stone_axe"
    assert cat.resolve("an axe") == "stone_axe"
    assert cat.resolve("the berries") == "berries"
    assert cat.resolve("plant fibers") == "plant_fiber"
    assert cat.resolve("unobtainium") is None
    assert cat.resolve("") is None


def test_match_combination():
    cat = Catalog.load()
    assert cat.match_combination({"stick", "stone", "rope"}).output == "stone_axe"
    assert cat.match_combination({"stick"}) is None
    assert cat.match_combination({"plant_fiber"}).output == "rope"


def test_known_recipes():
    cat = Catalog.load()
    assert sorted(r.output for r in cat.recipes if r.known_at_start) == ["campfire", "rope"]


def test_recipe_for():
    cat = Catalog.load()
    r = cat.recipe_for("planks")
    assert r.tools == ["stone_axe"] and r.count == 2
    assert cat.recipe_for("stick") is None


def test_every_recipe_references_known_items():
    """Every recipe in every recipes.json, the core's and each pack's, alternatives too, names items of the default
    catalog: an alternative that leans on another pack's item (a crystal lamp from crystal and a food-pack clay pot)
    fails here if that item goes."""
    cat = Catalog.load()
    seen = []
    for source, path in data_files("recipes.json"):
        for r in json.loads(path.read_text()):
            seen.append((source, r["output"], bool(r.get("alt"))))
            for i in [r["output"], *r["inputs"], *r.get("tools", [])]:
                assert i in cat.items, (source, r["output"], i)
            if r.get("station"):
                assert r["station"] in cat.items, (source, r["output"], r["station"])
    assert len(seen) == len(cat.recipes) and {s for s, _, _ in seen} > {"recipes.json"}
    assert ("packs/underground/recipes.json", "crystal_lamp", True) in seen
    assert any(r.output == "crystal_lamp" and r.alt and "clay_pot" in r.inputs for r in cat.recipes)
