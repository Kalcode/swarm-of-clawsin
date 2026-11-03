import json

from swarmworld.server.persistence import restore, save
from swarmworld.server.state import ServerState
from swarmworld.server.wishes import Wishes
from swarmworld.world.actions import Intention, apply_intention
from swarmworld.world.catalog import Catalog
from swarmworld.world.model import Event


def ev(kind, actor, text, **data):
    return Event(1000, kind, actor, 0, 0, text, data)


def test_wishes_come_from_speech_failures_and_the_wish_action():
    w = Wishes(Catalog.load())
    names = {"c1": "Inka", "c2": "Tam"}
    w.observe(ev("say", "c1", "", line="It's so wet, I wish we had a proper roof.", speaker="Inka"), names)
    w.observe(ev("say", "c2", "", line="If only we had a proper roof!", speaker="Tam"), names)
    w.observe(ev("say", "c2", "", line="I need to eat something.", speaker="Tam"), names)  # not a wish for a thing
    w.observe(ev("fail", "c1", "Inka tried to craft pattern key: You've never heard of a 'pattern key'."), names)
    w.observe(ev("wish", "c2", "", line="a boat to cross the lake"), names)
    ranked = w.ranked()
    assert [x["thing"] for x in ranked][:3] == ["boat to cross the lake", "pattern key", "proper roof"]  # wished, failed, then said
    roof = ranked[2]
    assert roof["creatures"] == 2 and roof["kinds"]["said"] == 2 and not roof["exists"]
    assert {x["thing"] for x in ranked} == {"proper roof", "pattern key", "boat to cross the lake"}
    assert next(x for x in ranked if x["thing"] == "pattern key")["kinds"]["failed"] == 1


def test_needs_for_things_that_exist_rank_below_true_wishes():
    w = Wishes(Catalog.load())
    names = {"c1": "Inka", "c2": "Tam"}
    w.observe(ev("say", "c1", "", line="We need more stone.", speaker="Inka"), names)
    w.observe(ev("say", "c2", "", line="We need stone!", speaker="Tam"), names)
    w.observe(ev("say", "c1", "", line="I wish we had a windmill.", speaker="Inka"), names)
    ranked = w.ranked()
    assert ranked[0]["thing"] == "windmill" and ranked[1]["thing"] == "stone" and ranked[1]["exists"]


def test_wish_action_at_the_wishing_stone():
    st = ServerState(seed=7)
    stones = [o for o in st.world.objects.values() if o.kind == "wishing_stone"]
    assert len(stones) == 1
    c = st.new_creature("mock")
    c.x, c.y = stones[0].x + 1, stones[0].y
    res = apply_intention(st.world, c, Intention("wish", text="a roof that keeps the rain off"))
    assert res.ok and "wishing stone" in res.message
    assert any(e.kind == "wish" and e.data.get("at_stone") for e in st.world.events)
    assert not apply_intention(st.world, c, Intention("wish")).ok


def test_answer_and_grant_reach_the_wisher():
    st = ServerState(seed=7)
    c = st.new_creature("mock")
    c.asleep = False
    st.wishes.observe(ev("say", c.id, "", line="I wish we had more rope.", speaker=c.name), {c.id: c.name})
    wid = st.wishes.ranked()[0]["id"]
    out = st.answer_wish(wid, reply="Look for tall grass by the river.", grant="rope", count=2)
    assert out["heard_by"] == [c.name] and out["granted_to"] == c.name and c.inventory["rope"] == 2
    assert any("Look for tall grass" in t for t in st.memory(c.id).recent())
    assert out["wish"]["status"] == "granted" and "2 rope" in out["wish"]["granted"]


def test_wishes_survive_a_restart(tmp_path):
    st = ServerState(seed=7)
    st.wishes.observe(ev("say", "c9", "", line="I wish we had a windmill.", speaker="Ola"), {"c9": "Ola"})
    save(st, tmp_path / "w.json")
    st2 = ServerState(seed=99)
    restore(st2, tmp_path / "w.json")
    assert st2.wishes.ranked()[0]["thing"] == "windmill"


def test_restoring_an_old_save_adds_the_wishing_stone(tmp_path):
    st = ServerState(seed=7)
    for o in [o for o in st.world.objects.values() if o.kind == "wishing_stone"]:
        st.world.remove_object(o.id)
    save(st, tmp_path / "old.json")
    data = json.loads((tmp_path / "old.json").read_text())
    assert not any(o["kind"] == "wishing_stone" for o in data["world"]["objects"])
    st2 = ServerState(seed=99)
    restore(st2, tmp_path / "old.json")
    assert sum(o.kind == "wishing_stone" for o in st2.world.objects.values()) == 1


def test_wish_phrases_read_cleanly():
    from swarmworld.server.wishes import thing_of
    cases = {  # the raw wish text after "I wish" / "we need", as seen in the live world
        "there were a place to store": "place to store",
        "there were a reliable water source": "reliable water source",
        "flint lay closer so we do": "flint lay closer",
        "there were more varied tasks so": "varied tasks",
        "firewood and berries to spare the": "firewood and berries to spare",
        "a roof that keeps the rain off because it pours": "roof that keeps the rain off",
    }
    for raw, want in cases.items():
        assert thing_of(raw) == want, (raw, thing_of(raw))


def test_wishes_about_other_creatures_are_not_things():
    w = Wishes(Catalog.load())
    names = {"c1": "Gus", "c2": "Dree"}
    w.observe(ev("say", "c1", "", line="I wish Dree would finally share the last berries.", speaker="Gus"), names)
    assert not w.ranked()


def test_saved_wishes_are_tidied_on_load():
    w = Wishes(Catalog.load())
    w.load({"seq": 2, "items": {
        "there were a place to store": {"id": "w1", "thing": "there were a place to store", "kinds": {"said": 1, "failed": 0, "wished": 0, "reflected": 1},
                                        "by": {"Vex": 1}, "quotes": [], "first_tick": 5, "last_tick": 9, "status": "open", "answer": "", "granted": ""},
        "place to store": {"id": "w2", "thing": "place to store", "kinds": {"said": 1, "failed": 0, "wished": 0, "reflected": 0},
                           "by": {"Ira": 1}, "quotes": [], "first_tick": 7, "last_tick": 8, "status": "open", "answer": "", "granted": ""}}})
    ranked = w.ranked()
    assert [x["thing"] for x in ranked] == ["place to store"] and ranked[0]["creatures"] == 2 and ranked[0]["total"] == 3
    w2 = Wishes(Catalog.load())
    w2.people = {"dree"}
    w2.load({"seq": 1, "items": {"x": {"id": "w1", "thing": "dree would finally share the last", "kinds": {"said": 1},
                                       "by": {"Gus": 1}, "quotes": [], "first_tick": 1, "last_tick": 1, "status": "open",
                                       "answer": "", "granted": ""}}})
    assert not w2.ranked()


def test_explicit_wishes_beat_reflected_fragments_on_the_board():
    w = Wishes(Catalog.load())
    names = {"c1": "Mirth"}
    for i in range(70):
        w.observe_reflection("Mirth", f"I wish for steady supply number{'x' * (i % 5)} of thing{chr(97 + i % 26)}{chr(97 + i // 26)}.", 5)
    for _ in range(8):
        w.observe(ev("wish", "c1", "", line="a flint to light my fire"), names)
    board = w.ranked(60)
    assert board[0]["thing"].startswith("flint") and not board[0]["reflected_only"]
    refl = [v for v in board if v["reflected_only"]]
    assert refl and len(refl) <= 30 and board[1:] == refl  # reflected-only sit after, in their own capped section
    assert len(w.ranked(60, 5)) == 6
