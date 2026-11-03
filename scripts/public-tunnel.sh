#!/usr/bin/env bash
# The public tunnel and its kill switch.   scripts/public-tunnel.sh {start|stop|status}
#   start   run cloudflared in the background (needs ~/.cloudflared/swarm-world.yml; docs/public-viewer.md)
#   stop    the kill switch: stop the tunnel this script started; the world keeps running
#   status  running (pid N) or not running; no network
# Environment: CONFIG, CLOUDFLARED, PIDFILE, LOG (and KILL, STOP_TICKS for tests)
set -euo pipefail
cd "$(dirname "$0")/.."
CONFIG="${CONFIG:-$HOME/.cloudflared/swarm-world.yml}"
CLOUDFLARED="${CLOUDFLARED:-cloudflared}"
PIDFILE="${PIDFILE:-runs/cloudflared.pid}"
LOG="${LOG:-runs/cloudflared.log}"
KILL="${KILL:-kill}"
STOP_TICKS="${STOP_TICKS:-50}"  # tenths of a second to wait after TERM (5 s)

# The pid in the pidfile, only if it is alive and really is our cloudflared (a reused pid is never trusted).
running_pid() {
  local pid cmd
  [[ -f "$PIDFILE" ]] || return 1
  pid="$(cat "$PIDFILE")"
  [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null || return 1
  cmd="$(ps -p "$pid" -o command= 2>/dev/null || true)"
  [[ "$cmd" == *"$(basename "$CLOUDFLARED")"* ]] || return 1
  echo "$pid"
}

# A config may only carry plain HTTP to this machine's world (docs/public-viewer.md, "The one rule").
check_config() {
  local code bad
  if [[ ! -f "$CONFIG" ]]; then
    echo "Fill in $CONFIG first (copy deploy/cloudflare/tunnel.yml; see docs/public-viewer.md)"
    return 1
  fi
  code="$(grep -v '^[[:space:]]*#' "$CONFIG" || true)"
  if grep -q '<' <<<"$code"; then
    echo "Fill in $CONFIG first (copy deploy/cloudflare/tunnel.yml; see docs/public-viewer.md)"
    return 1
  fi
  if grep -qiE 'warp-routing|private|tcp://|unix:|ssh://|rdp://|bastion' <<<"$code"; then
    echo "Refusing to start: $CONFIG has warp-routing, a private-network route or a non-HTTP service (docs/public-viewer.md, \"The one rule\")."
    return 1
  fi
  bad="$(grep -E '^[[:space:]]*-?[[:space:]]*service:' <<<"$code" | sed -E 's/^[[:space:]]*-?[[:space:]]*service:[[:space:]]*//; s/[[:space:]]+$//' | grep -vE '^(http://127\.0\.0\.1:[0-9]+/?|http_status:[0-9]+)$' || true)"
  if [[ -n "$bad" ]]; then
    echo "Refusing to start: $CONFIG has a service other than http://127.0.0.1:<port> or http_status:<code>: $bad"
    return 1
  fi
}

case "${1:-}" in
  start)
    if pid="$(running_pid)"; then echo "The tunnel is already running (pid $pid)."; exit 1; fi
    check_config || exit 1
    mkdir -p "$(dirname "$PIDFILE")" "$(dirname "$LOG")"
    nohup "$CLOUDFLARED" tunnel --config "$CONFIG" run >>"$LOG" 2>&1 &
    pid=$!
    echo "$pid" > "$PIDFILE"
    sleep 1
    if ! kill -0 "$pid" 2>/dev/null; then
      rm -f "$PIDFILE"
      echo "The tunnel died right after starting. See $LOG"
      exit 1
    fi
    echo "Tunnel started (pid $pid). Log: $LOG"
    ;;
  stop)
    if ! pid="$(running_pid)"; then
      rm -f "$PIDFILE"
      echo "no tunnel started by this script was running."
      echo "A cloudflared started another way (e.g. 'cloudflared service install') may still be serving: check 'pgrep -fl cloudflared'."
      exit 0
    fi
    $KILL "$pid" 2>/dev/null || true
    for _ in $(seq "$STOP_TICKS"); do kill -0 "$pid" 2>/dev/null || break; sleep 0.1; done
    if kill -0 "$pid" 2>/dev/null; then
      $KILL -9 "$pid" 2>/dev/null || true
      sleep 0.5
    fi
    if kill -0 "$pid" 2>/dev/null; then
      echo "ERROR: the tunnel (pid $pid) is still running after TERM and KILL. It may still be public: stop it by hand."
      exit 1
    fi
    rm -f "$PIDFILE"
    echo "Tunnel stopped. The world keeps running; nothing is public now."
    echo "(A cloudflared started another way would not be affected: check 'pgrep -fl cloudflared'.)"
    ;;
  status)
    if pid="$(running_pid)"; then echo "running (pid $pid)"; else echo "not running"; fi
    ;;
  *)
    echo "usage: $0 {start|stop|status}"
    exit 2
    ;;
esac
