"""Extract a curated set of sound effects from the licensed ElvGames & Pegonthetrack "Universal Sound Effects" zips
into web/assets/sfx/ (gitignored: the audio is licensed, never commit or redistribute it) and write manifest.json,
which web/sound.js reads. Idempotent; quietly does nothing when the zips are absent (the viewer then synthesizes).

    uv run python scripts/extract_sfx.py [INBOX_DIR] [OUT_DIR]

INBOX_DIR defaults to the repo's inbox/, OUT_DIR to the repo's web/assets/sfx/."""
import json
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CREDIT = "ElvGames & Pegonthetrack"

# key -> [(zip name contains, folder (last directory) , file-stem regex)]. Keys: world sound kinds, world event kinds
# (discover, invent, ...), viewer UI cues (ui_*) and per-surface footsteps (fs_*).
SOURCES = {
    "chop": [("Crafting", "Hammering & Sawing", r"Sawing Wood|Hammer - \d \(Single"), ("Crafting", "Cutting & Shaping", r"Cutting Stone - \d \(Single")],
    "knock": [("Crafting", "Hammering & Sawing", r"Chiseling Stone"), ("Crafting", "Cutting & Shaping", r"Cutting Stone - \d \(Single")],
    "build": [("Crafting", "Assembly", r".")],
    "craft": [("Crafting", "Metal Work", r".")],
    "splash": [("Brewing", "Brewing Sounds", r"Pour Liquid|Drop & Fizz")],
    "cook": [("Brewing", "Brewing Sounds", r"Boiling|Bubbling Water|Stirring"), ("Brewing", "Ingredient Preparation", r"Hand-Mix|Mix - Pour")],
    "discover": [("Achievements", "OGG", r"Trophy (\d|1[0-2])$")],
    "invent": [("Achievements", "OGG", r"Trophy (1[3-8])$")],
    "chronicle": [("Achievements", "OGG", r"Trophy (19|2[0-3])$")],
    "wish": [("Magic and Spells 3", "Air Spells", r"Air Spell 1$"), ("Magic and Spells 4", "Air Spells", r"Air Spell - 1$"), ("Brewing", "Potion & Glass Sounds", r"Magical Chime")],
    "grant": [("Magic and Spells 4", "Healing Spells", r"."), ("Magic and Spells 3", "Buffs", r"Buff Spell 1")],
    "voice": [("Magic and Spells 4", "Buff Spells", r"."), ("Magic and Spells 3", "Air Spells", r"Air Spell 2 - No")],
    "ui_tab": [("User Interface", "Click - Activate", r"Activate \d")],
    "ui_open": [("User Interface", "Open Map - Menu", r"."), ("User Interface", "Open - Close Window", r"Open")],
    "ui_ok": [("User Interface", "Enable - Disable", r"Enable")],
    "ui_warn": [("User Interface", "Error", r".")],
    "ui_send": [("User Interface", "Start - Confirm", r"Confirm \d$"), ("User Interface", "Sliding - Swoosh Effect", r".")],
    "fs_grass": [("Footsteps Sound Effects 2", "Grass Footsteps", r".")],
    "fs_dirt": [("Footsteps Sound Effects 2", "Dirt Footsteps", r"."), ("Footsteps Sound Effects 3", "Dirt Footsteps", r".")],
    "fs_sand": [("Footsteps Sound Effects 3", "Sand Footsteps", r".")],
    "fs_gravel": [("Footsteps Sound Effects 3", "Gravel Footsteps", r".")],
    "fs_stone": [("Footsteps Sound Effects 2", "Stone Footsteps", r"."), ("Footsteps Sound Effects 3", "Stone Footsteps", r".")],
    "fs_wood": [("Footsteps Sound Effects 3", "Wood Footsteps", r"^Wood Footstep")],
    "fs_water": [("Footsteps Sound Effects 2", "Water Footsteps", r".")],
}


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def extract(inbox: Path, out: Path) -> dict:
    """Extract what is mapped into out and write out/manifest.json. Returns {key: [relative files]} (empty when no zips)."""
    zips = sorted(inbox.glob("*.zip")) if inbox.is_dir() else []
    sounds: dict[str, list[str]] = {}
    opened: dict[Path, zipfile.ZipFile] = {}
    try:
        for key, rules in SOURCES.items():
            for token, folder, pattern in rules:
                for zp in zips:
                    if token not in zp.name:
                        continue
                    if zp not in opened:
                        try:
                            opened[zp] = zipfile.ZipFile(zp)
                        except (zipfile.BadZipFile, OSError):
                            continue
                    zf = opened[zp]
                    for name in sorted(zf.namelist()):
                        p = Path(name)
                        if p.suffix.lower() != ".ogg" or p.parent.name != folder or not re.search(pattern, p.stem):
                            continue
                        rel = f"{key}/{slug(zp.name.split(' - ')[0])}-{slug(p.stem)}.ogg"
                        if rel in sounds.setdefault(key, []):
                            continue
                        dest = out / rel
                        data = zf.read(name)
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        if not dest.exists() or dest.stat().st_size != len(data):
                            dest.write_bytes(data)
                        sounds[key].append(rel)
    finally:
        for zf in opened.values():
            zf.close()
    if sounds:
        (out / "manifest.json").write_text(json.dumps({"credit": CREDIT, "sounds": sounds}, indent=1) + "\n")
    return sounds


def main(argv: list[str]) -> int:
    inbox = Path(argv[1]) if len(argv) > 1 else ROOT / "inbox"
    out = Path(argv[2]) if len(argv) > 2 else ROOT / "web" / "assets" / "sfx"
    sounds = extract(inbox, out)
    if not sounds:
        print(f"No sound zips found in {inbox}; the viewer keeps its synthesized sounds.")
        return 0
    for key, files in sounds.items():
        print(f"{key}: {len(files)} files")
    print(f"Wrote {sum(map(len, sounds.values()))} sounds and manifest.json to {out}. Credit: {CREDIT}. Never commit these.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
