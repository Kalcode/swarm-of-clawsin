// The "closed" page. While it is deployed, its route answers every request on swarm-world.4rc4de.com before the tunnel
// would, so the tunnel and the Mac can stop. It works out the reopening itself: the next weekday (Monday to Friday) at
// 9am Eastern after now. Saturday and Sunday stay closed, so a Friday close says Monday.
const ZONE = "America/New_York";
const OPEN_HOUR = 9;
const DAY = 86400000;

// An instant's calendar date and hour in Eastern time (EST or EDT, whichever applies then).
function eastern(ms) {
  const parts = {};
  for (const p of new Intl.DateTimeFormat("en-US", {
    timeZone: ZONE, year: "numeric", month: "numeric", day: "numeric", hour: "numeric", hourCycle: "h23",
  }).formatToParts(new Date(ms))) parts[p.type] = Number(p.value);
  return { y: parts.year, m: parts.month, d: parts.day, h: parts.hour, day: Date.UTC(parts.year, parts.month - 1, parts.day) / DAY };
}

// 9am Eastern on a calendar date: 14:00 UTC under EST, 13:00 under EDT.
function opening(y, m, d) {
  for (const behind of [5, 4]) {
    const t = Date.UTC(y, m - 1, d, OPEN_HOUR + behind);
    if (eastern(t).h === OPEN_HOUR) return t;
  }
}

function nextOpening(now) {
  const { y, m, d } = eastern(now);
  for (let i = 0; i < 8; i++) {
    const date = new Date(Date.UTC(y, m - 1, d + i));
    const weekday = date.getUTCDay();
    if (weekday === 0 || weekday === 6) continue;
    const t = opening(date.getUTCFullYear(), date.getUTCMonth() + 1, date.getUTCDate());
    if (t > now) return t;
  }
}

function say(ms, options) {
  return new Intl.DateTimeFormat("en-US", { timeZone: ZONE, ...options }).format(new Date(ms));
}

function page(now) {
  const back = nextOpening(now);
  const days = eastern(back).day - eastern(now).day;
  const weekday = say(back, { weekday: "long" });
  const soon = days === 0 ? "soon" : days === 1 ? "tomorrow" : weekday;
  const zone = new Intl.DateTimeFormat("en-US", { timeZone: ZONE, timeZoneName: "short" })
    .formatToParts(new Date(back)).find((p) => p.type === "timeZoneName").value;
  const off = weekday === "Monday" && say(now, { weekday: "long" }) !== "Monday" ? "the weekend off" : "the night off";
  const again = days === 0 ? "this morning" : say(back, { weekday: "long", month: "long", day: "numeric" });
  const html = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Swarm World: back ${soon}</title>
<style>
  html, body { height: 100%; margin: 0; }
  body {
    display: grid; place-items: center; padding: 24px; box-sizing: border-box;
    background: #2a2330; color: #f3e6c8;
    font: 17px/1.5 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
  }
  main {
    max-width: 30em; text-align: center; padding: 28px 32px;
    background: #3a2f3f; border: 3px solid #a8744c; border-radius: 6px; box-shadow: 0 0 0 3px #1d1820;
  }
  .fire { font-size: 40px; line-height: 1; }
  h1 { margin: 12px 0 6px; font-size: 26px; }
  .when { margin: 0 0 14px; font-size: 19px; color: #ffd98a; }
  p { margin: 8px 0; color: #e2d2b0; }
  .local { color: #c9b896; font-size: 15px; }
</style>
</head>
<body>
<main data-back="${new Date(back).toISOString()}">
  <div class="fire" aria-hidden="true">🔥</div>
  <h1>Be back ${soon}!</h1>
  <p class="when">Check around 9am ${zone}.</p>
  <p>The creatures of Swarm World are resting while the machines that think for them take ${off}.
     The world opens again ${again}.</p>
  <p class="local" id="local"></p>
</main>
<script>
  try {
    const t = new Date(document.querySelector("main").dataset.back);
    const s = t.toLocaleString(undefined, { weekday: "long", hour: "numeric", minute: "2-digit", timeZoneName: "short" });
    document.getElementById("local").textContent = "That's " + s + " where you are.";
  } catch (e) {}
</script>
</body>
</html>`;
  return { html, back };
}

export default {
  async fetch() {
    const now = Date.now();
    const { html, back } = page(now);
    return new Response(html, {
      status: 503, // a planned break: crawlers come back later and don't index this page
      headers: {
        "content-type": "text/html; charset=utf-8",
        "cache-control": "no-store", // nothing keeps it once the world is back
        "retry-after": String(Math.max(60, Math.floor((back - now) / 1000))),
      },
    });
  },
};
