from swarmworld.server.persistence import restore, save
from swarmworld.server.state import ServerState
from swarmworld.world.actions import Intention, apply_intention


def test_save_and_restore_roundtrip(tmp_path):
    st = ServerState(seed=7)
    c = st.new_creature("mock")
    c.inventory.update({"stick": 2, "stone_axe": 1})
    c.known_recipes.add("stone_axe")
    c.spots["rock"] = (3, 4, 100)
    st.memory(c.id).goal = "build a hut"
    st.memory(c.id).add(st.world.tick, "I met Mara.", 2)
    apply_intention(st.world, c, Intention("gather", target="grass"))
    st.world.discoveries["stone_axe"] = {"item": "stone_axe", "by": c.name, "tick": 5}
    st.owner[c.id] = "laptop"
    n_objects = len(st.world.objects)
    path = tmp_path / "world.json"
    save(st, path)

    st2 = ServerState(seed=99)
    restore(st2, path)
    c2 = st2.world.creatures[c.id]
    assert c2.name == c.name and c2.inventory["stone_axe"] == 1 and "stone_axe" in c2.known_recipes
    assert c2.spots["rock"] == (3, 4, 100)
    assert c2.asleep  # wakes when its brain node rejoins
    assert st2.memory(c.id).goal == "build a hut" and "I met Mara." in st2.memory(c.id).recent()
    assert len(st2.world.objects) == n_objects
    assert st2.world.discoveries["stone_axe"]["by"] == c.name
    assert st2.owner[c.id] == "laptop"
    assert st2.sim.world is st2.world
    new = st2.new_creature("mock")
    assert new.id not in {c.id}


def test_metrics_survive_restart(tmp_path):
    st = ServerState(seed=7)
    st.metrics.bump("qwen", "act_ok", 5)
    st.metrics.item("qwen", "stone_axe")
    save(st, tmp_path / "w.json")
    st2 = ServerState(seed=7)
    restore(st2, tmp_path / "w.json")
    assert st2.metrics.models["qwen"]["act_ok"] == 5 and "stone_axe" in st2.metrics.items["qwen"]


def test_inventions_survive_restart(tmp_path):
    st = ServerState(seed=7)
    st.world.catalog.add_invention({"id": "inv_sun_totem", "name": "sun totem", "desc": "A tall carved post.",
                                    "food": 0, "placeable": True, "inputs": {"log": 2, "stone": 1}, "station": "campfire"})
    save(st, tmp_path / "w.json")
    st2 = ServerState(seed=7)
    restore(st2, tmp_path / "w.json")
    assert st2.world.catalog.resolve("sun totem") == "inv_sun_totem"
    assert st2.world.catalog.recipe_for("inv_sun_totem").inputs == {"log": 2, "stone": 1}
