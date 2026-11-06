"""The closed page (deploy/closed-page/worker.js) works out the reopening itself: the next weekday at 9am Eastern."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

WORKER = Path(__file__).resolve().parent.parent / "deploy/closed-page/worker.js"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed")

# Runs the Worker's fetch at each "now" (ISO times on stdin) with the clock pinned there.
HARNESS = r"""
const { pathToFileURL } = require('node:url');
const RealDate = Date;
let fake = 0;
globalThis.Date = class extends RealDate {
  constructor(...a) { if (a.length) super(...a); else super(fake); }
  static now() { return fake; }
};
(async () => {
  const worker = (await import(pathToFileURL(process.argv[2]).href)).default;
  const out = [];
  for (const now of JSON.parse(require('node:fs').readFileSync(0, 'utf8'))) {
    fake = RealDate.parse(now);
    const r = await worker.fetch(new Request('https://swarm-world.example/public/app/'));
    const html = await r.text();
    const pick = (re) => (html.match(re) || [])[1];
    out.push({ now, status: r.status, retry: Number(r.headers.get('retry-after')), cache: r.headers.get('cache-control'),
               back: pick(/data-back="([^"]+)"/), title: pick(/<title>(.*?)<\/title>/), h1: pick(/<h1>(.*?)<\/h1>/),
               when: pick(/<p class="when">(.*?)<\/p>/), html });
  }
  process.stdout.write(JSON.stringify(out));
})();
"""


def run(tmp_path, *nows):
    harness = tmp_path / "harness.cjs"
    harness.write_text(HARNESS)
    r = subprocess.run([NODE, str(harness), str(WORKER)], input=json.dumps(nows), capture_output=True, text=True,
                       timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@needs_node
@pytest.mark.parametrize("now, back", [
    ("2026-11-10T19:00:00Z", "2026-11-11T14:00:00.000Z"),  # Tuesday 2pm EST: Wednesday at 9am
    ("2026-11-06T20:50:00Z", "2026-11-09T14:00:00.000Z"),  # Friday afternoon: Monday, not Saturday
    ("2026-11-07T17:00:00Z", "2026-11-09T14:00:00.000Z"),  # Saturday: Monday
    ("2026-11-09T04:00:00Z", "2026-11-09T14:00:00.000Z"),  # Sunday 11pm EST (Monday in UTC): Monday at 9am
    ("2026-11-09T12:00:00Z", "2026-11-09T14:00:00.000Z"),  # Monday 7am EST: this morning
    ("2026-11-09T14:00:00Z", "2026-11-10T14:00:00.000Z"),  # Monday 9am sharp: closed now, so Tuesday
    ("2026-10-30T20:00:00Z", "2026-11-02T14:00:00.000Z"),  # Friday in EDT, Monday in EST (Nov 1 2026)
    ("2027-03-12T20:00:00Z", "2027-03-15T13:00:00.000Z"),  # Friday in EST, Monday in EDT (Mar 14 2027)
])
def test_it_reopens_on_the_next_weekday_at_9am_eastern(tmp_path, now, back):
    [page] = run(tmp_path, now)
    assert page.get("back") == back
    assert page["status"] == 503 and page["cache"] == "no-store"
    seconds = (json_ms(back) - json_ms(now)) // 1000
    assert page["retry"] == max(60, seconds)


@needs_node
def test_the_words_follow_the_reopening(tmp_path):
    tue, fri, sun, mon_early, march = run(tmp_path, "2026-11-10T19:00:00Z", "2026-11-06T20:50:00Z",
                                          "2026-11-09T04:00:00Z", "2026-11-09T12:00:00Z", "2027-03-12T20:00:00Z")
    assert tue["h1"] == "Be back tomorrow!" and tue["title"] == "Swarm World: back tomorrow"
    assert "Wednesday, November 11" in tue["html"] and "the night off" in tue["html"]
    assert fri["h1"] == "Be back Monday!" and fri["title"] == "Swarm World: back Monday"
    assert "Monday, November 9" in fri["html"] and "the weekend off" in fri["html"]
    assert sun["h1"] == "Be back tomorrow!" and "the weekend off" in sun["html"]
    assert mon_early["h1"] == "Be back soon!" and "this morning" in mon_early["html"]
    assert tue["when"] == "Check around 9am EST." and march["when"] == "Check around 9am EDT."
    assert "November 6" not in tue["html"]  # nothing left over from a hand-set date


def json_ms(iso):
    from datetime import datetime
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000)
