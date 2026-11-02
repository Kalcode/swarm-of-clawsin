"""Tests for the terminal Lua sandbox (Task 11, Review Focus item 4)."""

from __future__ import annotations

import time

import pytest

from swarmworld.scripting.lua_sandbox import LuaSandbox, RunResult


def _bytecode() -> str:
    """A real precompiled Lua chunk, as a str the way a creature would submit it."""
    from lupa import lua54

    chunk = lua54.LuaRuntime(encoding=None).eval("string.dump(function() return 1 end)")
    assert chunk.startswith(b"\x1bLua")
    return chunk.decode("latin-1")


@pytest.fixture
def sandbox() -> LuaSandbox:
    return LuaSandbox()


def test_sandbox_runs_and_prints(sandbox):
    result = sandbox.run('print("hello", 1, nil, true) print(2 + 3)', {}, {})
    assert result == RunResult(ok=True, output=["hello\t1\tnil\ttrue", "5"], error=None)


def test_output_is_capped(sandbox):
    result = sandbox.run('for i = 1, 50 do print(i) end print(("x"):rep(1000))', {}, {})
    assert result.ok
    assert result.output == [str(i) for i in range(1, 21)]
    long = sandbox.run('print(("é"):rep(500)) print("a\\nb")', {}, {})
    assert long.output == ["é" * 200, "a", "b"]


def test_api_roundtrip(sandbox):
    said: list = []
    scans: list = []

    def scan(r):
        scans.append(r)
        return [
            {"kind": "tree", "name": "oak", "dx": 1, "dy": 0},
            {"kind": "creature", "name": "Bo", "dx": -2, "dy": 3},
        ]

    api = {
        "scan": scan,
        "say": said.append,
        "time": lambda: {"tick": 40, "day": 2, "phase": "dusk"},
    }
    code = """
    local names = {}
    for i, t in ipairs(scan(5)) do
      names[#names + 1] = t.kind .. ":" .. t.name .. "@" .. t.dx .. "," .. t.dy
    end
    local now = time()
    say(table.concat(names, " ") .. " " .. now.phase .. now.tick)
    print(type(scan(1)), #scan(1))
    """
    result = sandbox.run(code, api, {})
    assert result.ok, result.error
    assert said == ["tree:oak@1,0 creature:Bo@-2,3 dusk40"]
    assert all(isinstance(s, str) for s in said)
    assert scans == [5, 1, 1] and type(scans[0]) is int
    assert result.output == ["table\t2"]


def test_api_arguments_become_plain_python(sandbox):
    seen: list = []
    result = sandbox.run(
        'probe({1, 2, {x = "y"}}, {a = true}, 2.5, nil, print)',
        {"probe": lambda *args: seen.append(args)},
        {},
    )
    assert result.ok, result.error
    assert seen == [([1, 2, {"x": "y"}], {"a": True}, 2.5, None, None)]


def test_memory_persists(sandbox):
    state: dict = {}
    code = """
    memory.runs = (memory.runs or 0) + 1
    memory.log = memory.log or {}
    memory.log[#memory.log + 1] = "run" .. memory.runs
    print(memory.runs)
    """
    assert sandbox.run(code, {}, state).output == ["1"]
    assert sandbox.run(code, {}, state).output == ["2"]
    assert state == {"runs": 2, "log": ["run1", "run2"]}
    assert sandbox.run(code, {}, state).output == ["3"]


def test_memory_keeps_only_plain_values(sandbox):
    state: dict = {"old": "kept?"}
    code = """
    memory.old = nil
    memory.f = print
    memory.long = ("x"):rep(600)
    memory.deep = {a = {b = 1, c = {d = 1}}}  -- memory.deep.a.c.d is 4 keys deep
    memory.flag = true
    """
    assert sandbox.run(code, {}, state).ok
    assert "old" not in state and "f" not in state
    assert len(state["long"]) == 500
    assert state["deep"] == {"a": {"b": 1}}
    assert state["flag"] is True

    # At most 200 keys survive, counted over all levels, top-level keys first.
    assert sandbox.run(
        'memory.nested = {1, 2, 3} for i = 1, 300 do memory["k" .. i] = i end', {}, state
    ).ok

    def count(value):
        if isinstance(value, dict):
            return sum(1 + count(v) for v in value.values())
        if isinstance(value, list):
            return sum(1 + count(v) for v in value)
        return 0

    assert count(state) == 200


LIMIT_CASES = [
    ("infinite_loop", "while true do end", "instruction limit exceeded"),
    ("table_growth_bomb", "local t = {} for i = 1, 1e9 do t[i] = i end", "limit|out of memory"),
    ("string_doubling_bomb", 'local s = "x" while true do s = s .. s end', "out of memory"),
    ("string_rep_huge", 'local s = string.rep("x", 1e9)', "too large"),
    ("string_method_rep_huge", 'local s = ("x"):rep(1e9)', "too large"),
    ("os_execute", 'os.execute("touch {canary}")', "global 'os'"),
    ("io_open", 'local f = io.open("/etc/passwd") print(f:read("a"))', "global 'io'"),
    ("io_write", 'io.open("{canary}", "w"):write("pwned")', "global 'io'"),
    ("load", 'load("return 1")', "global 'load'"),
    ("loadstring", 'loadstring("return 1")', "global 'loadstring'"),
    ("dofile", 'dofile("/etc/passwd")', "global 'dofile'"),
    ("string_dump", "string.dump(print)", "field 'dump'"),
    ("require", 'require("os")', "global 'require'"),
    ("python_eval", 'python.eval("1")', "global 'python'"),
    ("python_builtins", "local o = python.builtins.open", "global 'python'"),
    ("string_meta_dump", '("").dump(print)', "field 'dump'"),
    ("getmetatable_dump", 'local d = getmetatable("").__index.dump', "global 'getmetatable'"),
    ("bytecode_input", "{bytecode}", "binary chunk"),
    ("collectgarbage", "collectgarbage()", "global 'collectgarbage'"),
    ("debug_sethook", "debug.sethook()", "global 'debug'"),
    ("setmetatable", "setmetatable({}, {__gc = print})", "global 'setmetatable'"),
    ("rawget", 'rawget(_ENV, "os")', "global 'rawget'"),
    ("coroutine", "coroutine.wrap(function() end)", "global 'coroutine'"),
    ("api_python_attrs", "local c = say.__class__", "index a function value"),
    ("pcall_cannot_swallow_limit",
     "while true do pcall(function() while true do end end) end", "instruction limit exceeded"),
    ("table_move_huge", "table.move({}, 1, 1e15, 1)", "instruction limit exceeded"),
    ("pattern_backtracking", 'return ("a"):rep(300):find(".-.-.-b")', "pattern too complex"),
    ("deep_recursion", "local function f() return 1 + f() end f()", "overflow|out of memory"),
    # Harmless: the dangerous thing is simply absent.
    ("string_meta_dump_is_nil", 'print(("").dump, string.dump)', None),
    ("env_is_clean",
     'for k in pairs(_ENV) do assert(not ({os=1, io=1, debug=1, load=1, python=1, '
     'require=1, package=1, getmetatable=1, collectgarbage=1})[k], k) end print("clean")', None),
    ("string_rep_empty", 'print(#string.rep("", 1e15))', None),  # a C loop in Lua 5.4
]


@pytest.mark.parametrize("name,code,expected", LIMIT_CASES, ids=[c[0] for c in LIMIT_CASES])
def test_sandbox_limits(sandbox, tmp_path, name, code, expected):
    canary = tmp_path / "pwned"
    code = code.replace("{canary}", str(canary))
    if code == "{bytecode}":
        code = _bytecode()
    said: list = []
    start = time.perf_counter()
    result = sandbox.run(code, {"say": said.append}, {})
    elapsed = time.perf_counter() - start
    assert isinstance(result, RunResult)
    if expected is None:
        assert result.ok, result.error
        assert "function" not in " ".join(result.output)
    else:
        assert not result.ok
        assert result.error and any(part in result.error for part in expected.split("|")), result.error
    assert not canary.exists()
    assert said == []
    assert elapsed < 2.0
    # The sandbox (and the world loop around it) keeps working afterwards.
    assert sandbox.run('print("still alive")', {}, {}).output == ["still alive"]


def test_memory_limit_reports_out_of_memory():
    roomy = LuaSandbox(max_instructions=50_000_000)
    for code in (
        "local t = {} for i = 1, 1e9 do t[i] = i end",
        'local t = {} for i = 1, 1e9 do t[i] = ("x"):rep(100) .. i end',
        'local s = "x" while true do s = s .. s end',
    ):
        result = roomy.run(code, {}, {})
        assert (result.ok, result.error) == (False, "out of memory"), code


def test_heavy_library_loops_are_bounded(sandbox):
    big = 'local s = ("x"):rep(100000) s = s .. s .. s .. s\n'
    for code in (
        'local s = ("x"):rep(100000) while true do s:gsub("x", "y") end',
        'while true do local x = ("x"):rep(100000) end',
        'local t = {("x"):rep(20000):byte(1, -1)} while true do table.sort(t) end',
        'local s = ("a"):rep(440) while true do s:find(".-.-b") end',
        big + 'while true do local a = s .. "y" end',
        big + 'local b, c = s .. "y", s .. "z" while true do local x = b < c end',
    ):
        start = time.perf_counter()
        result = sandbox.run(code, {}, {})
        assert not result.ok and "limit exceeded" in result.error, (code, result.error)
        assert time.perf_counter() - start < 1.0, code


def test_api_exception_becomes_lua_error(sandbox):
    def scan(r):
        raise ValueError("radius must be at most 6")

    result = sandbox.run("scan(99)", {"scan": scan}, {})
    assert not result.ok
    assert "radius must be at most 6" in result.error and "line 1" in result.error

    caught = sandbox.run(
        'local ok, err = pcall(scan, 99) print(ok, type(err), err)', {"scan": scan}, {}
    )
    assert caught.ok
    assert caught.output == ["false\tstring\tscan: radius must be at most 6"]

    bad_return = sandbox.run("scan()", {"scan": lambda: object()}, {})
    assert not bad_return.ok and "cannot pass object to Lua" in bad_return.error


def test_api_calls_at_memory_exhaustion_do_not_crash(sandbox):
    # lupa aborts the process if a Python-side allocation hits the limit; the
    # sandbox must lift the limit around api calls. A crash fails this test run.
    calls: list = []

    def scan(r):
        calls.append(r)
        return [{"kind": "rock", "name": "x" * 200, "dx": i, "dy": i} for i in range(500)]

    code = """
    local ok_count = 0
    local results = {} for i = 1, 40 do results[i] = 0 end
    local hog = {}
    while pcall(function() for i = 1, 1e9 do hog[#hog + 1] = {i} end end) do end
    while pcall(function() hog[#hog + 1] = {} end) do end
    for i = 1, 20 do results[i] = pcall(scan, i) end
    for i = 21, 40 do results[i] = pcall(echo, "abc", 1) end
    hog = nil
    for i = 1, 40 do if results[i] == true then ok_count = ok_count + 1 end end
    print(ok_count)
    """
    result = LuaSandbox(max_instructions=50_000_000).run(
        code, {"scan": scan, "echo": lambda *a: list(a)}, {}
    )
    assert len(calls) == 20
    assert result.ok, result.error
    assert result.output == ["40"]


def test_timing(sandbox):
    sandbox.run("local x = 1", {}, {})  # warm up imports
    runs = 50
    start = time.perf_counter()
    for _ in range(runs):
        result = sandbox.run("local x = 1 + 1", {"say": lambda m: None}, {"n": 1})
        assert result.ok
    average = (time.perf_counter() - start) / runs
    assert average < 0.020, f"{average * 1000:.2f} ms per run"
