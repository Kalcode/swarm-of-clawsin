#!/usr/bin/env bash
# Start everything on this Mac: oMLX (if it isn't running), the world, and a local brain node.
#   ./start-world.sh                 # local only; resumes the saved world
#   ./start-world.sh --lan           # also let other machines in the house join
#   ./start-world.sh --fresh         # brand-new world (the old save is kept as worlds/default.<time>.bak)
#   ./start-world.sh --no-inspiration  # no hunches: purely unassisted discovery
#   (flags combine, e.g. ./start-world.sh --fresh --lan; SEED=42 gives a different map)
# Settings (environment variables): MODEL, CREATURES, SLOTS, SEED, TICK, PORT, WORLD, MODEL2 ("NAME:N" second model; MODEL2= for one model only)
#   MODEL_SERVER: think on another machine's model server instead of this Mac's oMLX, e.g. the gaming PC:
#   MODEL_SERVER=http://192.168.50.42:11434/v1 MODEL=gpt-oss:20b MODEL2=qwen3.5:9b:8 ./start-world.sh --lan
#   A model can name its own server: MODEL2="Qwen3.5-4B-MLX-4bit:8@http://127.0.0.1:8000/v1" keeps it on this Mac.
#   HARNESS: layers in this world, e.g. HARNESS=plan,disclose,recall; each goes to half of every model's creatures.
#   HARNESS_ALL: layers every creature gets, e.g. HARNESS_ALL=plan.
#   PUBLIC_LINK: the link in the public viewer's About panel (docs/public-viewer.md).
#   FRONTIER=on: new land grows where creatures explore at the east or west edge (off by default)
#   ADOPT: give sleeping creatures of an old model the new minds (they keep their memories), "OLD[=NEW] ...", e.g.
#   ADOPT="gemma-4-e4b=gpt-oss:20b qwen3.5-4b=qwen3.5:9b". Without it, new models bring new creatures.
set -euo pipefail
cd "$(dirname "$0")"
# Default minds: the newest distilled student (~/models/swarm-student-*) with all three harness layers, else Qwen3.5-9B alone.
# (Gemma 4 E4B is out: it loops, issue 003.)
STUDENT="$(ls -d "$HOME"/models/swarm-student-*/ 2>/dev/null | sort | tail -n 1 || true)"; STUDENT="${STUDENT%/}"  # folders only
if [[ -z "${MODEL:-}" && -n "$STUDENT" ]]; then
  MODEL="$(basename "$STUDENT")"
  HARNESS_ALL="${HARNESS_ALL-plan,disclose,recall}"
fi
MODEL="${MODEL:-Qwen3.5-9B-MLX-4bit}"
CREATURES="${CREATURES:-12}"
MODEL2="${MODEL2-}"
SLOTS="${SLOTS:-12}"
SEED="${SEED:-7}"
TICK="${TICK:-1.0}"   # seconds per world tick; slower worlds give each creature more thoughts per day
PORT="${PORT:-7777}"
WORLD="${WORLD:-worlds/default.json}"
FRONTIER="${FRONTIER:-}"
mkdir -p runs

# Never run two worlds at once: they can share the port on macOS and steal each other's brain nodes.
if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1 || pgrep -f "python -m swarmworld.server" >/dev/null; then
  echo "A Swarm World is already running (port $PORT or a swarmworld.server process). Stop it first:"
  echo "  pkill -f start-world.sh; pkill -f swarmworld"
  exit 1
fi

start_omlx() {
  echo "Starting oMLX..."
  omlx serve --model-dir ~/models --max-concurrent-requests 16 --memory-guard-gb 20 --paged-ssd-cache-dir ~/.omlx/cache --paged-ssd-cache-max-size 10GB >> runs/omlx.log 2>&1 &
  for _ in $(seq 90); do curl -sf http://127.0.0.1:8000/v1/models >/dev/null && break; sleep 1; done
}
# This Mac's oMLX is needed unless every model thinks elsewhere (MODEL_SERVER, or MODEL...@URL)
uses_omlx() { [[ -z "${MODEL_SERVER:-}" || "${MODEL:-}${MODEL2:-}" == *"127.0.0.1:8000"* ]]; }
if [[ -n "${MODEL_SERVER:-}" ]]; then
  curl -sf --max-time 5 "$MODEL_SERVER/models" >/dev/null || { echo "No model server answering at $MODEL_SERVER"; exit 1; }
fi
if uses_omlx; then
  curl -sf http://127.0.0.1:8000/v1/models >/dev/null || start_omlx
fi

WORLD_ARGS=(--seed "$SEED" --tick "$TICK" --port "$PORT" --world "$WORLD")
NODE_ARGS=(--server "ws://127.0.0.1:$PORT" --model "$MODEL:$CREATURES" --slots "$SLOTS")
[[ -n "${MODEL2:-}" ]] && NODE_ARGS+=(--model "$MODEL2")
[[ -n "${MODEL_SERVER:-}" ]] && NODE_ARGS+=(--model-server "$MODEL_SERVER")
[[ -n "${HARNESS:-}" ]] && WORLD_ARGS+=(--harness "$HARNESS")
[[ -n "${HARNESS_ALL:-}" ]] && WORLD_ARGS+=(--harness-all "$HARNESS_ALL")
[[ -n "${PUBLIC_LINK:-}" ]] && WORLD_ARGS+=(--public-link "$PUBLIC_LINK")
[[ -n "$FRONTIER" ]] && WORLD_ARGS+=(--frontier "$FRONTIER")
for a in ${ADOPT:-}; do NODE_ARGS+=(--adopt "$a"); done
if [[ -n "${TOKEN:-}" ]]; then  # e.g. when exposing the world through a tunnel
  WORLD_ARGS+=(--token "$TOKEN")
  NODE_ARGS+=(--token "$TOKEN")
fi
for arg in "$@"; do
  case "$arg" in
    --lan)
      if [[ -z "${TOKEN:-}" ]]; then
        TOKEN="$(openssl rand -hex 4)"
        WORLD_ARGS+=(--token "$TOKEN")
        NODE_ARGS+=(--token "$TOKEN")
      fi
      WORLD_ARGS+=(--lan)
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

# Watchdog for long unattended runs: if the model server dies, bring it back (brain nodes retry on their own).
misses=0
while kill -0 "$WORLD_PID" 2>/dev/null; do
  sleep 60 & wait $!  # interruptible, so Ctrl-C or a kill stops everything at once
  uses_omlx || continue  # another machine's model server looks after itself
  if curl -sf --max-time 20 http://127.0.0.1:8000/v1/models >/dev/null; then
    misses=0
  else
    misses=$((misses + 1))
    if (( misses >= 3 )); then  # three silent minutes in a row, not just a busy moment
      echo "$(date): oMLX is not answering; restarting it"
      pkill -f "omlx-server" 2>/dev/null || true
      pkill -f "omlx serve" 2>/dev/null || true
      sleep 5
      start_omlx
      misses=0
    fi
  fi
done
