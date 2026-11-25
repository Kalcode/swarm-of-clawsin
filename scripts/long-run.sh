#!/usr/bin/env bash
# The long run: the live world, its two brain nodes and a watchdog, for TARGET_DAYS world days (a world day is 1,200
# ticks, 20 minutes at 1 tick a second; 200 days is about 67 hours).
#
#   scripts/long-run.sh start     oMLX, the world on its own save, the student node, the pc node (if the PC answers),
#                                 then the watchdog. The first start fixes the target tick in runs/long-run/target_tick.
#   scripts/long-run.sh pause     everything stops together (the world saves; the PC's model is unloaded) and stays
#                                 stopped: world days don't pass while paused. The watchdog keeps watching, idle.
#   scripts/long-run.sh resume    start it all again on the same save; the target tick stays.
#   scripts/long-run.sh stop      pause, then end the watchdog too.
#   scripts/long-run.sh status
#
# The watchdog (every 60 s, never while paused): restarts the world, oMLX or a node that died, saves /api/metrics
# hourly to runs/long-run/metrics/, and pauses everything at the target tick. Every start, pause, resume and restart
# is a row in docs/steward-log.md. Logs: runs/long-run/*.log.
#
# PC_SERVER, the PC's model server (e.g. http://<PC-IP>:11434/v1), comes from the environment or a PC_SERVER= line in .env;
# without it the PC counts as silent and its node never starts.
# For a dry run on a copy, override WORLD_FILE, PORT, LONG_RUN_DIR, STEWARD_LOG, NODE_SUFFIX and PC_SERVER.
set -u
SELF="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
cd "$(dirname "$SELF")/.."
DIR="${LONG_RUN_DIR:-runs/long-run}"
WORLD_FILE="${WORLD_FILE:-worlds/default.json}"
PORT="${PORT:-7777}"
STEWARD_LOG="${STEWARD_LOG:-docs/steward-log.md}"
SUFFIX="${NODE_SUFFIX:-}"
mkdir -p "$DIR/metrics"
PAUSED="$DIR/paused"
TARGET_DAYS="${TARGET_DAYS:-200}"
DAY_TICKS=1200
# A setting from the gitignored .env beside the code (a NAME=value line, read, never sourced), for what the environment
# leaves unset: the owner's machine-specific values stay out of the repo.
from_env_file() { [[ -f .env ]] && sed -n "s/^$1=//p" .env | tail -n 1 | tr -d "\"'" || true; }
PC_SERVER="${PC_SERVER:-$(from_env_file PC_SERVER)}"
PC_HOST="${PC_SERVER%/v1}"
OMLX=http://127.0.0.1:8000/v1
STUDENT=swarm-student-20261104
TOKEN="${TOKEN:-$(cat "$DIR/token" 2>/dev/null)}"
[[ -n "$TOKEN" ]] || TOKEN="$(openssl rand -hex 4)"
echo "$TOKEN" > "$DIR/token"

WORLD_CMD=(uv run python -m swarmworld.server --seed 7 --tick 1.0 --port "$PORT" --world "$WORLD_FILE"
           --harness-all plan,disclose,recall --token "$TOKEN" --lan --log-prompts --frontier on)
NODE=(uv run python -m swarmworld.node --server "ws://127.0.0.1:$PORT" --token "$TOKEN")
STUDENT_CMD=("${NODE[@]}" --model-server "$OMLX" --model "$STUDENT:12" --adopt "swarm-student-20261105=$STUDENT"
             --slots 12 --name "student$SUFFIX")
PC_CMD=("${NODE[@]}" --model-server "$PC_SERVER" --model gpt-oss:20b:12 --slots 4 --name "pc$SUFFIX")

log() { echo "$(date '+%F %T') $*" >> "$DIR/watchdog.log"; }
active() { [[ ! -f "$PAUSED" ]]; }
world_up() { pgrep -f "swarmworld.server --seed 7 --tick 1.0 --port $PORT " >/dev/null; }
node_up() { pgrep -f "swarmworld.node --server ws://127.0.0.1:$PORT .*--name $1$SUFFIX\$" >/dev/null; }
omlx_up() { curl -s -m 5 "$OMLX/models" | grep -q "\"$STUDENT\""; }
pc_up() { [[ -n "$PC_SERVER" ]] && curl -s -m 5 "$PC_HOST/api/tags" >/dev/null; }
tick() { curl -s -m 5 "127.0.0.1:$PORT/api/metrics" | python3 -c 'import sys,json; print(json.load(sys.stdin)["tick"])' 2>/dev/null || echo "?"; }
saved_tick() { python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["world"]["tick"])' "$WORLD_FILE" 2>/dev/null || echo "?"; }

steward() {  # what, why, outcome: one row in the steward log
  local t; t="$(tick)"; [[ "$t" == "?" ]] && t="$(saved_tick)"
  printf '| %s | %s | %s | %s | %s |\n' "$(date '+%Y-%m-%d %H:%M')" "$t" "$1" "$2" "$3" >> "$STEWARD_LOG"
  log "steward: $1 ($3)"
}

start_omlx() {
  omlx_up && return 0
  pgrep -f omlx-server >/dev/null && { pkill -f omlx-server; sleep 5; }
  nohup omlx serve --model-dir ~/models --max-concurrent-requests 16 --memory-guard-gb 20 \
    --paged-ssd-cache-dir ~/.omlx/cache --paged-ssd-cache-max-size 10GB >> runs/omlx.log 2>&1 &
  for _ in $(seq 90); do omlx_up && return 0; sleep 1; done
  log "oMLX did not come up in 90 s"; return 1
}

start_world() {
  world_up && return 0
  nohup "${WORLD_CMD[@]}" >> "$DIR/world.log" 2>&1 &
  for _ in $(seq 60); do lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1 && return 0; sleep 1; done
  log "the world did not start listening in 60 s"; return 1
}

start_node() {  # student | pc
  node_up "$1" && return 0
  if [[ "$1" == student ]]; then nohup "${STUDENT_CMD[@]}" >> "$DIR/node-student.log" 2>&1 &
  else nohup "${PC_CMD[@]}" >> "$DIR/node-pc.log" 2>&1 &
  fi
}

stop_all() {
  if world_up; then
    pkill -TERM -f "swarmworld.server --seed 7 --tick 1.0 --port $PORT "
    for _ in $(seq 60); do world_up || break; sleep 1; done  # it saves on the way out
  fi
  pkill -TERM -f "swarmworld.node --server ws://127.0.0.1:$PORT .*--name student$SUFFIX\$"
  pkill -TERM -f "swarmworld.node --server ws://127.0.0.1:$PORT .*--name pc$SUFFIX\$"
  curl -s -m 5 "$PC_HOST/api/generate" -d '{"model":"gpt-oss:20b","keep_alive":0}' >/dev/null || true
  curl -s -m 5 -X POST "$OMLX/models/$STUDENT/unload" >/dev/null || true
}

bring_up() {
  start_omlx || return 1
  start_world || return 1
  start_node student
  if pc_up; then start_node pc; else log "the PC doesn't answer: the pc node waits for it"; fi
}

watch() {
  local last_snap=0 now t target
  local -a last=(0 0 0 0)  # the last restart of the world, oMLX, the student node, the pc node: at most one per 10 min
  log "watchdog up (target tick $(cat "$DIR/target_tick"))"
  due() { (( now - last[$1] > 600 )) && last[$1]="$now"; }
  while true; do
    now="$(date +%s)"
    if active && ! world_up && due 0; then  # the flag is read again before every restart: a pause may land mid-loop
      start_world && steward "Watchdog: restarted the world on its own save." "It had stopped." "Up."
    fi
    if active && ! omlx_up && due 1; then
      start_omlx && steward "Watchdog: restarted oMLX." "It didn't answer." "Up."
    fi
    if active && ! node_up student && due 2; then
      start_node student; steward "Watchdog: restarted the student node." "It had stopped." "Up."
    fi
    if active && ! node_up pc && pc_up && due 3; then
      start_node pc; steward "Watchdog: restarted the pc node." "It had stopped and the PC answers." "Up."
    fi
    if active && (( now - last_snap >= 3600 )); then
      last_snap="$now"
      curl -s -m 10 "127.0.0.1:$PORT/api/metrics" > "$DIR/metrics/$(date '+%Y%m%d-%H%M').json" || true
    fi
    t="$(tick)"; target="$(cat "$DIR/target_tick")"  # read each time: raise it to run on past the target
    if active && [[ "$t" != "?" ]] && (( t >= target )); then
      touch "$PAUSED"; stop_all
      steward "Watchdog: paused everything at the target." "The run reached $TARGET_DAYS world days (tick $target)." \
        "Paused; collect the data."
    fi
    sleep 60
  done
}

case "${1:-status}" in
  start)
    if world_up || node_up student || node_up pc; then echo "Already running: use status, pause or resume."; exit 1; fi
    rm -f "$PAUSED"
    if [[ ! -f "$DIR/target_tick" ]]; then
      echo $(( $(saved_tick) + TARGET_DAYS * DAY_TICKS )) > "$DIR/target_tick"
    fi
    bring_up || { echo "Start failed: see $DIR/watchdog.log"; exit 1; }
    pgrep -f "$SELF watch $DIR" >/dev/null || nohup caffeinate -i -s "$SELF" watch "$DIR" >> "$DIR/watchdog.log" 2>&1 &
    sleep 15
    steward "Long run started: the world on its own save, the student (\`$STUDENT\`, 12) and the pc node (gpt-oss, 12) if the PC answers, with the watchdog." \
      "A $TARGET_DAYS-world-day run, frozen code, no interventions but crashes and welfare." "Target tick $(cat "$DIR/target_tick")."
    "$SELF" status
    ;;
  pause)
    touch "$PAUSED"; stop_all
    steward "Paused the long run: the world saved, both nodes stopped, the PC's model unloaded." "${WHY:-Asked to.}" \
      "Paused at tick $(saved_tick); \`scripts/long-run.sh resume\` continues."
    echo "Paused at tick $(saved_tick)."
    ;;
  resume)
    rm -f "$PAUSED"
    bring_up || { echo "Resume failed: see $DIR/watchdog.log"; exit 1; }
    pgrep -f "$SELF watch $DIR" >/dev/null || nohup caffeinate -i -s "$SELF" watch "$DIR" >> "$DIR/watchdog.log" 2>&1 &
    sleep 15
    steward "Resumed the long run on the same save." "${WHY:-Asked to.}" "Up at tick $(tick)."
    "$SELF" status
    ;;
  stop)
    touch "$PAUSED"; stop_all; pkill -f "$SELF watch $DIR"
    steward "Stopped the long run and its watchdog." "${WHY:-Asked to.}" "Down at tick $(saved_tick)."
    echo "Stopped at tick $(saved_tick)."
    ;;
  watch) watch ;;
  status)
    t="$(tick)"; target="$(cat "$DIR/target_tick" 2>/dev/null || echo '?')"
    echo "world:    $(world_up && echo "up, tick $t" || echo "down (saved at tick $(saved_tick))")"
    echo "student:  $(node_up student && echo up || echo down)    pc: $(node_up pc && echo up || echo down)    oMLX: $(omlx_up && echo up || echo down)    PC: $(pc_up && echo answers || echo silent)"
    echo "watchdog: $(pgrep -f "$SELF watch $DIR" >/dev/null && echo up || echo down)    $([[ -f "$PAUSED" ]] && echo PAUSED || echo "not paused")"
    if [[ "$t" != "?" && "$target" != "?" ]]; then
      echo "days left: $(( (target - t) / DAY_TICKS )) of $TARGET_DAYS (target tick $target)"
    fi
    ;;
  *) echo "usage: $0 start|pause|resume|stop|status"; exit 2 ;;
esac
