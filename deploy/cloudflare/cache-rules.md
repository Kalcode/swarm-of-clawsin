# Cloudflare cache rules for the public viewer

Set these in the Cloudflare dashboard for the zone that holds the hostname (Caching > Cache Rules). The world sends the
right `Cache-Control` on every `/public/*` response, so the rules only have to say "cache it and obey the origin".
Click-by-click steps are in [docs/public-viewer.md](../../docs/public-viewer.md).

## Rule "Swarm World public"

- When: custom filter expression `starts_with(http.request.uri.path, "/public/")`
- Cache eligibility: **Eligible for cache**. Cloudflare does not cache JSON by default, so without this every watcher reaches the Mac.
- Edge TTL: **Use cache-control header if present, bypass cache if not**. The world sets `s-maxage=3` on `live.json` and a year on versioned files; the edge must follow it, and a response without a header is not cached.
- Browser TTL: **Respect origin**. Browsers then honour `max-age=2` / `immutable` as the world intends.

## Optional rule: ignore the query string on live documents

- When: `http.request.uri.path eq "/public/live.json" or starts_with(http.request.uri.path, "/public/creature/")`
- Cache key: **Ignore query string**. A cache-busting `?x=random` from a script or an impatient visitor then cannot bypass the edge and hit the Mac.
- Do not apply this to `static.json`: its `?v=` is the version and must stay in the key.

## Tiered Cache

- Caching > Tiered Cache: **Smart Tiered Caching** on. Edge locations then fill from one upper tier, so one origin fetch serves the world instead of one per location.
