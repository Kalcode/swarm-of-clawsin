import pytest

from swarmworld.world.actions import Intention, apply_intention, parse_intention, step_activity
from swarmworld.world.catalog import Catalog
from swarmworld.world.model import START_TICK, Creature, World


@pytest.fixture
def world():
    tiles = [["g"] * 40 for _ in range(40)]
    w = World(40, 40, tiles, Catalog.load())
    w.tick = START_TICK + 100
    return w


def creature(w, name="Tam", x=10, y=10):
    c = Creature(f"c{len(w.creatures) + 1}", name, x, y, asleep=False)
    c.known_recipes = {r.output for r in w.catalog.recipes if r.known_at_start}
    w.creatures[c.id] = c
    return c


def act(w, c, **kw):
    res = apply_intention(w, c, Intention(**kw))
    while c.activity:
        step_activity(w, c)
    return res


def test_parse_intention_variants():
    it = parse_intention('Sure! ```json\n{"thought":"hm","action":"Chop","target":"oak","items":"stick, stone","count":9}\n```')
    assert it.action == "gather" and it.items == ["stick", "stone"] and it.count == 5
    assert parse_intention({"action": "walk_to", "target": "Mara"}).target == "Mara"


def test_bad_intentions_are_refused(world):
    assert parse_intention("not json") is None
    assert parse_intention({"action": "fly"}) is None
    assert parse_intention(None) is None
    c = creature(world)
    res = apply_intention(world, c, Intention("gather"))
    assert not res.ok and "nothing to gather" in res.message.lower()
    res = apply_intention(world, c, Intention("say"))
    assert not res.ok


def test_target_must_be_perceived(world):
    c = creature(world)
    world.add_object("tree", 30, 10, wood=6)
    res = apply_intention(world, c, Intention("walk_to", target="tree"))
    assert not res.ok and "don't see" in res.message
    other = creature(world, "Mara", 11, 10)
    res = apply_intention(world, c, Intention("give", target="Mara", items=["stone axe"]))
    assert not res.ok and "don't have" in res.message


def test_walk_to_arrives(world):
    c = creature(world)
    world.add_object("tree", 15, 12, wood=6)
    res = apply_intention(world, c, Intention("walk_to", target="the oak tree"))
    assert res.ok and not res.instant
    final = None
    for _ in range(20):
        final = step_activity(world, c) or final
        if c.activity is None:
            break
    assert final and final.ok and "arrive" in final.message
    assert max(abs(c.x - 15), abs(c.y - 12)) == 1


def test_gather_and_combine_discovers_axe(world):
    c = creature(world)
    world.add_object("tree", 11, 10, wood=6)
    world.add_object("rock", 9, 10)
    assert act(world, c, action="gather", target="tree", count=2).ok
    assert act(world, c, action="gather", target="rock", count=2).ok
    assert act(world, c, action="gather", target="grass", count=3).ok
    assert c.inventory["stick"] == 2 and c.inventory["stone"] >= 2 and c.inventory["plant_fiber"] == 3
    assert act(world, c, action="craft", target="rope").ok  # known at start
    res = act(world, c, action="craft", target="stone axe")
    assert not res.ok and "don't know" in res.message
    res = act(world, c, action="combine", items=["stick", "stone", "rope"])
    assert res.ok and "Eureka" in res.message
    assert c.inventory["stone_axe"] == 1 and "stone_axe" in c.known_recipes
    assert world.discoveries["stone_axe"]["by"] == "Tam"
    act(world, c, action="gather", target="tree")
    assert c.inventory["log"] == 3  # an unspecified count gathers a handful


def test_station_required(world):
    c = creature(world)
    c.inventory.update({"berries": 2, "stick": 3, "stone": 2})
    res = act(world, c, action="combine", items=["berries"])
    assert not res.ok and "campfire" in res.message
    assert act(world, c, action="place", target="campfire").ok is False  # don't have one yet
    assert act(world, c, action="craft", target="campfire").ok
    assert act(world, c, action="place", target="campfire").ok
    res = act(world, c, action="combine", items=["berries"])
    assert res.ok and c.inventory["roasted_berries"] == 1


def test_sign_write_and_read(world):
    c = creature(world)
    c.inventory.update({"sign": 1})
    assert act(world, c, action="place", target="sign").ok
    assert act(world, c, action="write", text="stick + stone + rope makes an axe").ok
    sign = next(o for o in world.objects.values() if o.kind == "sign")
    other = creature(world, "Mara", sign.x, sign.y + 1)
    res = act(world, other, action="read", target="sign")
    assert res.ok and "makes an axe" in res.message and "Tam" in res.message


def test_walk_to_beside_is_a_noop_and_the_repeat_gathers(world):
    c = creature(world)
    world.add_object("bush", 11, 10, berries=4)
    first = apply_intention(world, c, Intention("walk_to", target="berry bush"))
    assert first.ok and first.noop and not c.inventory.get("berries")
    second = apply_intention(world, c, Intention("walk_to", target="berry bush"))
    assert second.ok and not second.noop and c.inventory.get("berries", 0) > 0
    third = apply_intention(world, c, Intention("walk_to", target="berry bush"))
    assert third.noop  # a fresh no-op after a useful turn


def test_repeated_walk_to_a_sign_beside_you_reads_it(world):
    c = creature(world)
    world.add_object("sign", 11, 10, text="Clay by the river")
    apply_intention(world, c, Intention("walk_to", target="sign"))
    res = apply_intention(world, c, Intention("walk_to", target="sign"))
    assert res.ok and "Clay by the river" in res.message


def test_noop_survives_speaking_while_acting(world):
    c = creature(world)
    world.add_object("bush", 11, 10, berries=4)
    res = apply_intention(world, c, Intention("walk_to", target="berry bush", speech="Nice bush."))
    assert res.noop


def test_inventing_a_known_thing_makes_it(world):
    c = creature(world)
    c.inventory.update({"stick": 1, "stone": 1, "rope": 1})
    res = act(world, c, action="invent", target="stone axe", items=["stick", "stone", "rope"])
    assert res.ok and c.inventory.get("stone_axe") == 1 and "already exists" in res.message
    c.inventory.update({"plant_fiber": 3})
    assert act(world, c, action="invent", target="rope").ok and c.inventory.get("rope") == 1  # known recipe: craft


def test_myth_hint_only_for_names_of_things(world):
    c = creature(world)
    creature(world, "Mara", 35, 35)  # out of sight, but they know her name
    for hint in ("nothing", "the ground", "my inventory", "Mara", "3 sticks", "a very long name for a big thing"):
        c.inventory.update({"stick": 1, "berries": 1})
        res = act(world, c, action="combine", items=["stick", "berries"], target=hint)
        assert "No one has ever made" not in res.message, hint
    res = act(world, c, action="combine", items=["stick", "berries"], target="berry wand")
    assert "No one has ever made a 'berry wand'" in res.message


def test_walk_to_and_gather_use_remembered_spots(world):
    c = creature(world)
    world.add_object("rock", 30, 10)
    c.spots["rock"] = (30, 10, world.tick)  # seen yesterday, far out of sight now
    res = act(world, c, action="walk_to", target="boulder")
    assert res.ok and max(abs(c.x - 30), abs(c.y - 10)) == 1
    c.x, c.y = 10, 10
    res = act(world, c, action="gather", target="stone")
    assert c.inventory.get("stone", 0) > 0


def test_inventions_need_a_real_name(world):
    c = creature(world)
    c.inventory.update({"stick": 2, "berries": 2, "plant_fiber": 2})
    for name in ("new invention", "device", "a thing", "new tool"):
        res = act(world, c, action="invent", target=name, items=["stick", "berries", "plant fiber"])
        assert not res.ok and "real name" in res.message, name
    assert act(world, c, action="invent", target="berry whisk", items=["stick", "berries", "plant fiber"]).ok


def test_gather_at_a_campfire_explains_tending(world):
    c = creature(world)
    world.add_object("campfire", 11, 10, lit=True)
    res = act(world, c, action="gather", target="campfire")
    assert res.ok and res.noop and "give it sticks" in res.message


def test_gather_from_a_basket_takes_from_it(world):
    c = creature(world)
    world.add_object("basket", 11, 10, items={"stick": 3})
    assert act(world, c, action="gather", target="basket", items=["stick"]).ok and c.inventory["stick"] > 0


def test_place_uses_the_structure_named_in_items(world):
    c = creature(world)
    c.inventory.update({"campfire": 1, "plant_fiber": 3})
    assert act(world, c, action="place", target="grass", items=["campfire"]).ok and not c.inventory.get("campfire")
    assert any(o.kind == "campfire" for o in world.objects.values())


def test_a_source_name_means_what_it_gives(world):
    c = creature(world)
    c.satiety = 30
    c.inventory["berries"] = 2
    assert act(world, c, action="eat", target="berry bush").ok and c.satiety > 30


def test_pick_up_what_grows_here_gathers_it(world):
    c = creature(world)  # standing in a meadow
    assert act(world, c, action="pick_up", target="tall grass").ok and c.inventory.get("plant_fiber", 0) > 0
    assert not act(world, c, action="pick_up", target="rope").ok  # nothing to gather: still a plain failure


def test_walk_gets_as_close_as_it_can(world):
    c = creature(world)
    for y in range(40):
        world.tiles[y][20] = "W"  # deep water nobody can cross
    world.add_object("rock", 30, 10)
    c.spots["rock"] = (30, 10, world.tick)
    res = act(world, c, action="walk_to", target="boulder")
    assert res.ok and c.x == 19 and "as close as you can" in res.message


def test_shortfall_says_where_material_comes_from(world):
    c = creature(world)
    c.inventory.update({"plant_fiber": 1})
    res = act(world, c, action="craft", target="rope")
    assert not res.ok and "grass" in res.message


def test_eating_a_ripe_crop_beside_you_harvests_and_eats_it(world):
    c = creature(world)
    c.satiety = 10
    world.add_object("crop", 11, 10, crop="carrot", stage=2)
    res = act(world, c, action="eat", target="carrot")
    assert res.ok and c.satiety > 10 and not any(o.kind == "crop" for o in world.objects.values())
    world.add_object("crop", 11, 10, crop="carrot", stage=0)
    res = act(world, c, action="eat", target="carrot")
    assert not res.ok and "ripe" in res.message


def test_eating_from_a_mushroom_patch_beside_you_picks_and_eats(world):
    c = creature(world)
    c.satiety = 10
    patch = world.add_object("mushroom_patch", 11, 10)
    res = act(world, c, action="eat", target="mushroom")
    assert res.ok and c.satiety > 10 and "mushroom patch" in res.message
    assert patch.data["uses"] == 1  # one use of its two
    assert [e for e in world.events if e.kind == "eat"]


def test_eating_wild_food_out_of_reach_says_where_it_grows(world):
    c = creature(world)
    c.satiety = 10
    res = act(world, c, action="eat", target="mushroom")
    assert not res.ok and res.message == "You don't have any mushroom."  # beside nothing: as before
    world.add_object("herb_patch", 14, 10)
    res = act(world, c, action="eat", target="herbs")
    assert not res.ok and "wild herbs 4 steps east" in res.message and c.satiety == 10


def test_say_emits_event(world):
    c = creature(world)
    creature(world, "Mara", 12, 10)
    res = act(world, c, action="say", target="Mara", text="hello!")
    assert res.ok
    ev = [e for e in world.events if e.kind == "say"][-1]
    assert ev.data["to_name"] == "Mara" and ev.data["line"] == "hello!"


def test_say_with_words_only_in_speech_is_heard_once(world):
    c = creature(world)
    creature(world, "Mara", 12, 10)
    res = act(world, c, action="say", target="Mara", speech="Want to build a fire?")
    assert res.ok
    said = [e for e in world.events if e.kind == "say"]
    assert len(said) == 1 and said[0].data["line"] == "Want to build a fire?" and said[0].data["to_name"] == "Mara"


def test_eat_and_drink(world):
    c = creature(world)
    c.satiety = 30
    c.inventory["berries"] = 2
    assert act(world, c, action="eat", target="berries", count=2).ok
    assert c.satiety == 60
    assert not act(world, c, action="drink").ok
    world.tiles[10][11] = "w"
    assert act(world, c, action="drink").ok


def test_seeds_are_a_poor_meal_in_a_pinch(world):
    c = creature(world)
    c.satiety = 20
    c.inventory.update({"wheat_seeds": 2, "berries": 1})
    assert act(world, c, action="eat").ok  # no target: the best food goes first
    assert not c.inventory.get("berries") and c.inventory["wheat_seeds"] == 2
    before = c.satiety
    assert act(world, c, action="eat", target="wheat seeds").ok
    assert c.satiety == before + 2 * 3 and not c.inventory.get("wheat_seeds")


def test_gather_far_walks_then_gathers(world):
    c = creature(world)
    world.add_object("bush", 14, 10, berries=4)
    res = apply_intention(world, c, Intention("gather", target="berry bush", count=2))
    assert res.ok and not res.instant
    final = None
    for _ in range(30):
        r = step_activity(world, c)
        final = r or final
        if c.activity is None:
            break
    assert c.inventory["berries"] == 2
    assert final and "arrive" in final.message and "berries" in final.message


def test_counts_in_item_names(world):
    assert world.catalog.resolve("3 stick") == "stick"
    assert world.catalog.resolve("stone x2") == "stone"
    c = creature(world)
    c.inventory.update({"stick": 3, "stone": 2})
    assert act(world, c, action="combine", items=["3 stick", "2 stone"]).ok
    assert c.inventory["campfire"] == 1


def test_combine_superset_and_near_miss(world):
    c = creature(world)
    c.inventory.update({"flint": 1, "stick": 2, "stone": 1})
    res = act(world, c, action="combine", items=["flint", "stick", "stone"])
    assert res.ok and c.inventory["stone_knife"] == 1
    c.inventory.update({"stick": 1, "rope": 1})
    res = act(world, c, action="combine", items=["stick", "rope"])  # stone axe also needs stone
    assert not res.ok and "missing" in res.message


def test_walk_to_remembered_creature(world):
    c = creature(world)
    c.seen_pos["mara"] = (25, 10, world.tick)
    res = apply_intention(world, c, Intention("walk_to", target="Mara"))
    assert res.ok and "last saw" in c.activity["label"]


def test_farming_cycle(world):
    from swarmworld.world.simulation import Simulation
    sim = Simulation(world)
    c = creature(world)
    c.inventory.update({"wheat_seeds": 2})
    res = act(world, c, action="plant", target="seeds")
    assert not res.ok and "tool" in res.message
    c.inventory["hoe"] = 1
    assert act(world, c, action="plant", target="wheat seeds", count=2).ok
    crops = [o for o in world.objects.values() if o.kind == "crop"]
    assert len(crops) == 2
    assert not act(world, c, action="gather", target="wheat").ok  # not ripe
    for _ in range(620):
        sim.tick()
    assert all(o.data["stage"] == 2 and o.name == "ripe wheat" for o in crops)
    c.activity = None
    assert act(world, c, action="gather", target="ripe wheat").ok
    assert c.inventory["wheat"] == 3


def test_recipe_choice_prefers_wanted_and_ready(world):
    c = creature(world)
    c.inventory.update({"log": 2, "stone_axe": 1})
    res = act(world, c, action="combine", items=["log"])
    assert res.ok and c.inventory["planks"] == 2  # planks are ready (axe held), charcoal needs a fire
    c.inventory.update({"stick": 3, "stone": 2})
    act(world, c, action="craft", target="campfire")
    act(world, c, action="place", target="campfire")
    res = act(world, c, action="combine", items=["log"], target="charcoal")
    assert res.ok and c.inventory["charcoal"] == 1


def test_fishing(world):
    world.tiles[10][12] = "w"
    c = creature(world)
    res = act(world, c, action="gather", target="fish")
    assert not res.ok or c.activity is None  # walks to water first, then needs a rod
    c.x, c.y = 11, 10
    res = act(world, c, action="gather", target="water")
    assert not res.ok and "catch them" in res.message
    c.inventory["fishing_rod"] = 1
    world.rng.seed(1)
    res = act(world, c, action="gather", target="fish", count=5)
    caught = {i: n for i, n in c.inventory.items() if i != "fishing_rod" and n > 0}
    assert res.ok and caught and c.inventory["fishing_rod"] == 1  # what bit (the food pack names the species)
    assert all(world.catalog.items[i].food > 0 for i in caught), caught


def test_eat_from_bush_and_forgiving_combine(world):
    c = creature(world)
    world.add_object("bush", 11, 10, berries=6)
    c.satiety = 30
    res = act(world, c, action="eat", target="berry bush")
    assert res.ok and c.satiety == 45
    c.inventory.update({"log": 1, "stone_axe": 1})
    res = act(world, c, action="combine", items=["stone axe", "log"])
    assert res.ok and c.inventory["planks"] == 2
    c.inventory.update({"flint": 1, "stick": 1})
    res = act(world, c, action="combine", items=["flint", "stick", "unicorn horn"])
    assert res.ok and c.inventory["stone_knife"] == 1


def test_taming_and_eggs(world):
    c = creature(world)
    hen = world.add_object("chicken", 11, 10)
    c.inventory.update({"wheat_seeds": 3})
    res = act(world, c, action="gather", target="chicken")
    assert not res.ok and "shies away" in res.message
    hen = next(o for o in world.objects.values() if o.kind == "chicken")
    c.x, c.y = hen.x - 1, hen.y
    assert act(world, c, action="give", target="chicken", items=["wheat seeds"]).ok
    res = act(world, c, action="give", target="chicken", items=["wheat seeds"])
    assert res.ok and hen.data["tamed_by"] == "Tam" and "eggs" in res.message
    world.tick += 200
    c.x, c.y = hen.x - 1, hen.y
    assert act(world, c, action="gather", target="chicken").ok and c.inventory["egg"] == 1


def test_invent_new_food_and_others_can_combine_it(world):
    c = creature(world)
    c.inventory.update({"berries": 4, "wheat": 2, "stick": 3, "stone": 2, "campfire": 1})
    c.inventory["campfire"] = 1
    assert act(world, c, action="place", target="campfire").ok
    res = act(world, c, action="invent", target="berry cake", items=["berries", "wheat"], text="A sweet cake to eat.")
    assert res.ok and c.inventory["inv_berry_cake"] == 1
    item = world.catalog.items["inv_berry_cake"]
    assert item.food > 0 and not item.placeable
    assert not act(world, c, action="invent", target="stone seat", items=["stick", "stone"]).ok  # campfire recipe exists / once a day
    other = creature(world, "Mara", c.x, c.y + 1)
    other.inventory.update({"berries": 2, "wheat": 2})
    res = act(world, other, action="combine", items=["berries", "wheat"])
    assert res.ok and other.inventory["inv_berry_cake"] == 1
    # a fresh world from the shared catalog doesn't know the invention
    from swarmworld.world.catalog import Catalog
    assert "inv_berry_cake" not in Catalog.load().items


def test_combine_reads_ingredients_from_target_too(world):
    c = creature(world)
    c.inventory.update({"flint": 1, "stick": 1})
    res = act(world, c, action="combine", target="stick, flint", items=["flint"])
    assert res.ok and c.inventory["stone_knife"] == 1
    c.inventory.update({"log": 1, "stone_axe": 1, "stick": 3, "stone": 2})
    act(world, c, action="craft", target="campfire")
    act(world, c, action="place", target="campfire")
    res = act(world, c, action="combine", target="charcoal", items=["log"])
    assert res.ok and c.inventory["charcoal"] == 1


def test_invented_tool_helps_gathering(world):
    c = creature(world)
    c.inventory.update({"stone": 3, "flint": 2, "stick": 2, "campfire": 1})
    act(world, c, action="place", target="campfire")
    res = act(world, c, action="invent", target="stone hammer", items=["stone", "flint"], text="a heavy hammer for smashing")
    assert res.ok and "tool" in res.message
    item = world.catalog.items["inv_stone_hammer"]
    assert not item.placeable and "tool" in item.tags
    rock = world.add_object("rock", c.x, c.y - 1) if not world.object_at(c.x, c.y - 1) else world.object_at(c.x, c.y - 1)
    before = c.inventory["stone"] + c.inventory["flint"]
    res = act(world, c, action="gather", target="boulder", count=2)
    assert res.ok and "helps" in res.message
    assert c.inventory["stone"] + c.inventory["flint"] - before >= 3


def test_gather_item_finds_its_source_and_give_walks(world):
    c = creature(world)
    world.add_object("tree", 14, 10, wood=6)
    res = apply_intention(world, c, Intention("gather", target="stick"))
    assert res.ok and not res.instant
    for _ in range(30):
        step_activity(world, c)
        if c.activity is None:
            break
    assert c.inventory["stick"] >= 1
    other = creature(world, "Mara", c.x + 4, c.y + 2)
    res = apply_intention(world, c, Intention("give", target="Mara", items=["stick"]))
    assert res.ok
    for _ in range(30):
        step_activity(world, c)
        if c.activity is None:
            break
    assert other.inventory["stick"] >= 1


def test_named_known_recipe_reminder(world):
    c = creature(world)
    c.inventory.update({"stone": 4})
    res = act(world, c, action="combine", target="campfire", items=["stone"])
    assert not res.ok and "3 stick + 2 stone" in res.message


def test_inventions_can_build_on_inventions(world):
    c = creature(world)
    c.inventory.update({"stone": 6, "flint": 4, "stick": 4})
    assert act(world, c, action="invent", target="stone hammer", items=["stone", "flint"], text="a heavy hammer").ok
    world.tick += 1300  # next day
    res = act(world, c, action="invent", target="stone chisel", items=["stone hammer", "stick", "stone"], text="splits stone with the hammer")
    assert res.ok, res.message
    chisel = next(v for v in world.catalog.inventions if v["name"] == "stone chisel")
    assert chisel["depth"] == 2 and "inv_stone_hammer" in chisel["inputs"]


def test_invented_shelter_and_light_have_effects(world):
    from swarmworld.world.perception import sight_range
    c = creature(world)
    c.inventory.update({"stick": 6, "plant_fiber": 4, "stone": 4, "flint": 2})
    res = act(world, c, action="invent", target="grass hut", items=["stick", "plant fiber", "stone"], text="a little shelter to sleep in")
    assert res.ok and "like a bed" in res.message
    assert act(world, c, action="place", target="grass hut").ok
    res = act(world, c, action="rest")
    assert "bed" in res.message
    world.tick += 1300
    res = act(world, c, action="invent", target="flint torch", items=["stick", "flint", "plant fiber"], text="a torch that lights the night")
    assert res.ok and "lights up the night" in res.message
    assert act(world, c, action="place", target="flint torch").ok
    world.tick = 2 * 1200 + 1000  # night
    assert sight_range(world, c) == 5


def test_no_two_creatures_on_one_tile(world):
    a = creature(world, "Tam", 10, 10)
    b = creature(world, "Mara", 12, 10)  # standing in the way
    world.add_object("tree", 14, 10, wood=6)
    assert apply_intention(world, a, Intention("walk_to", target="oak tree")).ok
    seen = set()
    for _ in range(30):
        step_activity(world, a)
        assert (a.x, a.y) != (b.x, b.y)
        seen.add((a.x, a.y))
        if a.activity is None:
            break
    assert max(abs(a.x - 14), abs(a.y - 10)) <= 1


def test_speaking_to_a_sleeper(world):
    a = creature(world, "Tam", 10, 10)
    b = creature(world, "Mara", 11, 10)
    b.asleep = True
    res = act(world, a, action="say", target="Mara", text="Wake up!")
    assert res.ok and "fast asleep" in res.message
    from swarmworld.world.perception import perceive
    assert "fast asleep" in perceive(world, a)


def test_animals_block_walking(world):
    world.add_object("cow", 11, 10)
    assert not world.walkable(11, 10)


def test_carving_and_learning_by_reading(world):
    a = creature(world, "Tam", 10, 10)
    world.add_object("tree", 11, 10, wood=6)
    res = act(world, a, action="write", text="Flint and a stick make a stone knife.")
    assert res.ok and "oak tree" in res.message
    b = creature(world, "Mara", 12, 11)
    from swarmworld.world.perception import perceive
    assert "words carved into it" in perceive(world, b)
    res = act(world, b, action="read", target="carving")
    assert res.ok and "stone knife" in res.message and "stone_knife" in b.known_recipes
    assert any(e.kind == "learn" and e.data["how"] == "reading" for e in world.events)


def test_explore_turns_at_the_edge_and_animals_arent_food(world):
    c = creature(world, "Tam", 10, 0)  # top edge
    res = apply_intention(world, c, Intention("explore", target="north"))
    assert res.ok and "turn" in res.message
    c2 = creature(world, "Mara", 20, 20)
    res = act(world, c2, action="eat", target="chicken")
    assert not res.ok and "live animal" in res.message


def test_known_recipe_among_extra_items(world):
    c = creature(world)
    c.inventory.update({"plant_fiber": 3, "clay": 1})
    res = act(world, c, action="combine", items=["plant fiber", "clay"])
    assert res.ok and c.inventory["rope"] == 1 and c.inventory["clay"] == 1


def test_shared_basket_and_tending_fire(world):
    a = creature(world, "Tam", 10, 10)
    a.inventory.update({"plant_fiber": 4, "stick": 3, "berries": 5})
    assert act(world, a, action="combine", items=["plant fiber", "stick"]).ok and a.inventory["basket"] == 1
    assert act(world, a, action="place", target="basket").ok
    res = act(world, a, action="store", target="basket", items=["berries"])
    assert res.ok and a.inventory["berries"] == 0
    b = creature(world, "Mara", 12, 10)
    res = act(world, b, action="take", target="basket", items=["berries"], count=3)
    assert res.ok and b.inventory["berries"] == 3
    from swarmworld.world.perception import perceive
    assert "basket (holding 2 berries)" in perceive(world, b)
    fire = world.add_object("campfire", 10, 11, lit=False, lit_until=0)
    res = act(world, a, action="give", target="campfire", items=["stick"])
    assert res.ok and fire.data["lit"] and "relight" in res.message


def test_teach_passes_on_a_recipe(world):
    from swarmworld.world.simulation import Simulation
    sim = Simulation(world)
    a = creature(world, "Tam", 10, 10)
    b = creature(world, "Mara", 13, 10)
    a.known_recipes.add("stone_knife")
    assert not act(world, a, action="teach", target="Mara", items=["stone axe"]).ok  # doesn't know it
    res = act(world, a, action="teach", target="Mara", items=["stone knife"])
    assert res.ok
    sim.tick()
    assert "stone_knife" in b.known_recipes
    assert any(e.kind == "learn" and e.data.get("how") == "listening" for e in world.events)


def test_talking_while_working(world):
    from swarmworld.world.simulation import Simulation
    sim = Simulation(world)
    a = creature(world, "Tam", 10, 10)
    b = creature(world, "Mara", 12, 10)
    world.add_object("bush", 11, 11, berries=6)
    it = parse_intention({"action": "gather", "target": "berry bush", "speech": "Mara, berries over here!"})
    res = apply_intention(world, a, it)
    assert res.ok and "you say" in res.message
    sim.tick()
    assert a.inventory["berries"] >= 1
    assert any(e.kind == "say" and e.data.get("to_name") == "Mara" for e in world.events)


def test_myth_can_become_an_invention(world):
    c = creature(world)
    c.inventory.update({"rope": 2, "berries": 2})
    res = act(world, c, action="combine", target="berry-rope", items=["rope", "berries"])
    assert not res.ok and "could invent it" in res.message
    res = act(world, c, action="invent", target="berry-rope", items=["rope", "berries"], text="a warm rope rubbed with berries")
    assert res.ok and "inv_berry_rope" in c.inventory


def test_a_gather_that_yields_nothing_spends_no_use(world, monkeypatch):
    from swarmworld.world.registry import YIELDS
    c = creature(world)
    patch = world.add_object("herb_patch", 11, 10)
    uses = YIELDS["herb_patch"]["uses"]
    monkeypatch.setitem(YIELDS, "herb_patch", dict(YIELDS["herb_patch"], items={"herbs": [0, 0]}))
    act(world, c, action="gather", target="herb patch")
    assert not c.inventory.get("herbs") and patch.kind == "herb_patch"
    assert patch.data.get("uses", uses) == uses  # nothing came of it, so nothing was used up
    monkeypatch.setitem(YIELDS, "herb_patch", dict(YIELDS["herb_patch"], items={"herbs": [1, 1]}))
    assert act(world, c, action="gather", target="herb patch").ok and c.inventory["herbs"] == 1
    assert patch.data["uses"] == uses - 1


def test_one_set_of_water_kinds_for_drinking_and_filling(world):
    from swarmworld.world import actions
    from swarmworld.world.packs import food
    from swarmworld.world.registry import KINDS
    assert actions.water_kinds() == {k for k, spec in KINDS.items() if spec.get("water")} and "well" in KINDS
    assert "well" in actions.water_kinds()
    assert not hasattr(food, "_water_kinds") and food._busy is actions._busy  # the core's, not copies
    c = creature(world)
    world.add_object("well", 11, 10)
    assert act(world, c, action="drink").message == "You drink cool water and feel refreshed."
