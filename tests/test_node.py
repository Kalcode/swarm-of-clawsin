import asyncio
import socket

from swarmworld.mind.prompts import INTENTION_SCHEMA, build_act_messages
from swarmworld.mind.memory import Memory
from swarmworld.node.__main__ import short_tag
from swarmworld.node.brain import LLMBrain, MockBrain
from swarmworld.node.client import ModelSpec, run_node
from swarmworld.server.app import STATE, create_app
from swarmworld.world.actions import _first_json_object, parse_intention
from swarmworld.world.terrain import generate_world
from swarmworld.world.model import Creature
from swarmworld.world.perception import perceive


async def test_mock_brain_returns_valid_intention():
    w = generate_world(7)
    c = Creature("c1", "Tam", *w.spawn_point(), asleep=False)
    w.creatures[c.id] = c
    msgs = build_act_messages(w, c, Memory(), perceive(w, c))
    ok, out, err, usage = await MockBrain(1).think(msgs, INTENTION_SCHEMA, 200)
    assert ok and parse_intention(out) is not None


def test_lenient_json_parse():
    assert _first_json_object('```json\n{"action": "wait"}\n```') == {"action": "wait"}
    assert _first_json_object('Sure, here: {"action": "say", "text": "a {brace} b"} hope that helps') == {"action": "say", "text": "a {brace} b"}
    assert _first_json_object("no json here") is None


async def test_brain_error_returns_not_ok():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    brain = LLMBrain(f"http://127.0.0.1:{port}/v1", "x", timeout=2)
    ok, out, err, usage = await brain.think([{"role": "user", "content": "hi"}], None, 10)
    await brain.close()
    assert not ok and err


def test_short_tag():
    assert short_tag("Qwen3.5-9B-MLX-4bit") == "qwen3.5-9b"
    assert short_tag("gemma-4-e4b-it-4bit") == "gemma-4-e4b"
    assert short_tag("mlx-community/Qwen3.5-4B-MLX-4bit") == "qwen3.5-4b"
    assert short_tag("llama3.1:latest") == "llama3.1"


async def test_mock_node_end_to_end(aiohttp_client):
    client = await aiohttp_client(create_app(seed=7, tick_seconds=0.01))
    url = str(client.make_url("/")).replace("http", "ws")
    task = asyncio.create_task(run_node(url, "testnode", [ModelSpec("mock", MockBrain(3), 4)], slots=4))
    st = client.app[STATE]
    for _ in range(300):
        await asyncio.sleep(0.02)
        if st.metrics.models["mock"]["act_ok"] >= 8:
            break
    task.cancel()
    assert st.metrics.models["mock"]["act_ok"] >= 8
    assert len(st.world.creatures) == 4


def test_brain_turns_thinking_off_for_omlx_and_ollama():
    q = LLMBrain("http://pc:11434/v1", "qwen3.5:9b").body([], None, 260)
    assert q["chat_template_kwargs"] == {"enable_thinking": False}  # oMLX, vLLM
    assert q["reasoning_effort"] == "none" and q["max_tokens"] == 260  # Ollama
    g = LLMBrain("http://pc:11434/v1", "gpt-oss:20b").body([], None, 260)
    assert g["reasoning_effort"] == "low"  # gpt-oss can't stop reasoning, only shorten it
    assert g["max_tokens"] >= 260 + 400  # room for that reasoning before the answer
