# The public viewer

A read-only copy of the world for anyone with a link, served from Cloudflare's edge so the Mac only ever answers a trickle of requests.

## How it works

- Every 3 seconds (`--public-every`, `0` turns it off) the world builds snapshots: `/public/live.json` (positions, events), `/public/static.json?v=…` (the map and catalog, cached for a year because the version is in the URL), per-creature detail and the almanac. Each is built once per interval and reused for every request.
- The public page, `/public/app/`, polls those documents. It has no sockets into the world and no controls.
- Cloudflare's edge caches them (`s-maxage=3` for live data), so a thousand watchers cost the Mac about one request per document per few seconds.
- The tunnel (`cloudflared`) carries only `/public/*` (and `/`, which redirects to `/public/app/`). Everything else (`/api/*`, `/ws/*`, the steward's pages) answers 404 at the edge and is never reachable from outside.

### The one rule never to break

The tunnel config must route only plain HTTP to `http://127.0.0.1:7777`, only for `/public/*` and `/`, with `http_status:404` for everything else. Never add a `warp-routing` block, a private-network route, or a `tcp://` / `unix:` / `ssh://` / `rdp://` service.

Why: the world decides who is "this machine" (steward actions open: answering wishes, admin, voice) by the absence of the proxy headers Cloudflare adds to HTTP ingress. Any path that delivers traffic without them arrives from 127.0.0.1 and is treated as you. `tests/test_public_deploy.py` checks the template for this; check your filled-in copy the same way.

## Preview

With the world running (and `--public-every` not 0):

- `http://127.0.0.1:7777/public/app/` is exactly what watchers get. Use it to judge the page.
- `http://127.0.0.1:7777/?public` is the normal viewer in public mode, for development.

## One-time setup

You need `cloudflared` installed (`brew install cloudflared`) and a domain on Cloudflare. Replace `<host>` with the hostname, e.g. `swarm.example.com`.

1. `cloudflared tunnel login`. A browser opens: pick the domain and authorize. This writes `~/.cloudflared/cert.pem`.
2. `cloudflared tunnel create swarm-world`. It prints the tunnel id and writes `~/.cloudflared/<TUNNEL-ID>.json`.
3. `cloudflared tunnel route dns swarm-world <host>`. This creates the proxied CNAME for `<host>` in the dashboard (DNS > Records; it must show the orange cloud, Proxied).
4. `cp deploy/cloudflare/tunnel.yml ~/.cloudflared/swarm-world.yml`, then replace `<TUNNEL-ID>` (twice), `<HOME>` (your home directory, absolute) and `<HOSTNAME>` (twice) with `<host>`. Leave the ingress rules as they are. `scripts/public-tunnel.sh start` refuses to run while any `<` remains.
5. Cache rule, in the Cloudflare dashboard (details and reasons in [deploy/cloudflare/cache-rules.md](../deploy/cloudflare/cache-rules.md)):
   1. Select the domain, then Caching > Cache Rules > Create rule.
   2. Name it `Swarm World public`. Choose Custom filter expression > Edit expression, and enter `starts_with(http.request.uri.path, "/public/")`.
   3. Cache eligibility: Eligible for cache.
   4. Edge TTL: "Use cache-control header if present, bypass cache if not".
   5. Browser TTL: Respect origin.
   6. Deploy.
   7. Optional second rule (ignore the query string): expression `http.request.uri.path eq "/public/live.json" or starts_with(http.request.uri.path, "/public/creature/")`, with Cache key > Query string > Ignore.
6. Caching > Tiered Cache > turn on Smart Tiered Caching.

## Posting day

- [ ] 1. Start the world with real minds. The GPU budget versus training is your call. Set `PUBLIC_LINK` (the link shown in the About panel), which needs a world restart: stop the running world first (`start-world.sh` refuses a second copy), then `PUBLIC_LINK=https://<host>/ ./start-world.sh`.
- [ ] 2. Start the tunnel: `scripts/public-tunnel.sh start` (`status` to check; log in `runs/cloudflared.log`).
- [ ] 3. Compare `https://<host>/public/app/` with the local preview.
- [ ] 4. Check the cache is hitting. Run this twice within 3 seconds; the second should say `HIT`:
  `curl -sI https://<host>/public/live.json | grep -iE 'cf-cache-status|cache-control'`
  The same goes for `https://<host>/public/static.json?v=<version>` (the version is in `live.json`).
- [ ] 5. Nothing private is reachable. Each of these should print `404`:
  `curl -s -o /dev/null -w '%{http_code}\n' https://<host>/api/state` (and `/ws/view`, `/public/app/assets/limezu/manifest.json`, `/api/almanac`).
  Path traversal through the real hostname must also print `404` for each of these:
  `curl --path-as-is -s -o /dev/null -w '%{http_code}\n' https://<host>/public/../api/state`, `https://<host>/public%2F..%2Fapi%2Fstate`, `https://<host>/public/%2e%2e/api/state`.
- [ ] 6. Watch the Mac: `curl -s http://127.0.0.1:7777/api/metrics` (look at `tick_ms`) and `top -pid <world pid>`.

## The kill switch

`scripts/public-tunnel.sh stop` stops the tunnel this script started, at once (TERM, then KILL after 5 s). It checks that the process is really gone and exits 1 with an error if it is not; it only touches a pid that is really `cloudflared`. If it says "no tunnel started by this script was running", a `cloudflared` started another way (for example `cloudflared service install`, or a terminal) may still be serving: run `pgrep -fl cloudflared` and stop that one yourself. The world keeps running; nothing is public once no cloudflared is left. Optionally, restart the world with `--public-every 0` so it stops building snapshots too.

## Load test

(Filled in by the load test, Task 9.)

## Troubleshooting

- Always `MISS` (or no `cf-cache-status`): the cache rule is missing, its expression does not match, or the DNS record is not proxied.
- `502`: the world is down or on a different port than the one in `swarm-world.yml`.
- 404 on `/public/app/`: the hostname in `swarm-world.yml` does not match the DNS route.
- "Can’t reach the world" in the page: `live.json` is failing; fetch it directly from the local preview.
