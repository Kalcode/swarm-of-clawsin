# Swarm World: notes for Claude

- Before starting a world (start-world.sh, swarmworld.server or swarmworld.node), check whether one is already running:
  `lsof -nP -iTCP:7777 -sTCP:LISTEN; pgrep -fl swarmworld`. The user often runs it themselves. start-world.sh refuses to
  start a second copy.
- Never edit `start-world.sh` in place while a world is running: bash re-reads a running script by byte offset. Write a
  new file and `mv` it over the old one.
- Work on `main` and push to `origin` (the user's private Forgejo, code.clausens.cloud, via `tea`/ssh). Backlog: `issues/`.
- The gaming PC lends its GPU through Ollama on the home network: [docs/gaming-pc.md](docs/gaming-pc.md).
- Never commit `inbox/`, `web/assets/limezu/` or `docs/media/`: licensed LimeZu art (see .gitignore).
- `worlds/` holds the living world's save; `--fresh` keeps the old one as `worlds/default.<time>.bak`.
- Tests: `uv run pytest`.
