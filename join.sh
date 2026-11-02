#!/usr/bin/env bash
# Join a Swarm World running on another computer in the house.
#   ./join.sh --token TOKEN                         # find the world automatically, use the local model server
#   ./join.sh --token TOKEN --model llama3.1:6      # choose a model and how many creatures it drives
#   ./join.sh --token TOKEN --server ws://192.168.1.20:7777
# Needs: uv (https://docs.astral.sh/uv/) and a local model server (oMLX, Ollama, LM Studio or llama-server).
set -euo pipefail
cd "$(dirname "$0")"
command -v uv >/dev/null || { echo "Please install uv first: https://docs.astral.sh/uv/getting-started/installation/"; exit 1; }
ARGS=("$@")
if [[ " ${ARGS[*]-} " != *" --server "* ]]; then ARGS+=(--discover); fi
exec uv run python -m swarmworld.node "${ARGS[@]}"
