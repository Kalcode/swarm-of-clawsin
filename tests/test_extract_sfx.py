"""scripts/extract_sfx.py with a tiny fake zip (no real audio)."""
import importlib.util
import json
import zipfile
from pathlib import Path

spec = importlib.util.spec_from_file_location("extract_sfx", Path(__file__).resolve().parent.parent / "scripts" / "extract_sfx.py")
extract_sfx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extract_sfx)


def fake_inbox(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    base = "Footsteps Sound Effects 2 - Universal Sound Effects"
    with zipfile.ZipFile(inbox / f"{base}.zip", "w") as z:
        for i in (1, 2):
            z.writestr(f"{base}/Grass Footsteps/Grass Footstep {i}.ogg", b"x" * i)
        z.writestr(f"{base}/Snow Footsteps/Snow Footsteps 1.ogg", b"snow")
        z.writestr(f"{base}/Grass Footsteps/License.txt", b"text")
    return inbox


def test_extracts_mapped_files_and_manifest(tmp_path):
    out = tmp_path / "out"
    sounds = extract_sfx.extract(fake_inbox(tmp_path), out)
    assert set(sounds) == {"fs_grass"}
    assert len(sounds["fs_grass"]) == 2
    assert all((out / f).is_file() for f in sounds["fs_grass"])
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["sounds"] == sounds and "ElvGames" in manifest["credit"]
    again = extract_sfx.extract(tmp_path / "inbox", out)  # idempotent
    assert again == sounds


def test_missing_inbox_is_clean(tmp_path, capsys):
    out = tmp_path / "out"
    assert extract_sfx.main(["x", str(tmp_path / "nope"), str(out)]) == 0
    assert not out.exists()
    assert "synthesized" in capsys.readouterr().out


def test_shared_file_stored_once_and_stale_pruned(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    base = "Crafting and Tinkering - Universal Sound Effects"
    with zipfile.ZipFile(inbox / f"{base}.zip", "w") as z:
        z.writestr(f"{base}/Cutting & Shaping/Cutting Stone - 1 (Single 1).ogg", b"stone")  # mapped to chop and knock
    out = tmp_path / "out"
    (out / "old").mkdir(parents=True)
    (out / "old" / "stale.ogg").write_bytes(b"x")
    sounds = extract_sfx.extract(inbox, out)
    assert sounds["chop"] == sounds["knock"] and len(sounds["chop"]) == 1
    assert sorted(p.name for p in out.rglob("*.ogg")) == [Path(sounds["chop"][0]).name]
    assert not (out / "old").exists()
