"""Join the world as a brain node:

    uv run python -m swarmworld.node --model Qwen3.5-9B-MLX-4bit:10
    uv run python -m swarmworld.node --discover --token T          # from another machine on the LAN
    uv run python -m swarmworld.node --mock 8                       # no model server needed
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import platform
import re
import socket
import sys
import urllib.request
from pathlib import Path

from .brain import LLMBrain, MockBrain
from .client import FatalNodeError, ModelSpec, run_node

CANDIDATE_SERVERS = ["http://127.0.0.1:8000/v1", "http://127.0.0.1:11434/v1", "http://127.0.0.1:1234/v1", "http://127.0.0.1:8080/v1"]


def short_tag(model: str) -> str:
    tag = model.split("/")[-1].lower()
    tag = re.sub(r"[-_](mlx|gguf|instruct|it|chat|q\d\w*|\d+bit)(?=$|[-_])", "", tag)
    tag = re.sub(r"[-_](mlx|gguf|instruct|it|chat|q\d\w*|\d+bit)(?=$|[-_])", "", tag)
    return tag.replace(":latest", "")


CLOUD_KEYS = {"generativelanguage.googleapis.com": "GOOGLE_API_KEY"}


def key_for(base_url: str, given: str | None) -> str | None:
    """An API key for a cloud model server, from --api-key, the environment or ./.env (never from the command line
    shown in the process list unless you pass it). Local servers need none."""
    if given:
        return given
    name = next((v for host, v in CLOUD_KEYS.items() if host in base_url), None)
    if not name:
        return None
    key = os.environ.get(name, "").strip()
    if not key and Path(".env").is_file():
        for line in Path(".env").read_text().splitlines():
            k, sep, v = line.strip().partition("=")
            if sep and k.strip() == name:
                key = v.strip().strip("\"'")
    return key or None


def list_models(base_url: str, api_key: str | None = None) -> list[str] | None:
    try:
        req = urllib.request.Request(f"{base_url.rstrip('/')}/models",
                                     headers={"Authorization": f"Bearer {api_key}"} if api_key else {})
        with urllib.request.urlopen(req, timeout=2) as r:
            data = json.loads(r.read())
        return [m["id"] for m in data.get("data", [])]
    except Exception:
        return None


def hardware() -> dict:
    mem = None
    try:
        mem = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (ValueError, OSError, AttributeError):
        pass
    return {"host": socket.gethostname(), "os": platform.platform(), "machine": platform.machine(),
            "cpus": os.cpu_count(), "ram_gb": round(mem / 2**30, 1) if mem else None}


def suggest_creatures(ram_gb: float | None) -> int:
    if not ram_gb:
        return 6
    return 4 if ram_gb < 12 else 8 if ram_gb < 24 else 12 if ram_gb < 48 else 20


MODEL_ARG = re.compile(r"^(?P<name>[^@]+?)(?::(?P<n>\d+))?(?:@(?P<url>https?://.+?))?(?::(?P<n2>\d+))?$")


def parse_model_arg(arg: str) -> tuple[str, int | None, str | None]:
    """MODEL[:CREATURES][@SERVER]: e.g. gpt-oss:20b:12@http://192.168.50.42:11434/v1 (a trailing :N is the count)."""
    m = MODEL_ARG.match(arg.strip())
    if not m:
        return arg, None, None
    n = m.group("n") or m.group("n2")
    return m.group("name"), int(n) if n else None, m.group("url")


def apply_adopts(specs: list[ModelSpec], adopts: list[str]) -> None:
    """--adopt gemma-4-e4b (to the first model) or --adopt qwen3.5-4b=qwen3.5:9b (to a named one)."""
    for a in adopts:
        old, _, new = a.partition("=")
        spec = next((s for s in specs if not new or s.tag in (new, short_tag(new))), None)
        if spec is None:
            sys.exit(f"--adopt {a}: '{new}' isn't one of this node's models ({', '.join(s.tag for s in specs)})")
        spec.adopt.append(short_tag(old.strip()))


def main() -> None:
    ap = argparse.ArgumentParser(description="Join Swarm World as a brain node")
    ap.add_argument("--server", default=None, help="world address, e.g. ws://192.168.1.20:7777 (default: local, or --discover)")
    ap.add_argument("--discover", action="store_true", help="find the world on the home network")
    ap.add_argument("--token", default=None, help="join token printed by the world server")
    ap.add_argument("--model-server", default=None, help="OpenAI-compatible base URL (default: auto-detect oMLX/Ollama/LM Studio)")
    ap.add_argument("--api-key", default=None)
    ap.add_argument("--model", action="append", default=[],
                    help="MODEL[:CREATURES][@SERVER], repeatable for a mixed population; @SERVER thinks on another machine")
    ap.add_argument("--mock", type=int, default=0, metavar="N", help="add N rule-based creatures (no LLM)")
    ap.add_argument("--adopt", action="append", default=[], metavar="OLD[=NEW]",
                    help="give sleeping creatures of model OLD a new mind (they keep their memories); "
                         "NEW picks which of your models (default: the first)")
    ap.add_argument("--slots", type=int, default=8, help="concurrent model requests")
    ap.add_argument("--name", default=None, help="node name (default: hostname)")
    ap.add_argument("--temperature", type=float, default=0.8)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    hw = hardware()
    specs: list[ModelSpec] = []
    if args.model:
        parsed = [parse_model_arg(m) for m in args.model]
        base = args.model_server
        if not base and any(url is None for _, _, url in parsed):
            base = next((u for u in CANDIDATE_SERVERS if list_models(u, args.api_key) is not None), None)
            if not base:
                sys.exit("No model server found. Start oMLX (omlx serve --model-dir ~/models) or Ollama, or pass --model-server.")
        listed: dict[str, list[str]] = {}
        for name, n, url in parsed:
            server = url or base
            api_key = key_for(server, args.api_key)
            available = listed.setdefault(server, [a.removeprefix("models/") for a in list_models(server, api_key) or []])
            n = n or suggest_creatures(hw.get("ram_gb"))
            if available and name not in available:
                alt = next((a for a in available if a in (f"{name}:latest", f"mlx-community/{name}")), None)
                if not alt:
                    sys.exit(f"Model '{name}' isn't on {server}. Available: {', '.join(available)}")
                name = alt
            specs.append(ModelSpec(short_tag(name), LLMBrain(server, name, api_key, temperature=args.temperature), n))
            print(f"  {name}: {n} creatures, thinking on {server}")
    if args.mock:
        specs.append(ModelSpec("mock", MockBrain(), args.mock))
    if not specs:
        base = args.model_server or next((u for u in CANDIDATE_SERVERS if list_models(u, args.api_key)), None)
        models = [m for m in (list_models(base, args.api_key) or []) if "embed" not in m.lower()] if base else []
        if not models:
            sys.exit("No --model given and no model server with models found. Try --mock 8 to test without a model.")
        name = models[0]
        n = suggest_creatures(hw.get("ram_gb"))
        print(f"  Using {name} on {base} for {n} creatures (pass --model to choose).")
        specs.append(ModelSpec(short_tag(name), LLMBrain(base, name, args.api_key, temperature=args.temperature), n))

    apply_adopts(specs, args.adopt)
    server = args.server
    if not server and args.discover:
        from ..net.discovery import discover
        print("  Looking for Swarm World on your network...")
        server = asyncio.run(discover(8.0))
        if not server:
            sys.exit("No world found. Ask for the address and pass --server ws://IP:7777")
        print(f"  Found {server}")
    server = server or "ws://127.0.0.1:7777"
    name = args.name or socket.gethostname().split(".")[0]
    print(f"  Joining {server} as '{name}' with " + ", ".join(f"{s.creatures}x {s.tag}" for s in specs))
    try:
        asyncio.run(run_node(server, name, specs, args.slots, args.token, hw))
    except FatalNodeError as exc:
        sys.exit(f"World refused to let us join: {exc}")
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
