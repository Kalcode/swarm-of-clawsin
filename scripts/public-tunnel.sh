#!/usr/bin/env bash
# The public tunnel and its kill switch.   scripts/public-tunnel.sh {start|stop|status}
#   start   run cloudflared in the background (needs ~/.cloudflared/swarm-world.yml; docs/public-viewer.md)
#   stop    the kill switch: stop the tunnel; the world keeps running and nothing is public
#   status  running (pid N) or not running; no network
# Environment: CONFIG, CLOUDFLARED, PIDFILE, LOG
set -euo pipefail
cd "$(dirname "$0")/.."
CONFIG="${CONFIG:-$HOME/.cloudflared/swarm-world.yml}"
CLOUDFLARED="${CLOUDFLARED:-cloudflared}"
PIDFILE="${PIDFILE:-runs/cloudflared.pid}"
LOG="${LOG:-runs/cloudflared.log}"

running_pid() {
  local pid
  [[ -f "$PIDFILE" ]] && pid="$(cat "$PIDFILE")" && [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null && echo "$pid"
}

case "${1:-}" in
  start)
    if pid="$(running_pid)"; then echo "The tunnel is already running (pid $pid)."; exit 1; fi
    if [[ ! -f "$CONFIG" ]] || grep -q '<' "$CONFIG"; then
      echo "Fill in $CONFIG first (copy deploy/cloudflare/tunnel.yml; see docs/public-viewer.md)"
      exit 1
    fi
    mkdir -p "$(dirname "$PIDFILE")" "$(dirname "$LOG")"
    nohup "$CLOUDFLARED" tunnel --config "$CONFIG" run >>"$LOG" 2>&1 &
    echo $! > "$PIDFILE"
    echo "Tunnel started (pid $!). Log: $LOG"
    ;;
  stop)
    if pid="$(running_pid)"; then
      kill "$pid" 2>/dev/null || true
      for _ in $(seq 50); do kill -0 "$pid" 2>/dev/null || break; sleep 0.1; done
      kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null || true
    fi
    rm -f "$PIDFILE"
    echo "Tunnel stopped. The world keeps running; nothing is public now."
    ;;
  status)
    if pid="$(running_pid)"; then echo "running (pid $pid)"; else echo "not running"; fi
    ;;
  *)
    echo "usage: $0 {start|stop|status}"
    exit 2
    ;;
esac
