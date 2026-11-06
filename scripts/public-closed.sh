#!/usr/bin/env bash
# The "back tomorrow" page for the public viewer, so the tunnel (and the Mac) can stop overnight.
#   scripts/public-closed.sh on      put the page up (a Cloudflare Worker on swarm-world.4rc4de.com/*), then stop the tunnel
#   scripts/public-closed.sh off     start the tunnel, then take the page down: the live viewer is back
#   scripts/public-closed.sh status  what https://swarm-world.4rc4de.com answers, and the tunnel's state
# The page is deploy/closed-page; it works out the reopening itself (the next weekday at 9am Eastern). Each switch puts the new state up before it
# removes the old, so a visitor never meets an error in between. Needs wrangler signed in (npx wrangler whoami).
set -euo pipefail
cd "$(dirname "$0")/.."
PAGE_DIR=deploy/closed-page
WRANGLER=(npx -y wrangler@4)

case "${1:-}" in
  on)
    (cd "$PAGE_DIR" && "${WRANGLER[@]}" deploy)
    scripts/public-tunnel.sh stop
    ;;
  off)
    scripts/public-tunnel.sh start
    sleep 5
    (cd "$PAGE_DIR" && yes | "${WRANGLER[@]}" delete)
    ;;
  status)
    curl -s -o /dev/null -w "https://swarm-world.4rc4de.com/ answers %{http_code}\n" https://swarm-world.4rc4de.com/
    scripts/public-tunnel.sh status
    ;;
  *)
    echo "usage: $0 {on|off|status}" >&2
    exit 2
    ;;
esac
