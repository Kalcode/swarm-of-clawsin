#!/usr/bin/env bash
# Start everything on this Mac: oMLX (if it isn't running), the world, and a local brain node.
#   ./start-world.sh                 # local only; resumes the saved world
#   ./start-world.sh --lan           # also let other machines in the house join
#   ./start-world.sh --fresh         # brand-new world (the old save is kept as worlds/default.<time>.bak)
#   ./start-world.sh --no-inspiration  # no hunches: purely unassisted discovery
#   (flags combine, e.g. ./start-world.sh --fresh --lan; SEED=42 gives a different map)
# Settings (environment variables): MODEL, CREATURES, SLOTS, SEED, TICK, PORT, WORLD, MODEL2 ("NAME:N" second model; MODEL2= for one model only)
set -euo pipefail
cd "$(dirname "$0")"
MODEL="${MODEL:-gemma-4-e4b-it-4bit}"
CREATURES="${CREATURES:-12}"
MODEL2="${MODEL2-Qwen3.5-4B-MLX-4bit:8}"
SLOTS="${SLOTS:-12}"
SEED="${SEED:-7}"
TICK="${TICK:-1.0}"   # seconds per world tick; slower worlds give each creature more thoughts per day
PORT="${PORT:-7777}"
WORLD="${WORLD:-worlds/default.json}"
mkdir -p runs

if ! curl -sf http://127.0.0.1:8000/v1/models >/dev/null; then
  echo "Starting oMLX..."
  omlx serve --model-dir ~/models --max-concurrent-requests 16 --memory-guard-gb 20 --paged-ssd-cache-dir ~/.omlx/cache --paged-ssd-cache-max-size 10GB > runs/omlx.log 2>&1 &
  for _ in $(seq 90); do curl -sf http://127.0.0.1:8000/v1/models >/dev/null && break; sleep 1; done
fi

WORLD_ARGS=(--seed "$SEED" --tick "$TICK" --port "$PORT" --world "$WORLD")
NODE_ARGS=(--server "ws://127.0.0.1:$PORT" --model "$MODEL:$CREATURES" --slots "$SLOTS")
[[ -n "${MODEL2:-}" ]] && NODE_ARGS+=(--model "$MODEL2")
for arg in "$@"; do
  case "$arg" in
    --lan)
      TOKEN="${TOKEN:-$(openssl rand -hex 4)}"
      WORLD_ARGS+=(--lan --token "$TOKEN")
      NODE_ARGS+=(--token "$TOKEN")
      ;;
    --fresh) WORLD_ARGS+=(--fresh) ;;
    --no-inspiration) WORLD_ARGS+=(--no-inspiration) ;;
    *) echo "unknown option: $arg"; exit 1 ;;
  esac
done

uv run python -m swarmworld.server "${WORLD_ARGS[@]}" &
WORLD_PID=$!
trap 'kill $WORLD_PID ${NODE_PID:-} 2>/dev/null || true' EXIT INT TERM
for _ in $(seq 30); do curl -sf "http://127.0.0.1:$PORT/api/metrics" >/dev/null && break; sleep 0.5; done
uv run python -m swarmworld.node "${NODE_ARGS[@]}" &
NODE_PID=$!
[[ -z "${NO_OPEN:-}" ]] && open "http://127.0.0.1:$PORT/" 2>/dev/null || true
wait
