"""Brains: turn chat messages into a reply. LLMBrain calls any OpenAI-compatible server;
MockBrain is a rule-based stand-in for tests and offline demos."""

from __future__ import annotations

import json
import random
import re
import time
from typing import Any

import aiohttp

from ..world.actions import _first_json_object

THINK_RE = re.compile(r"<think>.*?</think>", re.S)


class LLMBrain:
    def __init__(self, base_url: str, model: str, api_key: str | None = None, extra_body: dict | None = None,
                 timeout: float = 90.0, temperature: float = 0.8, disable_thinking: bool = True):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.extra_body = extra_body or {}
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.temperature = temperature
        self.disable_thinking = disable_thinking
        self.use_schema = True
        self._session: aiohttp.ClientSession | None = None

    async def session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
            self._session = aiohttp.ClientSession(timeout=self.timeout, headers=headers)
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    def body(self, messages: list[dict], schema: dict | None, max_tokens: int) -> dict:
        body: dict[str, Any] = {"model": self.model, "messages": messages, "max_tokens": max_tokens,
                                "temperature": self.temperature}
        if schema and self.use_schema:
            body["response_format"] = {"type": "json_schema",
                                       "json_schema": {"name": "intention", "schema": schema, "strict": True}}
        if self.disable_thinking:
            body["chat_template_kwargs"] = {"enable_thinking": False}
        body.update(self.extra_body)
        return body

    async def think(self, messages: list[dict], schema: dict | None, max_tokens: int) -> tuple[bool, Any, str | None, dict]:
        try:
            sess = await self.session()
            for attempt in range(2):
                async with sess.post(f"{self.base_url}/chat/completions", json=self.body(messages, schema, max_tokens)) as r:
                    text = await r.text()
                    if r.status == 400 and schema and self.use_schema and attempt == 0 and "response_format" in text:
                        self.use_schema = False  # server doesn't support constrained output; fall back to lenient parsing
                        continue
                    if r.status != 200:
                        return False, None, f"HTTP {r.status}: {text[:300]}", {}
                    data = json.loads(text)
                    break
            msg = (data.get("choices") or [{}])[0].get("message") or {}
            content = THINK_RE.sub("", msg.get("content") or "").strip()
            usage = data.get("usage") or {}
            if schema:
                obj = _first_json_object(content)
                return True, (obj if obj is not None else content), None, usage
            return True, content, None, usage
        except Exception as exc:  # network down, timeout, bad JSON: report, don't crash
            return False, None, f"{type(exc).__name__}: {exc}"[:300], {}


class MockBrain:
    """Cheap rule-based behavior so the world can be tested without a model server."""

    def __init__(self, seed: int = 0):
        self.rng = random.Random(seed)
        self.model = "mock"

    async def close(self) -> None:
        pass

    async def think(self, messages: list[dict], schema: dict | None, max_tokens: int) -> tuple[bool, Any, str | None, dict]:
        user = messages[-1]["content"]
        if not schema:
            return True, "I have been gathering things and watching the others. I mean to keep making tools.", None, {}
        now = user.split("Right now:")[-1]
        carry = re.search(r"You carry: (.*)\.", now)
        carry = carry.group(1) if carry else ""

        def has(item: str, n: int = 1) -> bool:
            m = re.search(rf"(\d+) {item}\b", carry)
            return bool(m and int(m.group(1)) >= n)

        def out(action: str, target: str = "", items: list | None = None, text: str = "", count: int = 1, thought: str = "") -> tuple:
            return True, {"thought": thought or f"I'll {action} {target}".strip(), "action": action, "target": target,
                          "items": items or [], "text": text, "count": count, "goal": ""}, None, {"prompt_tokens": len(user) // 4, "completion_tokens": 30}

        hungry = any(w in now for w in ("very hungry", "starving", "a bit hungry"))
        if hungry and has("berries"):
            return out("eat", "berries")
        if has("stick") and has("stone") and has("rope") and "stone axe" not in carry:
            return out("combine", items=["stick", "stone", "rope"], thought="These might fit together.")
        if has("plant fiber", 3) and not has("rope"):
            return out("craft", "rope")
        if self.rng.random() < 0.12:
            return out("say", text=self.rng.choice(["Hello there!", "Anyone found stone?", "The berries are good here.", "I'm making rope."]))
        for kind in ("berry bush", "oak tree", "pine tree", "boulder"):
            if re.search(rf"{kind}e?s?(?:, the nearest)? right beside you", now):
                if kind == "berry bush" and not hungry and has("berries", 3):
                    continue
                return out("gather", kind, count=2)
        if not has("plant fiber", 3) and not has("rope") and self.rng.random() < 0.4:
            return out("gather", "grass", count=3)
        for kind in ("berry bush", "boulder", "oak tree", "pine tree"):
            if kind in now and self.rng.random() < 0.7:
                return out("walk_to", kind)
        return out("explore", self.rng.choice(["north", "south", "east", "west", "northeast", "southwest"]))
