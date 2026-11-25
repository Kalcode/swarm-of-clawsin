"""The repository is public: what it must never carry, and the scripts that keep the owner's machine-specific values in
the gitignored .env instead (PC_SERVER, CLOUDFLARE_ACCOUNT_ID)."""

import os
import re
import shutil
import socket
import subprocess
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# The owner's working notes and licensed art and sound: on the owner's machine, never in the repo.
NEVER_TRACKED = ("issues/", "docs/superpowers/", "docs/show-hn.md", "inbox/", "web/assets/limezu/", "web/assets/sfx/",
                 "docs/media/", ".env", "CLAUDE.local.md")
# The owner's home subnet, a Cloudflare account id written into a config, and personal mail addresses.
NEVER_WRITTEN = (re.compile(r"192\.168\.50\.\d"), re.compile(r"account_id\s*=\s*\"?[0-9a-f]{32}"),
                 re.compile(r"[\w.+-]+@(gmail|icloud|outlook|hotmail|yahoo)\.com", re.I))


def tracked_files() -> list[str]:
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a git checkout")
    return [p for p in out.decode().split("\0") if p]


def test_working_notes_and_licensed_assets_are_not_tracked():
    bad = [p for p in tracked_files() if p.startswith(NEVER_TRACKED) or p in NEVER_TRACKED]
    assert bad == []


def test_no_home_address_account_id_or_personal_email_in_tracked_files():
    hits = []
    for rel in tracked_files():
        path = ROOT / rel
        if not path.is_file():   # removed in the working tree, not yet committed
            continue
        try:
            text = path.read_text()
        except UnicodeDecodeError:
            continue   # images and fonts
        hits += [f"{rel}: {m.group(0)}" for pattern in NEVER_WRITTEN for m in pattern.finditer(text)]
    assert hits == []


def test_the_code_is_mit_licensed():
    assert (ROOT / "LICENSE").read_text().startswith("MIT License\n")
    assert tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["license"] == "MIT"


def copy_script(tmp_path: Path, rel: str) -> Path:
    dest = tmp_path / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / rel, dest)
    return dest


def fake_tool(bin_dir: Path, name: str, body: str) -> None:
    bin_dir.mkdir(exist_ok=True)
    tool = bin_dir / name
    tool.write_text(f"#!/usr/bin/env bash\n{body}\n")
    tool.chmod(0o755)


def env_without(*names: str, **extra: str) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in names}
    env.update(extra)
    return env


def busy_port() -> socket.socket:
    """A port already listening: start-world.sh stops at its "already running" check, which comes after the PC_SERVER
    check and before anything starts, so even a broken check can't start oMLX or a world."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen()
    return s


def test_start_world_refuses_a_pc_node_without_pc_server(tmp_path):
    script = copy_script(tmp_path, "start-world.sh")   # no .env beside it
    with busy_port() as busy:
        run = subprocess.run([str(script)], env=env_without("PC_SERVER", PC="gpt-oss:20b:12",
                                                            PORT=str(busy.getsockname()[1])),
                             capture_output=True, text=True, timeout=30)
    assert run.returncode == 1 and "needs PC_SERVER" in run.stderr
    assert "already running" not in run.stdout   # it stopped at the PC_SERVER check, before anything else


def test_start_world_reads_pc_server_from_the_env_file(tmp_path):
    script = copy_script(tmp_path, "start-world.sh")
    (tmp_path / ".env").write_text("VOYAGE_API_KEY=x\nPC_SERVER=http://192.0.2.1:11434/v1\n")
    with busy_port() as busy:
        run = subprocess.run([str(script)], env=env_without("PC_SERVER", PC="gpt-oss:20b:12",
                                                            PORT=str(busy.getsockname()[1])),
                             capture_output=True, text=True, timeout=30)
    assert "needs PC_SERVER" not in run.stderr
    assert run.returncode == 1 and "already running" in run.stdout


def test_long_run_without_pc_server_never_asks_a_pc(tmp_path):
    script = copy_script(tmp_path, "scripts/long-run.sh")   # no .env beside it
    calls = tmp_path / "curl-calls"
    fake_tool(tmp_path / "bin", "curl", f'echo "$*" >> "{calls}"; exit 7')
    run = subprocess.run([str(script), "status"],
                         env=env_without("PC_SERVER", "TOKEN", PATH=f"{tmp_path / 'bin'}:{os.environ['PATH']}",
                                         PORT="1", LONG_RUN_DIR=str(tmp_path / "lr")),
                         capture_output=True, text=True, timeout=60)
    assert "PC: silent" in run.stdout
    assert "/api/tags" not in (calls.read_text() if calls.exists() else "")


def test_closed_page_passes_the_account_from_the_env_file_to_wrangler(tmp_path):
    copy_script(tmp_path, "scripts/public-closed.sh")
    fake_tool(tmp_path / "scripts", "public-tunnel.sh", "exit 0")
    (tmp_path / "deploy" / "closed-page").mkdir(parents=True)
    (tmp_path / ".env").write_text("CLOUDFLARE_ACCOUNT_ID=0123456789abcdef0123456789abcdef\n")
    seen = tmp_path / "account-seen"
    fake_tool(tmp_path / "bin", "npx", f'echo "${{CLOUDFLARE_ACCOUNT_ID:-unset}}" > "{seen}"')
    run = subprocess.run([str(tmp_path / "scripts" / "public-closed.sh"), "on"],
                         env=env_without("CLOUDFLARE_ACCOUNT_ID", PATH=f"{tmp_path / 'bin'}:{os.environ['PATH']}"),
                         capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stderr
    assert seen.read_text().strip() == "0123456789abcdef0123456789abcdef"
