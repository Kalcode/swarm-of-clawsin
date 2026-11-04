import pytest

from swarmworld.world.actions import Intention, apply_intention
from swarmworld.world.catalog import Catalog
from swarmworld.world.model import START_TICK, Creature, World


@pytest.fixture
def world():
    w = World(40, 40, [["g"] * 40 for _ in range(40)], Catalog.load())
    w.tick = START_TICK + 100
    w.catalog.add_invention({"id": "inv_spark_fragments", "name": "spark fragments", "desc": "x", "food": 0,
                             "placeable": True, "inputs": {"flint": 2, "stone": 2}})
    w.catalog.add_invention({"id": "inv_blanket", "name": "warm reed blanket", "desc": "x", "food": 0,
                             "placeable": True, "inputs": {"plant_fiber": 3}})
    return w


def make(w, name, x):
    c = Creature(f"c{len(w.creatures) + 1}", name, x, 10, asleep=False)
    w.creatures[c.id] = c
    return c


def test_give_unheld_known_recipe_names_recipe_and_shortfall(world):
    tula, una = make(world, "Tula", 10), make(world, "Una", 11)
    tula.known_recipes.add("inv_spark_fragments")
    tula.inventory["stone"] = 1
    res = apply_intention(world, tula, Intention("give", target="Una", items=["spark fragments"]))
    assert not res.ok
    assert res.message.startswith("You don't have any spark fragments.")
    assert "You know how to make it: 2 flint + 2 stone" in res.message
    assert "no flint" in res.message and "no stone" not in res.message


def test_place_unheld_known_recipe(world):
    mirth = make(world, "Mirth", 10)
    mirth.known_recipes.add("inv_blanket")
    mirth.inventory["plant_fiber"] = 1
    res = apply_intention(world, mirth, Intention("place", target="warm reed blanket"))
    assert not res.ok
    assert res.message.startswith("You don't have a warm reed blanket to place.")
    assert "3 plant fiber" in res.message and "only 1 plant fiber" in res.message


def test_material_gets_source_hint(world):
    c = make(world, "Tam", 10)
    make(world, "Una", 11)
    res = apply_intention(world, c, Intention("give", target="Una", items=["stick"]))
    assert not res.ok and "break them off trees" in res.message


def test_unknown_recipe_or_item_unchanged(world):
    c = make(world, "Tam", 10)
    make(world, "Una", 11)
    res = apply_intention(world, c, Intention("give", target="Una", items=["spark fragments"]))
    assert res.message == "You don't have any spark fragments."
    res = apply_intention(world, c, Intention("place", target="warm reed blanket"))
    assert res.message == "You don't have a warm reed blanket to place."
    res = apply_intention(world, c, Intention("give", target="Una", items=["zzzz"]))
    assert res.message == "You don't know of anything called 'zzzz'."


def test_a_crafting_shortfall_says_how_to_make_the_missing_ingredient(world):
    # Teo tried "craft strong cord" 9 times: "you need 2 rope, but you have 1", never told that rope is 3 plant fiber
    world.catalog.add_invention({"id": "inv_strong_cord", "name": "strong cord", "desc": "x", "food": 0,
                                 "placeable": True, "inputs": {"rope": 2}})  # an invention in the live world
    c = make(world, "Teo", 10)
    c.inventory["rope"] = 1
    c.known_recipes |= {"rope", "inv_strong_cord"}
    res = apply_intention(world, c, Intention("craft", target="strong cord"))
    assert not res.ok and "need 2 rope, but you have 1" in res.message
    assert "You know how to make rope:" in res.message and "no plant fiber" in res.message


def test_a_raw_material_shortfall_keeps_its_source_hint(world):
    c = make(world, "Ann", 10)
    c.inventory["plant_fiber"] = 1
    c.known_recipes.add("rope")
    res = apply_intention(world, c, Intention("craft", target="rope"))
    assert not res.ok and "Plant fiber:" in res.message and "You know how to make" not in res.message


def test_holding_the_ingredients_says_craft_it_first(world):
    # 38 failed gives in an hour: "You don't have any rope. You know how to make it: 3 plant fiber -> rope." while
    # holding the fiber; nothing said it was all there
    gale = make(world, "Gale", 10)
    make(world, "Teo", 11)
    gale.inventory["plant_fiber"] = 4
    gale.known_recipes.add("rope")
    res = apply_intention(world, gale, Intention("give", target="Teo", items=["rope"]))
    assert not res.ok and "3 plant fiber -> rope; you have the ingredients, so craft it first." in res.message
