# Cloudflare cache rules for the public viewer

Set these in the Cloudflare dashboard for the zone that holds the hostname (Caching > Cache Rules). The world sends the
right `Cache-Control` on every `/public/*` response, so the rules only have to say "cache it and obey the origin".
Click-by-click steps are in [docs/public-viewer.md](../../docs/public-viewer.md).

Scope every rule to your hostname: a zone often holds other services, and a path rule alone matches all of them. Replace
`<your hostname>` below with the hostname of the tunnel, e.g. `swarm.example.com`.

## Rule 1, "Swarm World public"

- When: custom filter expression `http.host eq "<your hostname>" and starts_with(http.request.uri.path, "/public/")`
- Cache eligibility: **Eligible for cache**. Cloudflare does not cache JSON by default, so without this every watcher reaches the Mac.
- Edge TTL: **Use cache-control header if present, bypass cache if not**. The world sets `s-maxage=3` on `live.json` and a year on versioned files; the edge must follow it, and a response without a header is not cached.
- Browser TTL: **Respect origin**. Browsers then honour `max-age=2` / `immutable` as the world intends.

## Rule 2, "Swarm World ignore query string" (required)

- When: `http.host eq "<your hostname>" and (http.request.uri.path eq "/public/live.json" or http.request.uri.path eq "/public/almanac.json" or http.request.uri.path eq "/public/history.json" or starts_with(http.request.uri.path, "/public/creature/"))`
- Cache key: **Ignore query string**, plus the same cache eligibility and TTL settings as rule 1 (a rule that sets the cache key must also say "eligible", or order it after rule 1 and let both apply).
- Why it is required: these documents take no query, so every `?x=random` is a made-up cache key that would miss at the edge and reach the Mac. (The world also answers such a request with a small redirect to the bare URL, but ignoring the query at the edge means it never gets that far.)
- Never apply this to `static.json` or `chronicle.json`: their `?v=` is the version and must stay in the key. The world redirects any other `v` (and a missing one) to the current version, so a made-up `v` costs one tiny answer, not a body. Rule 1 alone covers them, and the app files under `/public/app/`.

## Rule 3, a rate limit (suggested)

- Security > WAF > Rate limiting rules, scoped like the others: `http.host eq "<your hostname>" and starts_with(http.request.uri.path, "/public/")`.
- Counting: per IP, e.g. **120 requests per minute**, action Block for a minute. A watcher makes about 25 a minute (a live poll every 3 s plus a few details), so this is generous even for an office behind one address; a script hammering the origin hits it quickly.
- A request the edge answers from cache still counts toward the limit, which is the point: it stops one visitor from using up the connection or the free-plan quota.

## Tiered Cache

- Caching > Tiered Cache: **Smart Tiered Caching** on. Edge locations then fill from one upper tier, so one origin fetch serves the world instead of one per location.
