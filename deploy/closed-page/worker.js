// The "back tomorrow" page. While it is deployed, its route answers every request on swarm-world.4rc4de.com
// before the tunnel would, so the tunnel and the Mac can stop. Edit BACK and WHEN for another day.
const BACK = "2026-11-05T14:00:00Z"; // 9:00 AM EST
const WHEN = "Thursday, November 5, around 9am EST";

const PAGE = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Swarm World: back tomorrow</title>
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
<main>
  <div class="fire" aria-hidden="true">🔥</div>
  <h1>Be back tomorrow!</h1>
  <p class="when">Check around 9am EST.</p>
  <p>The creatures of Swarm World are resting while the machines that think for them take the night off.
     The world opens again ${WHEN.replace(", around 9am EST", "")}.</p>
  <p class="local" id="local"></p>
</main>
<script>
  try {
    const t = new Date("${BACK}");
    const s = t.toLocaleString(undefined, { weekday: "long", hour: "numeric", minute: "2-digit", timeZoneName: "short" });
    document.getElementById("local").textContent = "That's " + s + " where you are.";
  } catch (e) {}
</script>
</body>
</html>`;

export default {
  async fetch() {
    return new Response(PAGE, {
      status: 503, // a planned break: crawlers come back later and don't index this page
      headers: {
        "content-type": "text/html; charset=utf-8",
        "cache-control": "no-store", // nothing keeps it once the world is back
        "retry-after": String(Math.max(60, Math.round((Date.parse(BACK) - Date.now()) / 1000))),
      },
    });
  },
};
