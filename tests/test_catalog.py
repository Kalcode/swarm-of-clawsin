from swarmworld.world.catalog import Catalog


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
    cat = Catalog.load()
    for r in cat.recipes:
        assert r.output in cat.items
        for i in list(r.inputs) + r.tools:
            assert i in cat.items, i
        if r.station:
            assert r.station in cat.items
