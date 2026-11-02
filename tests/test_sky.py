"""The voice from the sky reaches sleepers as a dream, lingers for a day, and isn't treated as idle chatter."""

from swarmworld.mind.recall import Doc
from swarmworld.server.persistence import restore, save
from swarmworld.server.state import SKY_LINGER, ServerState, auto_weight


def two_creatures():
    st = ServerState(seed=7)
    a, b = st.new_creature("mock"), st.new_creature("mock")
    a.asleep, b.asleep = False, True
    b.wake_reason = None
    return st, a, b


def prompt(st, c):
    return st.make_job(type("N", (), {"id": "n", "inflight": {}})(), c)["messages"][1]["content"]


def test_sleepers_dream_the_voice():
    st, a, b = two_creatures()
    reached = st.voice_from_the_sky("Beer is sacred.")
    assert a.name in reached and any(b.name in r for r in reached)
    assert any(t.startswith("In a dream") and "Beer is sacred." in t for t in st.memory(b.id).recent())
    assert b.asleep and b.wake_reason is None  # a dream doesn't wake you


def test_the_sky_lingers_for_a_day():
    st, a, _ = two_creatures()
    st.voice_from_the_sky("Beer is sacred.")
    assert 'The sky has spoken: "Beer is sacred."' in prompt(st, a)
    st.world.tick += SKY_LINGER + 1
    a.thinking = False
    assert "The sky has spoken" not in prompt(st, a)


def test_an_area_voice_lingers_only_for_those_who_heard():
    st, a, b = two_creatures()
    b.asleep = False
    a.x, a.y, b.x, b.y = 5, 5, 40, 40
    st.voice_from_the_sky("Dig here.", x=5, y=5, radius=3)
    assert "Dig here." in prompt(st, a) and "Dig here." not in prompt(st, b)


def test_a_wish_answer_lingers_for_the_wishers():
    from swarmworld.world.events import Event
    st, a, b = two_creatures()
    st.wishes.observe(Event(st.world.tick, "say", a.id, 0, 0, "", {"line": "I wish we had a boat.", "speaker": a.name}),
                      {a.id: a.name})
    st.answer_wish(st.wishes.ranked()[0]["id"], reply="Lash logs together with rope.")
    assert 'The sky answered your wish for boat: "Lash logs together with rope."' in prompt(st, a)
    assert "Lash logs" not in prompt(st, b)


def test_sky_words_survive_a_restart(tmp_path):
    st, a, _ = two_creatures()
    st.voice_from_the_sky("Beer is sacred.")
    save(st, tmp_path / "w.json")
    st2 = ServerState(seed=99)
    restore(st2, tmp_path / "w.json")
    st2.world.creatures[a.id].asleep = False
    assert "Beer is sacred." in prompt(st2, st2.world.creatures[a.id])


def test_recall_does_not_treat_the_sky_as_chatter():
    sky = Doc("k1", "memory", 'A booming voice from the sky says: "Beer is sacred."', 0, 3)
    chat = Doc("k2", "memory", 'Mara says: "Nice weather."', 0, 1)
    assert auto_weight(sky) == 1.0 and auto_weight(chat) < 1.0
