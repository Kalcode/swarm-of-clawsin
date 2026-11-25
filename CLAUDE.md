# Swarm World: notes for Claude

- Before starting a world (start-world.sh, swarmworld.server or swarmworld.node), check whether one is already running:
  `lsof -nP -iTCP:7777 -sTCP:LISTEN; pgrep -fl swarmworld`. The user often runs it themselves. start-world.sh refuses to
  start a second copy.
- Never edit `start-world.sh` in place while a world is running, nor `scripts/long-run.sh` while its watchdog runs: bash
  re-reads a running script by byte offset. Write a new file and `mv` it over the old one.
- Never commit `inbox/`, `web/assets/limezu/`, `web/assets/sfx/` or `docs/media/`: licensed art and sound that belong to
  the project's owner (see .gitignore and web/assets/LICENSE-assets.txt). Without them the viewer falls back to Kenney's
  CC0 art and synthesized sound.
- `worlds/` holds the living world's save; `--fresh` keeps the old one as `worlds/default.<time>.bak`.
- Never commit `issues/`, `docs/superpowers/` or `docs/show-hn.md`: the owner's working notes (backlog, plans,
  specs, drafts), gitignored. The almanac's Roadmap tab reads `issues/README.md` when it is there.
- Tests: `uv run pytest`. `tests/test_publication.py` keeps home IPs, account IDs and those notes out of the repo.
- Personal, machine-specific notes go in `CLAUDE.local.md` (gitignored), which Claude Code loads after this file.
