"""Run the world server:  uv run python -m swarmworld.server [--lan --token T]"""

from __future__ import annotations

import argparse
import logging
import secrets
import socket
import time
from pathlib import Path

from aiohttp import web

from .app import STATE, create_app
from .harness import LAYERS, Harness
from .persistence import save


def lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def layers(arg: str) -> set[str]:
    names = {n.strip() for n in arg.split(",") if n.strip()}
    if names - set(LAYERS):
        raise SystemExit(f"unknown harness layer(s) {sorted(names - set(LAYERS))}; choose from {', '.join(LAYERS)}")
    return names


def main() -> None:
    ap = argparse.ArgumentParser(description="Swarm World server")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--port", type=int, default=7777)
    ap.add_argument("--tick", type=float, default=1.0, help="seconds per world tick (slower = more thoughts per world-day)")
    ap.add_argument("--lan", action="store_true", help="listen on the home network so other machines can join")
    ap.add_argument("--token", default=None, help="join token required from brain nodes (auto-generated with --lan)")
    ap.add_argument("--runs", default="runs", help="directory for event/think logs")
    ap.add_argument("--world", default="worlds/default.json", help="save file; the world resumes from it if it exists")
    ap.add_argument("--fresh", action="store_true", help="start a brand-new world (the old save file is kept as .bak)")
    ap.add_argument("--no-inspiration", action="store_true", help="no vague hunches for curious creatures (purely unassisted discovery)")
    ap.add_argument("--harness", default="", help="harness layers in this world, comma separated (plan,disclose,recall)")
    ap.add_argument("--harness-all", default="", help="layers every creature gets; the rest go to half of each model")
    args = ap.parse_args()

    everyone = layers(args.harness_all)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    token = args.token or (secrets.token_urlsafe(8) if args.lan else None)
    host = "0.0.0.0" if args.lan else "127.0.0.1"
    run_dir = Path(args.runs) / time.strftime("%Y%m%d-%H%M%S")
    world_path = Path(args.world)
    if args.fresh and world_path.exists():
        world_path.rename(world_path.with_suffix(f".{time.strftime('%Y%m%d-%H%M%S')}.bak"))
    if world_path.exists():
        print(f"  Resuming the world saved in {world_path} (use --fresh for a new one)")
    app = create_app(seed=args.seed, token=token, tick_seconds=args.tick, run_dir=run_dir, world_path=world_path,
                     harness=Harness(layers(args.harness) | everyone, everyone))
    app[STATE].sim.inspiration = not args.no_inspiration

    advert = None
    if args.lan:
        ip = lan_ip()
        print(f"\n  Swarm World is open on your home network.\n  Viewer:     http://{ip}:{args.port}/\n"
              f"  Join token: {token}\n  Other machines:  ./join.sh --token {token}   (or --server ws://{ip}:{args.port})\n")
        try:
            from ..net.discovery import advertise
            advert = advertise(args.port, ip)
        except Exception as exc:  # discovery is a convenience, never a requirement
            print(f"  (LAN discovery unavailable: {exc})")
    else:
        print(f"\n  Swarm World running.  Viewer: http://127.0.0.1:{args.port}/\n")
    try:
        web.run_app(app, host=host, port=args.port, print=None, access_log=None)
    finally:
        try:
            save(app[STATE], world_path)  # last word, even if shutdown was interrupted
        except Exception as exc:
            print(f"  (final save failed: {exc})")
        if advert:
            advert.close()


if __name__ == "__main__":
    main()
