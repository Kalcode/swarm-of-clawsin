# Swarm World: notes for Claude

- Before starting a world (start-world.sh, swarmworld.server or swarmworld.node), check whether one is already running:
  `lsof -nP -iTCP:7777 -sTCP:LISTEN; pgrep -fl swarmworld`. The user often runs it themselves. start-world.sh refuses to
  start a second copy.
- Never commit `inbox/`, `web/assets/limezu/` or `docs/media/`: licensed LimeZu art (see .gitignore).
- `worlds/` holds the living world's save; `--fresh` keeps the old one as `worlds/default.<time>.bak`.
- Tests: `uv run pytest`.
