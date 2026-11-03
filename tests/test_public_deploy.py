import os
import re
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def fake_cloudflared(tmp_path):
    fake = tmp_path / "cloudflared"
    fake.write_text(f'#!/bin/bash\necho "$@" > "{tmp_path}/marker"\nexec sleep 60\n')
    fake.chmod(0o755)
    yield fake
    pid = tmp_path / "cloudflared.pid"
    if pid.exists():  # never leave the fake sleeping behind
        subprocess.run(["bash", str(ROOT / "scripts/public-tunnel.sh"), "stop"],
                       env={**os.environ, "PIDFILE": str(pid), "LOG": str(tmp_path / "log")}, capture_output=True)


def tunnel(tmp_path, cmd, **env):
    e = {**os.environ, "PIDFILE": str(tmp_path / "cloudflared.pid"), "LOG": str(tmp_path / "cloudflared.log"),
         "CLOUDFLARED": str(tmp_path / "cloudflared"), **env}
    return subprocess.run(["bash", str(ROOT / "scripts/public-tunnel.sh"), cmd], env=e, capture_output=True, text=True, timeout=30)


def wait_for(path):
    for _ in range(40):
        if path.exists():
            return True
        time.sleep(0.05)
    return path.exists()


def test_the_tunnel_routes_only_public_paths():
    text = (ROOT / "deploy/cloudflare/tunnel.yml").read_text()
    code = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))
    paths = re.findall(r"^\s*-?\s*path:\s*(\S+)\s*$", code, re.M)
    services = re.findall(r"^\s*-?\s*service:\s*(\S+)\s*$", code, re.M)
    assert paths == ["^/public/.*$", "^/$"] and services[-1] == "http_status:404"
    assert set(services[:-1]) == {"http://127.0.0.1:7777"}
    for p in ("/api/state", "/ws/view", "/ws/node", "/index.html", "/api/admin/give"):
        assert not any(re.match(rx, p) for rx in paths), p
    # header-less traffic from 127.0.0.1 counts as this machine: only plain HTTP ingress may reach the world
    for banned in ("warp-routing", "private", "tcp://", "unix:", "ssh://", "rdp://", "bastion"):
        assert banned not in code.lower(), banned
    assert all(s.startswith(("http://127.0.0.1:", "http_status:")) for s in services)


def test_the_kill_switch_never_starts_from_the_template(tmp_path, fake_cloudflared):
    r = tunnel(tmp_path, "start", CONFIG=str(ROOT / "deploy/cloudflare/tunnel.yml"))
    assert r.returncode == 1 and "Fill in" in r.stdout + r.stderr and not (tmp_path / "marker").exists()


def test_start_refuses_a_missing_config(tmp_path, fake_cloudflared):
    r = tunnel(tmp_path, "start", CONFIG=str(tmp_path / "nope.yml"))
    assert r.returncode == 1 and "Fill in" in r.stdout + r.stderr and not (tmp_path / "marker").exists()


def test_start_status_stop(tmp_path, fake_cloudflared):
    cfg = tmp_path / "cfg.yml"
    cfg.write_text("tunnel: abc\ningress:\n  - service: http_status:404\n")
    assert tunnel(tmp_path, "start", CONFIG=str(cfg)).returncode == 0 and wait_for(tmp_path / "marker")
    assert "running (pid" in tunnel(tmp_path, "status").stdout
    assert tunnel(tmp_path, "start", CONFIG=str(cfg)).returncode != 0  # already running
    out = tunnel(tmp_path, "stop").stdout
    assert "nothing is public now" in out and "not running" in tunnel(tmp_path, "status").stdout


def test_start_world_passes_the_public_link():
    text = (ROOT / "start-world.sh").read_text()
    assert 'WORLD_ARGS+=(--public-link "$PUBLIC_LINK")' in text
    assert "#   PUBLIC_LINK:" in text
    assert subprocess.run(["bash", "-n", str(ROOT / "start-world.sh")]).returncode == 0


def test_the_runbook_covers_posting_day():
    doc = (ROOT / "docs/public-viewer.md").read_text()
    for s in ("scripts/public-tunnel.sh stop", "cf-cache-status", "/public/app/", "deploy/cloudflare/cache-rules.md", "tick_ms",
              "warp-routing", "cloudflared tunnel route dns swarm-world", "Tiered Cache", "/?public"):
        assert s in doc, s
