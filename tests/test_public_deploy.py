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
    fake.write_text(f'#!/bin/bash\necho "$@" > "{tmp_path}/marker"\nsleep 60 &\ntrap "kill $!; exit 0" TERM\nwait\n')
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


GOOD = "tunnel: abc\ningress:\n  - hostname: h.example.com\n    path: ^/public/.*$\n    service: http://127.0.0.1:7777\n  - service: http_status:404\n"


def test_a_faithful_copy_of_the_template_is_not_blocked_by_its_comments(tmp_path, fake_cloudflared):
    text = (ROOT / "deploy/cloudflare/tunnel.yml").read_text()
    filled = text.replace("<TUNNEL-ID>", "abc").replace("<HOME>", "/home/x").replace("<HOSTNAME>", "h.example.com")
    cfg = tmp_path / "cfg.yml"
    cfg.write_text(filled)
    assert tunnel(tmp_path, "start", CONFIG=str(cfg)).returncode == 0
    tunnel(tmp_path, "stop")


@pytest.mark.parametrize("bad", [
    "warp-routing:\n  enabled: true\n", "  - service: tcp://127.0.0.1:22\n", "  - service: unix:/tmp/s.sock\n",
    "  - service: ssh://127.0.0.1:22\n", "  - service: rdp://127.0.0.1:3389\n", "  - service: bastion\n",
    "  - service: http://10.0.0.5:80\n", "  - service: http://localhost:7777\n", "# private-network is fine in a comment\nprivate-network: 1\n"])
def test_start_refuses_a_config_that_could_expose_the_world(tmp_path, fake_cloudflared, bad):
    cfg = tmp_path / "cfg.yml"
    cfg.write_text(GOOD + bad)
    r = tunnel(tmp_path, "start", CONFIG=str(cfg))
    assert r.returncode == 1 and not (tmp_path / "marker").exists()


def test_start_accepts_commented_mentions(tmp_path, fake_cloudflared):
    cfg = tmp_path / "cfg.yml"
    cfg.write_text("# never add warp-routing or tcp://\n" + GOOD)
    assert tunnel(tmp_path, "start", CONFIG=str(cfg)).returncode == 0
    tunnel(tmp_path, "stop")


def test_stop_with_no_tunnel_does_not_claim_success(tmp_path, fake_cloudflared):
    r = tunnel(tmp_path, "stop")
    out = r.stdout + r.stderr
    assert "no tunnel started by this script was running" in out and "pgrep -fl cloudflared" in out
    assert "nothing is public now" not in out


def test_stop_leaves_a_foreign_process_alone(tmp_path, fake_cloudflared):
    other = subprocess.Popen(["sleep", "30"])
    try:
        (tmp_path / "cloudflared.pid").write_text(str(other.pid))
        out = tunnel(tmp_path, "stop").stdout
        assert other.poll() is None and "no tunnel started by this script was running" in out
        assert "not running" in tunnel(tmp_path, "status").stdout
    finally:
        other.kill()
        other.wait()


def test_stop_fails_loudly_when_the_process_will_not_die(tmp_path, fake_cloudflared):
    cfg = tmp_path / "cfg.yml"
    cfg.write_text(GOOD)
    assert tunnel(tmp_path, "start", CONFIG=str(cfg)).returncode == 0
    nokill = tmp_path / "nokill"
    nokill.write_text("#!/bin/bash\nexit 0\n")
    nokill.chmod(0o755)
    r = tunnel(tmp_path, "stop", KILL=str(nokill), STOP_TICKS="5")
    assert r.returncode == 1 and "nothing is public now" not in r.stdout and "still running" in r.stdout + r.stderr
    assert tunnel(tmp_path, "stop").returncode == 0  # the real kill works


def test_runbook_has_traversal_probes_and_stop_caveat():
    doc = (ROOT / "docs/public-viewer.md").read_text()
    for s in ("--path-as-is", "/public/../api/state", "public%2F..%2Fapi%2Fstate", "/public/%2e%2e/api/state",
              "pgrep -fl cloudflared", "cloudflared service install"):
        assert s in doc, s
