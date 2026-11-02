"""Sandbox for the Lua programs that creatures write into in-world terminals.

This module is the safety boundary between agent-written code and the host.
Agent code may misbehave inside the world, but it must never reach the host
machine and must never crash or hang the world server.

How it is contained
-------------------
* **Fresh interpreter per run.** Every :meth:`LuaSandbox.run` creates a new
  ``LuaRuntime`` (about 30 µs), so nothing leaks from one run to the next.
* **Text-only load into a bare environment.** User code is compiled with
  ``load(code, "=program", "t", env)``: bytecode is rejected, and ``env``
  holds only ``print`` (captured), copies of ``string`` (without ``dump``),
  ``table`` and ``math`` (without ``randomseed``), ``pairs``, ``ipairs``,
  ``next``, ``tostring``, ``tonumber``, ``type``, ``select``, ``error``,
  ``pcall`` (wrapped), ``assert``, ``unpack``, the api functions and
  ``memory``. The shared string metatable's ``__index`` points at the same
  safe ``string`` copy, so ``("").dump`` is ``nil``. As a second layer, the
  runtime's real globals (``os``, ``io``, ``debug``, ``load``, ``python``,
  and so on) are deleted before user code runs.
* **No Python objects reach user code.** ``register_eval`` and
  ``register_builtins`` are off, the ``python`` global is removed, and an
  ``attribute_filter`` denies all Python attribute access. Api results are
  converted to plain Lua values and tables; Lua arguments are converted to
  plain Python values before the api function sees them. The Python bridge
  objects live only in upvalues of trusted closures, which user code cannot
  read without the ``debug`` library.
* **Instruction budget.** A count hook (``debug.sethook``, installed from the
  trusted side before user code starts) adds ``HOOK_EVERY`` to a counter
  every ``HOOK_EVERY`` VM instructions and raises "instruction limit
  exceeded" past ``max_instructions``. Library calls whose C code does work
  proportional to their input (``string.rep``/``gsub``/``find``/...,
  ``table.concat``/``sort``/``move``/...) are wrapped and charged to the same
  budget, and each api call costs ``API_CALL_COST``. Once a limit trips, the
  wrapped ``pcall`` re-raises, so user code cannot catch it and continue.
* **Pattern guard.** The hook cannot interrupt C code, so ``find``/``match``/
  ``gmatch``/``gsub`` refuse a call whose worst-case backtracking estimate,
  C(len + e, e) for e quantifiers (+1 if unanchored), exceeds
  ``PATTERN_BUDGET``. That bounds one call to roughly 0.1 s. ``string.rep``
  output is capped at ``MAX_STRING_REP`` bytes, and ``table.move`` ranges are
  charged before the call.
* **CPU-time backstop.** The hook and every charged call also stop the run
  after ``TIME_LIMIT`` seconds of process CPU time (``os.clock``). This
  catches single VM instructions that are O(n), such as ``..`` on megabyte
  strings.
* **Memory cap.** lupa's allocator limit (``set_max_memory``) is armed right
  before user code is compiled, so a run can allocate at most
  ``max_memory`` bytes beyond the sandbox's own setup.

lupa caveat: allocations made from Python under an armed limit crash the process
-----------------------------------------------------------------------------
With lupa 2.8, if a Lua allocation that *Python* starts (``table_from``, pushing
a returned string, wrapping a table argument) hits the memory limit, Lua raises
outside any protected call. That is a PANIC/abort or a "Fatal Python error",
not an exception. This module therefore lifts the limit (``unlimit``) around
every Python-side allocation: each api call disarms it before lupa converts
the arguments and re-arms it once the result is stored in a Lua table, and the
host reads results only after disarming it for good. Keep this invariant if
you change anything here: **never touch the LuaRuntime from Python while the
memory limit is armed**.
"""

from __future__ import annotations

import math
import re
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable

try:  # Lua 5.4 is the most widely known modern Lua; prefer it when bundled.
    from lupa import lua54 as _lupa
except ImportError:  # pragma: no cover - fall back to lupa's default Lua
    import lupa as _lupa

LuaRuntime = _lupa.LuaRuntime
LuaError = _lupa.LuaError
LuaMemoryError = _lupa.LuaMemoryError
lua_type = _lupa.lua_type

__all__ = ["LuaSandbox", "RunResult"]


@dataclass
class RunResult:
    ok: bool
    output: list[str] = field(default_factory=list)  # captured print() lines
    error: str | None = None  # short human-readable error


# --------------------------------------------------------------------------
# Trusted Lua bootstrap. It runs with the full standard library, captures what
# it needs as locals, strips the runtime's globals, and returns the function
# that builds the sandbox environment and runs one program.
# --------------------------------------------------------------------------
_BOOTSTRAP = r"""
local LIMITS = ...
local MAX_INSTRUCTIONS = LIMITS.max_instructions
local HOOK_EVERY = LIMITS.hook_every
local API_CALL_COST = LIMITS.api_call_cost
local TIME_LIMIT = LIMITS.time_limit
local MAX_LINES = LIMITS.max_lines
local LINE_BYTES = LIMITS.line_bytes
local MAX_STRING = LIMITS.max_string
local MAX_PATTERN = LIMITS.max_pattern
local PATTERN_BUDGET = LIMITS.pattern_budget
local UNIT = LIMITS.bytes_per_instruction

local MSG_INSTRUCTIONS = "instruction limit exceeded"
local MSG_TIME = "time limit exceeded"

local type, tostring, tonumber, select, error, pcall, next, pairs, ipairs, assert =
      type, tostring, tonumber, select, error, pcall, next, pairs, ipairs, assert
local load, getmetatable, sethook, clock = load, getmetatable, debug.sethook, os.clock
local log = math.log
local string_lib, table_lib, math_lib = string, table, math
local s_byte, s_sub, s_find, s_format = string.byte, string.sub, string.find, string.format
local t_pack, t_concat = table.pack, table.concat
local string_meta = getmetatable("")

-- Second layer: user code never sees _G, but strip it anyway.
do
  local loaded = package.loaded
  for _, name in ipairs({"python", "os", "io", "debug", "package", "require", "load",
                         "loadstring", "loadfile", "dofile", "collectgarbage", "rawset",
                         "rawget", "rawequal", "rawlen", "setmetatable", "getmetatable",
                         "coroutine", "utf8", "warn", "xpcall"}) do
    loaded[name] = nil
    _G[name] = nil
  end
end

local function copy(t)
  local c = {}
  for k, v in next, t do c[k] = v end
  return c
end

-- Length of a string (or number, which Lua coerces) argument, else nil.
local function lenof(v)
  local tv = type(v)
  if tv == "string" then return #v end
  if tv == "number" then return #tostring(v) end
  return nil
end

-- C(n, k) as a float, stopping early once it exceeds the pattern budget.
local function choose(n, k)
  local c = 1
  for i = 1, k do
    c = c * (n - k + i) / i
    if c > PATTERN_BUDGET then return c end
  end
  return c
end

-- Index just past the ']' closing the set that starts at p[i] == '['.
local function skip_set(p, i)
  local n = #p
  i = i + 1
  if s_byte(p, i) == 94 then i = i + 1 end            -- '^'
  repeat                                              -- first char may be ']'
    if i > n then return n + 1 end
    local c = s_byte(p, i)
    i = i + 1
    if c == 37 then i = i + 1 end                     -- '%x' escape
  until s_byte(p, i) == 93                            -- ']'
  return i + 1
end

-- Shape of a Lua pattern for the backtracking estimate: exponent e (one per
-- '*', '+', '-' quantifier, '%b' and back-reference, plus one when the
-- match is unanchored), and q, the number of '?' items.
local function pattern_shape(p, gmatch)
  local n, i, e, q = #p, 1, 0, 0
  if gmatch or s_byte(p, 1) ~= 94 then e = 1 else i = 2 end
  while i <= n do
    local c = s_byte(p, i)
    local quantifiable = true
    if c == 37 then                                   -- '%'
      local d = s_byte(p, i + 1)
      if d == 98 then                                 -- %bxy
        e = e + 1; i = i + 4; quantifiable = false
      elseif d == 102 then                            -- %f[set]
        i = skip_set(p, i + 2); quantifiable = false
      elseif d and d >= 48 and d <= 57 then           -- %0 .. %9
        e = e + 1; i = i + 2; quantifiable = false
      else
        i = i + 2
      end
    elseif c == 91 then                               -- '['
      i = skip_set(p, i)
    elseif c == 40 or c == 41 then                    -- '(' ')'
      i = i + 1; quantifiable = false
    else
      i = i + 1
    end
    if quantifiable then
      local qc = s_byte(p, i)
      if qc == 42 or qc == 43 or qc == 45 then e = e + 1; i = i + 1
      elseif qc == 63 then q = q + 1; i = i + 1 end
    end
  end
  return e, q
end

return function(code, bridge, api_names, unlimit, start_limit, relimit, memory, status)
  local count, killed, active, t0 = 0, nil, false, 0
  local output, nlines = {}, 0
  status.output = output

  local function kill(msg)
    killed = killed or msg
    error(killed, 0)
  end

  local function check_time()
    if clock() - t0 > TIME_LIMIT then kill(MSG_TIME) end
  end

  -- Charge n instructions to the budget (n <= 0 and NaN are ignored). Called
  -- by every wrapped library function, so it also checks the CPU clock.
  local function charge(n)
    if killed then error(killed, 0) end
    if n > 0 then
      count = count + n
      if count > MAX_INSTRUCTIONS then kill(MSG_INSTRUCTIONS) end
      check_time()
    end
  end

  local function hook()
    if not active then return end
    if killed then error(killed, 0) end
    count = count + HOOK_EVERY
    if count > MAX_INSTRUCTIONS then kill(MSG_INSTRUCTIONS) end
    check_time()
  end

  -- pcall that cannot swallow a tripped limit and never hands out host objects.
  local function pcall_result(ok, ...)
    if killed then error(killed, 0) end
    if ok then return true, ... end
    local e = ...
    if type(e) == "userdata" then e = "host error" end
    return false, e
  end
  local function sandbox_pcall(f, ...)
    return pcall_result(pcall(f, ...))
  end

  -- print: tab-joined, split on newlines, at most MAX_LINES lines of
  -- LINE_BYTES bytes (the host trims to characters).
  local function print(...)
    if nlines >= MAX_LINES then return end
    local args = t_pack(...)
    local room = (MAX_LINES - nlines) * (LINE_BYTES + 1)
    local parts, used = {}, 0
    for i = 1, args.n do
      local piece = tostring(args[i])
      if #piece > room - used then piece = s_sub(piece, 1, room - used) end
      parts[i] = piece
      used = used + #piece + 1
      if used >= room then break end
    end
    local text = t_concat(parts, "\t")
    local pos = 1
    repeat
      local nl = s_find(text, "\n", pos, true)
      local stop = (nl or #text + 1) - 1
      if stop - pos + 1 > LINE_BYTES then stop = pos + LINE_BYTES - 1 end
      nlines = nlines + 1
      output[nlines] = s_sub(text, pos, stop)
      pos = nl and nl + 1
    until not pos or nlines >= MAX_LINES
  end

  -- Patterns: refuse calls whose worst-case backtracking is too expensive
  -- (C code cannot be interrupted by the hook) and charge the scan.
  local shapes, gmatch_shapes = {}, {}
  local function pattern_problem(s, p, plain, gmatch)
    local ls, lp = lenof(s), lenof(p)
    if not (ls and lp) then return nil end            -- let Lua report the bad argument
    local cost
    if plain then
      cost = (ls + 1) * (lp / 64 + 1)
    else
      if lp > MAX_PATTERN then
        return s_format("pattern too long (limit %d bytes)", MAX_PATTERN)
      end
      if type(p) == "number" then p = tostring(p) end
      local cache = gmatch and gmatch_shapes or shapes
      local shape = cache[p]
      if not shape then
        local e, q = pattern_shape(p, gmatch)
        shape = {e, q}
        cache[p] = shape
      end
      cost = choose(ls + shape[1], shape[1]) * 2 ^ shape[2] * (lp / 16 + 1)
    end
    if not (cost <= PATTERN_BUDGET) then
      return "pattern too complex for a string this long"
    end
    charge(1 + ls // UNIT + cost // 1024)
    return nil
  end

  -- string: a copy of the library with dump removed and costly calls wrapped.
  local sstring = copy(string_lib)
  sstring.dump = nil
  do
    local rep = string_lib.rep
    sstring.rep = function(s, n, sep)
      local ls, cnt = lenof(s), tonumber(n)
      local lsep = (sep == nil) and 0 or lenof(sep)
      if ls and lsep and cnt and cnt >= 1 then
        local total = (ls + lsep) * (cnt + 0.0) - lsep
        if not (total <= MAX_STRING) then
          error(s_format("string.rep result too large (limit %d bytes)", MAX_STRING), 2)
        end
        if total <= 0 then return "" end               -- Lua 5.4 loops n times here
        charge(total // UNIT)
      end
      return rep(s, n, sep)
    end
  end
  do
    local find = string_lib.find
    sstring.find = function(s, p, init, plain)
      local problem = pattern_problem(s, p, plain, false)
      if problem then error(problem, 2) end
      return find(s, p, init, plain)
    end
  end
  do
    local match = string_lib.match
    sstring.match = function(s, p, init)
      local problem = pattern_problem(s, p, false, false)
      if problem then error(problem, 2) end
      return match(s, p, init)
    end
  end
  do
    local gmatch = string_lib.gmatch
    sstring.gmatch = function(s, p, init)
      local problem = pattern_problem(s, p, false, true)
      if problem then error(problem, 2) end
      return gmatch(s, p, init)
    end
  end
  do
    local gsub = string_lib.gsub
    sstring.gsub = function(s, p, repl, n)
      local problem = pattern_problem(s, p, false, false)
      if problem then error(problem, 2) end
      local r, k = gsub(s, p, repl, n)
      charge(#r // UNIT)
      return r, k
    end
  end
  do
    local sub = string_lib.sub
    sstring.sub = function(s, i, j)
      local r = sub(s, i, j); charge(#r // UNIT); return r
    end
    local upper = string_lib.upper
    sstring.upper = function(s)
      local r = upper(s); charge(#r // UNIT); return r
    end
    local lower = string_lib.lower
    sstring.lower = function(s)
      local r = lower(s); charge(#r // UNIT); return r
    end
    local reverse = string_lib.reverse
    sstring.reverse = function(s)
      local r = reverse(s); charge(#r // UNIT); return r
    end
    local format = string_lib.format
    sstring.format = function(fmt, ...)
      local r = format(fmt, ...); charge(#r // UNIT); return r
    end
    local pack = string_lib.pack
    sstring.pack = function(fmt, ...)
      local r = pack(fmt, ...); charge(#r // UNIT); return r
    end
    local function charge_results(...)
      charge(select("#", ...) // 8)
      return ...
    end
    local byte = string_lib.byte
    sstring.byte = function(s, i, j) return charge_results(byte(s, i, j)) end
    local unpack = string_lib.unpack
    sstring.unpack = function(fmt, s, pos) return charge_results(unpack(fmt, s, pos)) end
    local char = string_lib.char
    sstring.char = function(...)
      charge(select("#", ...) // 8)
      return char(...)
    end
  end
  string_meta.__index = sstring                       -- ("x"):rep() etc. use the safe copy

  -- table: a copy with costly calls charged.
  local stable = copy(table_lib)
  do
    local concat = table_lib.concat
    stable.concat = function(t, sep, i, j)
      if type(t) == "table" then
        charge(((tonumber(j) or #t) - (tonumber(i) or 1) + 1.0) // 8)  -- float: no wraparound
      end
      local r = concat(t, sep, i, j)
      charge(#r // UNIT)
      return r
    end
    local insert = table_lib.insert
    stable.insert = function(t, ...)
      if type(t) == "table" and select("#", ...) >= 2 then charge(#t // 16) end
      return insert(t, ...)
    end
    local remove = table_lib.remove
    stable.remove = function(t, ...)
      if type(t) == "table" then charge(#t // 16) end
      return remove(t, ...)
    end
    local sort = table_lib.sort
    stable.sort = function(t, comp)
      if type(t) == "table" then
        local n = #t
        if n > 1 then charge(n * log(n, 2) // 2) end
      end
      return sort(t, comp)
    end
    local move = table_lib.move
    stable.move = function(a1, f, e, t, a2)
      local first, last = tonumber(f), tonumber(e)
      if first and last then charge((last - first + 1.0) // 4) end  -- float: no wraparound
      return move(a1, f, e, t, a2)
    end
    local function charge_results(...)
      charge(select("#", ...) // 8)
      return ...
    end
    local unpack = table_lib.unpack
    stable.unpack = function(t, i, j) return charge_results(unpack(t, i, j)) end
    local pack = table_lib.pack
    stable.pack = function(...)
      charge(select("#", ...) // 8)
      return pack(...)
    end
    local create = table_lib.create                   -- Lua 5.5 only
    if create then
      stable.create = function(narr, nrec)
        charge(((tonumber(narr) or 0) + (tonumber(nrec) or 0)) // 16)
        return create(narr, nrec)
      end
    end
  end

  local smath = copy(math_lib)
  smath.randomseed = nil

  local function sandbox_tonumber(v, base)                -- O(#v) on long digit strings
    if type(v) == "string" then charge(#v // UNIT) end
    return tonumber(v, base)
  end

  local env = {
    print = print, pcall = sandbox_pcall,
    string = sstring, table = stable, math = smath,
    pairs = pairs, ipairs = ipairs, next = next,
    tostring = tostring, tonumber = sandbox_tonumber, type = type, select = select,
    error = error, assert = assert, unpack = stable.unpack,
  }

  -- Api functions: the limit is lifted while lupa and Python touch the Lua
  -- heap, results come back boxed in a table built while unlimited, and the
  -- limit is re-armed even if the bridge fails.
  local function api_function(index)
    return function(...)
      charge(API_CALL_COST)                           -- no allocation before unlimit()
      unlimit()
      local called, ok, box = pcall(bridge, index, ...)
      relimit()
      check_time()
      if called and ok then return box[1] end
      if called and type(box) == "table" then error(box[1], 2) end
      error("host function failed", 2)
    end
  end
  for i = 1, #api_names do
    env[api_names[i]] = api_function(i)
  end
  env.memory = memory

  local function main()
    sethook(hook, "", HOOK_EVERY)
    t0 = clock()
    start_limit()
    local fn, load_err = load(code, "=program", "t", env)
    if not fn then return false, load_err end
    active = true
    local ok, err = pcall(fn)
    active = false
    if ok then err = nil end
    return ok, err
  end

  local outer_ok, ok, err = pcall(main)
  active = false
  unlimit()
  sethook()
  if not outer_ok then ok, err = false, ok end
  status.ok = ok and true or false
  status.err = err
  status.killed = killed
  status.memory = env.memory
end
"""


class _Budget:
    """Counts items converted across the boundary; raises when exhausted."""

    __slots__ = ("left", "what")

    def __init__(self, items: int, what: str) -> None:
        self.left = items
        self.what = what

    def take(self) -> None:
        self.left -= 1
        if self.left < 0:
            raise ValueError(f"{self.what} too large")


class _Context:
    """Per-run state shared with the bridge callbacks.

    ``lua`` is cleared after the run: the callbacks are referenced from inside
    the Lua state, so holding the runtime here would form a cycle that Python's
    garbage collector cannot see.
    """

    __slots__ = ("lua", "limit")

    def __init__(self, lua: Any) -> None:
        self.lua = lua
        self.limit = 0


def _deny_attribute(obj: Any, attr_name: Any, is_setting: bool) -> Any:
    raise AttributeError("Python attribute access is not allowed in the sandbox")


_DROP = object()
_INT64_MIN, _INT64_MAX = -(2**63), 2**63 - 1


class LuaSandbox:
    """Runs untrusted Lua programs with instruction, time and memory limits."""

    MAX_OUTPUT_LINES = 20
    MAX_LINE_CHARS = 200
    MAX_CODE_BYTES = 64 * 1024
    MAX_ERROR_CHARS = 300

    MAX_STATE_KEYS = 200  # total keys kept in memory/state, all levels
    MAX_STATE_DEPTH = 3  # memory.a.b.c is kept, memory.a.b.c.d is dropped
    MAX_STATE_STR = 500

    MAX_ARG_ITEMS = 1000  # table entries per api call, Lua -> Python
    MAX_ARG_DEPTH = 8
    MAX_ARG_STR = 10_000  # characters per string argument (truncated)
    MAX_RETURN_ITEMS = 10_000  # entries per api result, Python -> Lua
    MAX_RETURN_DEPTH = 16

    HOOK_EVERY = 1000  # count-hook period, in VM instructions
    API_CALL_COST = 100  # instructions charged per api call
    TIME_LIMIT = 0.1  # seconds of process CPU time per run (backstop)
    MAX_STRING_REP = 100_000  # bytes per string.rep result
    MAX_PATTERN_BYTES = 512
    PATTERN_BUDGET = 2e7  # worst-case backtracking steps allowed per call
    BYTES_PER_INSTRUCTION = 16  # charge for C work proportional to input/output

    def __init__(self, max_instructions: int = 50_000, max_memory: int = 2_000_000):
        if max_instructions <= 0 or max_memory <= 0:
            raise ValueError("limits must be positive")
        self.max_instructions = int(max_instructions)
        self.max_memory = int(max_memory)

    # ------------------------------------------------------------------ run
    def run(self, code: str, api: dict[str, Callable], state: dict) -> RunResult:
        """Run ``code``; never raises for anything the code itself does."""
        api = dict(api or {})
        for name, func in api.items():
            if not isinstance(name, str) or not callable(func):
                raise TypeError(f"api entries must map str -> callable, got {name!r}")
        if not isinstance(code, str):
            return RunResult(False, [], "program must be text")
        code_bytes = code.encode("utf-8", "replace")
        if len(code_bytes) > self.MAX_CODE_BYTES:
            return RunResult(False, [], f"program too long (limit {self.MAX_CODE_BYTES} bytes)")
        try:
            return self._run(code_bytes, api, state)
        except Exception as exc:  # defensive: host bugs must not reach the world loop
            return RunResult(False, [], f"sandbox error: {type(exc).__name__}")

    def _run(self, code: bytes, api: dict[str, Callable], state: dict) -> RunResult:
        lua = LuaRuntime(
            encoding=None,  # all strings cross as bytes; we encode/decode ourselves
            max_memory=0,  # custom allocator, no limit until user code starts
            register_eval=False,
            register_builtins=False,
            unpack_returned_tuples=True,
            attribute_filter=_deny_attribute,
        )
        ctx = _Context(lua)
        funcs = list(api.items())
        max_memory = self.max_memory

        def unlimit() -> None:
            if ctx.lua is not None:
                ctx.lua.set_max_memory(0)

        def start_limit() -> None:
            ctx.limit = ctx.lua.get_memory_used(total=True) + max_memory
            ctx.lua.set_max_memory(ctx.limit, total=True)

        def relimit() -> None:
            if ctx.lua is not None:
                ctx.lua.set_max_memory(ctx.limit, total=True)

        def bridge(index: Any, *args: Any) -> tuple[bool, Any]:
            # Called from Lua with the memory limit lifted; must not raise.
            current = ctx.lua
            name = "api"
            try:
                name, func = funcs[int(index) - 1]
                budget = _Budget(self.MAX_ARG_ITEMS, "argument")
                py_args = []
                for arg in args:
                    budget.take()
                    py_args.append(self._lua_to_py(arg, 0, budget))
                result = func(*py_args)
                value = self._py_to_lua(
                    current, result, 0, _Budget(self.MAX_RETURN_ITEMS, "result")
                )
                return True, current.table_from([value])
            except Exception as exc:
                message = f"{name}: {exc}" if str(exc) else f"{name}: {type(exc).__name__}"
                try:
                    return False, current.table_from([message[:200].encode("utf-8", "replace")])
                except Exception:
                    return False, None

        try:
            loader = lua.globals()[b"load"]
            factory = loader(_BOOTSTRAP.encode(), b"=sandbox", b"t")
            runner = factory(lua.table_from(self._limits()))
            memory_tbl = self._py_to_lua(
                lua, self._sanitize_state(state, from_lua=False), 0,
                _Budget(self.MAX_STATE_KEYS + 1, "memory"),
            )
            status = lua.table()
            names = lua.table_from([name.encode("utf-8") for name, _ in funcs])
            escaped: bytes | None = None  # the runner catches everything; just in case
            try:
                runner(code, bridge, names, unlimit, start_limit, relimit, memory_tbl, status)
            except LuaMemoryError:
                escaped = b"not enough memory"
            except LuaError as exc:
                escaped = str(exc).encode("utf-8", "replace")
            finally:
                lua.set_max_memory(0)  # before the host touches the Lua heap again

            output = self._read_output(status[b"output"])
            ok = escaped is None and status[b"ok"] is True
            if ok:
                error = None
            elif escaped is not None:
                error = self._format_error(status[b"killed"] or escaped, None)
            else:
                error = self._format_error(status[b"killed"], status[b"err"])
            final_memory = status[b"memory"]
            if lua_type(final_memory) != "table":
                final_memory = memory_tbl
            if isinstance(state, dict):
                new_state = self._sanitize_state(final_memory, from_lua=True)
                state.clear()
                state.update(new_state)
            return RunResult(ok, output, error)
        finally:
            ctx.lua = None

    # --------------------------------------------------------------- helpers
    def _limits(self) -> dict[bytes, Any]:
        return {
            b"max_instructions": self.max_instructions,
            b"hook_every": self.HOOK_EVERY,
            b"api_call_cost": self.API_CALL_COST,
            b"time_limit": float(self.TIME_LIMIT),
            b"max_lines": self.MAX_OUTPUT_LINES,
            b"line_bytes": self.MAX_LINE_CHARS * 4,  # UTF-8 worst case
            b"max_string": self.MAX_STRING_REP,
            b"max_pattern": self.MAX_PATTERN_BYTES,
            b"pattern_budget": float(self.PATTERN_BUDGET),
            b"bytes_per_instruction": self.BYTES_PER_INSTRUCTION,
        }

    def _read_output(self, table: Any) -> list[str]:
        lines: list[str] = []
        if lua_type(table) != "table":
            return lines
        for i in range(1, self.MAX_OUTPUT_LINES + 1):
            line = table[i]
            if not isinstance(line, bytes):
                break
            lines.append(line.decode("utf-8", "replace")[: self.MAX_LINE_CHARS])
        return lines

    def _format_error(self, killed: Any, err: Any) -> str:
        value = killed if killed is not None else err
        if isinstance(value, bytes):
            message = value.decode("utf-8", "replace")
        elif isinstance(value, (bool, int, float)):
            message = str(value)
        elif value is None:
            message = "error object is a nil value"
        else:
            message = f"error object is a {lua_type(value) or type(value).__name__} value"
        message = message.replace("not enough memory", "out of memory")
        message = re.sub(r"^(?:sandbox:\d+: )+", "", message)
        message = re.sub(r"^program:(\d+): ", r"line \1: ", message)
        return message[: self.MAX_ERROR_CHARS]

    # Lua -> Python, for api arguments.
    def _lua_to_py(self, value: Any, depth: int, budget: _Budget) -> Any:
        kind = lua_type(value)
        if kind is None:
            if isinstance(value, bytes):
                limit = self.MAX_ARG_STR
                return value[: limit * 4].decode("utf-8", "replace")[:limit]
            if value is None or isinstance(value, (bool, int, float)):
                return value
            return None
        if kind != "table":
            return None  # functions, coroutines, userdata never leave Lua
        if depth >= self.MAX_ARG_DEPTH:
            raise ValueError("argument nested too deeply")
        items: dict[Any, Any] = {}
        for key, item in value.items():
            budget.take()
            if isinstance(key, bytes):
                key = key.decode("utf-8", "replace")
            elif not isinstance(key, (int, float)):
                continue
            items[key] = self._lua_to_py(item, depth + 1, budget)
        return self._listify(items)

    # Python -> Lua, for api results and the initial memory table. Only call
    # this while the memory limit is lifted.
    def _py_to_lua(self, lua: Any, value: Any, depth: int, budget: _Budget) -> Any:
        if value is None or isinstance(value, (bool, float)):
            return value
        if isinstance(value, int):
            return value if _INT64_MIN <= value <= _INT64_MAX else float(value)
        if isinstance(value, str):
            return value.encode("utf-8", "replace")
        if isinstance(value, (bytes, bytearray)):
            return bytes(value)
        if depth >= self.MAX_RETURN_DEPTH:
            raise ValueError("value nested too deeply")
        if isinstance(value, dict):
            out: dict[Any, Any] = {}
            for key, item in value.items():
                budget.take()
                lua_key = self._py_key(key)
                if lua_key is not None:
                    out[lua_key] = self._py_to_lua(lua, item, depth + 1, budget)
            return lua.table_from(out)
        if isinstance(value, (list, tuple)):
            items = []
            for item in value:
                budget.take()
                items.append(self._py_to_lua(lua, item, depth + 1, budget))
            return lua.table_from(items)
        raise TypeError(f"cannot pass {type(value).__name__} to Lua")

    @staticmethod
    def _py_key(key: Any) -> Any:
        # nil and NaN keys would raise inside lupa's unprotected table writes.
        if isinstance(key, str):
            return key.encode("utf-8", "replace")
        if isinstance(key, bytes):
            return key
        if isinstance(key, bool):
            return key
        if isinstance(key, int):
            return key if _INT64_MIN <= key <= _INT64_MAX else None
        if isinstance(key, float):
            return None if math.isnan(key) else key
        return None

    @staticmethod
    def _listify(items: dict[Any, Any]) -> Any:
        """A table whose keys are exactly 1..n becomes a list."""
        n = len(items)
        if n and all(
            type(k) is int and 1 <= k <= n for k in items  # bool is excluded by `type`
        ):
            return [items[i] for i in range(1, n + 1)]
        return items

    # memory/state: plain values only, breadth first so top-level keys win.
    def _sanitize_state(self, root: Any, *, from_lua: bool) -> dict:
        result: dict[Any, Any] = {}
        if from_lua:
            if lua_type(root) != "table":
                return result
        elif not isinstance(root, dict):
            return result
        remaining = self.MAX_STATE_KEYS
        queue: deque[tuple[Any, dict, int]] = deque([(root, result, 1)])
        while queue and remaining > 0:
            source, target, depth = queue.popleft()
            for key, value in self._state_items(source, from_lua):
                if remaining <= 0:
                    break
                key = self._state_key(key)
                if key is None:
                    continue
                if self._is_state_table(value, from_lua):
                    if depth >= self.MAX_STATE_DEPTH:
                        continue
                    child: dict[Any, Any] = {}
                    target[key] = child
                    queue.append((value, child, depth + 1))
                else:
                    value = self._state_scalar(value)
                    if value is _DROP:
                        continue
                    target[key] = value
                remaining -= 1
        return {key: self._listify_tree(value) for key, value in result.items()}

    def _listify_tree(self, value: Any) -> Any:
        if isinstance(value, dict):
            return self._listify({k: self._listify_tree(v) for k, v in value.items()})
        return value

    @staticmethod
    def _state_items(source: Any, from_lua: bool):
        if from_lua or isinstance(source, dict):
            return source.items()
        return enumerate(source, 1)  # list / tuple

    @staticmethod
    def _is_state_table(value: Any, from_lua: bool) -> bool:
        if from_lua:
            return lua_type(value) == "table"
        return isinstance(value, (dict, list, tuple))

    def _state_key(self, key: Any) -> Any:
        if isinstance(key, bytes):
            key = key.decode("utf-8", "replace")
        if isinstance(key, str):
            return key if len(key) <= self.MAX_STATE_STR else None
        if isinstance(key, bool):
            return None
        if isinstance(key, int):
            return key if _INT64_MIN <= key <= _INT64_MAX else None
        if isinstance(key, float):
            return None if math.isnan(key) else key
        return None

    def _state_scalar(self, value: Any) -> Any:
        if isinstance(value, bytes):
            value = value[: self.MAX_STATE_STR * 4].decode("utf-8", "replace")
        if isinstance(value, str):
            return value[: self.MAX_STATE_STR]
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            return value if _INT64_MIN <= value <= _INT64_MAX else float(value)
        if isinstance(value, float):
            return value
        return _DROP
