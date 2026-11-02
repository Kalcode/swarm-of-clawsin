from swarmworld.scripting.terminal import run_terminal
from swarmworld.world.actions import Intention, apply_intention
from swarmworld.world.catalog import Catalog
from swarmworld.world.model import START_TICK, Creature, World
from swarmworld.world.simulation import Simulation


def _setup():
    w = World(30, 30, [["g"] * 30 for _ in range(30)], Catalog.load())
    w.tick = START_TICK
    notes = {}
    sim = Simulation(w, memory_sink=lambda c, t, i: notes.setdefault(c.name, []).append(t), terminal_runner=run_terminal)
    term = w.add_object("terminal", 10, 10, code="", screen=[], memory={})
    coder = Creature("c1", "Tam", 11, 10, asleep=False, wake_reason=None, last_think_tick=w.tick)
    listener = Creature("c2", "Mara", 12, 12, asleep=False, wake_reason=None, last_think_tick=w.tick)
    w.creatures.update({coder.id: coder, listener.id: listener})
    return w, sim, term, coder, listener, notes


def test_terminal_program_speaks():
    w, sim, term, coder, listener, notes = _setup()
    res = apply_intention(w, coder, Intention("program", target="terminal", text='say("hello from the stone")'))
    assert res.ok
    for _ in range(3):
        sim.tick()
    assert any('The terminal says: "hello from the stone"' in n for n in notes["Mara"])


def test_terminal_scan_print_and_memory():
    w, sim, term, coder, listener, notes = _setup()
    code = """
memory.runs = (memory.runs or 0) + 1
for _, t in ipairs(scan(3)) do
  if t.kind == "creature" then print(t.name .. " at " .. t.dx .. "," .. t.dy) end
end
print("run " .. memory.runs)
"""
    apply_intention(w, coder, Intention("program", target="terminal", text=code))
    for _ in range(45):
        sim.tick()
    screen = "\n".join(term.data["screen"])
    assert "Tam at 1,0" in screen and "Mara at 2,2" in screen
    assert term.data["memory"]["runs"] >= 2 and "run 2" in screen
    read = apply_intention(w, coder, Intention("read", target="terminal"))
    assert "Tam at 1,0" in read.message


def test_terminal_survives_bad_code():
    w, sim, term, coder, listener, notes = _setup()
    apply_intention(w, coder, Intention("program", target="terminal", text="while true do end"))
    sim.tick()
    sim.tick()
    assert any("error" in line for line in term.data["screen"])
    apply_intention(w, coder, Intention("program", target="terminal", text='os.execute("rm -rf /")'))
    for _ in range(25):
        sim.tick()
    assert any("error" in line for line in term.data["screen"][-2:])


def test_terminal_find_oracle():
    w, sim, term, coder, listener, notes = _setup()
    w.add_object("copper_vein", 25, 12, ore=8)
    code = 'local c = find("copper") if c then say("copper " .. c.steps .. " steps " .. c.direction) end'
    from swarmworld.world.actions import Intention, apply_intention
    apply_intention(w, coder, Intention("program", target="terminal", text=code))
    for _ in range(3):
        sim.tick()
    assert any("copper 15 steps east" in n for n in notes.get("Mara", []) + notes.get("Tam", []))


def test_a_single_expression_shows_its_value():
    w, sim, term, coder, listener, notes = _setup()
    w.add_object("clay", 14, 7)
    apply_intention(w, coder, Intention("program", target="terminal", text="find('clay')"))
    run_terminal(w, term)
    shown = " ".join(term.data["screen"])
    assert "clay bank" in shown and "steps=4" in shown and "northeast" in shown
    term.data.update(code="scan(5)", screen=[])
    run_terminal(w, term)
    assert any("Tam" in line for line in term.data["screen"]) and len(term.data["screen"]) >= 2
