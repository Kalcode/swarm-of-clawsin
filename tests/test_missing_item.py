from collections import Counter

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


def test_craft_it_first_only_when_a_craft_would_work(world):
    c = make(world, "Gale", 10)
    make(world, "Teo", 11)
    c.inventory["fish"] = 2
    c.known_recipes.add("cooked_fish")  # needs a campfire, and none is near
    res = apply_intention(world, c, Intention("give", target="Teo", items=["cooked fish"]))
    assert not res.ok and "fish -> cooked fish" in res.message and "craft it first" not in res.message
    # inside a crafting shortfall it isn't said: making rope eats the fiber the fishing rod needs too
    c.inventory.update({"stick": 2, "plant_fiber": 3})
    c.known_recipes |= {"rope", "fishing_rod"}
    res = apply_intention(world, c, Intention("craft", target="fishing rod"))
    assert not res.ok and "You know how to make rope:" in res.message and "craft it first" not in res.message


def test_an_item_on_the_ground_in_sight_says_go_and_pick_it_up(world):
    # Mirth: "I have 6 rope on the ground... so just put them in", 13 times; told to craft rope, never to pick it up
    mirth = make(world, "Mirth", 10)
    make(world, "Suki", 11)
    mirth.inventory["plant_fiber"] = 4
    mirth.known_recipes.add("rope")
    world.ground[(14, 14)] = Counter({"rope": 6})
    res = apply_intention(world, mirth, Intention("give", target="Suki", items=["rope"]))
    assert not res.ok and res.message.startswith("You don't have any rope.")
    assert '6 rope lie on the ground 4 steps southeast: walk_to "rope", then pick_up "rope".' in res.message
    assert "craft it first" not in res.message  # picking it up beats making it
    world.ground[(11, 11)] = Counter({"rope": 2})
    res = apply_intention(world, mirth, Intention("give", target="Suki", items=["rope"]))
    assert '2 rope lie on the ground right beside you to the southeast: pick_up "rope".' in res.message


def test_a_source_hint_names_the_nearest_source_in_sight(world):
    # Gus tried to feed a campfire sticks he didn't have 23 times: "Stick: break them off trees." Which tree?
    gus = make(world, "Gus", 10)
    make(world, "Tula", 11)
    tree = world.add_object("tree", 13, 10)
    world.add_object("tree", 20, 10)  # farther
    res = apply_intention(world, gus, Intention("give", target="Tula", items=["stick"]))
    assert not res.ok and f"Stick: break them off trees; the nearest {tree.name} is 3 steps east." in res.message


def test_no_source_in_sight_keeps_the_plain_hint(world):
    c = make(world, "Tam", 10)
    make(world, "Una", 11)
    res = apply_intention(world, c, Intention("give", target="Una", items=["stick"]))
    assert res.message == "You don't have any stick. Stick: break them off trees."


def test_a_used_up_source_is_not_named(world):
    c = make(world, "Tam", 10)
    make(world, "Una", 11)
    world.add_object("driftwood", 12, 10, uses=0)  # gathered out until it regrows
    pine = world.add_object("pine", 15, 10)
    res = apply_intention(world, c, Intention("give", target="Una", items=["stick"]))
    assert f"the nearest {pine.name} is 5 steps east." in res.message
