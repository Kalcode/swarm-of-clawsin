# The long run

A 200-world-day run of the live world, with the code frozen and no steward interventions, then a data collection.
A world day is 1,200 ticks: 20 minutes at 1 tick a second, so 200 days take about 67 hours of running.

## Running it

`scripts/long-run.sh` starts and watches everything:

- `start`: oMLX, the world on its own save (`--log-prompts --frontier on`), the student node (12 creatures on
  `swarm-student-20261104`; `--adopt` brings round 3's six back), the pc node (12 on gpt-oss) if the PC answers, and the
  watchdog. The first start fixes the target, 200 days on, in `runs/long-run/target_tick`.
- `pause`: everything stops together. The world saves, both nodes stop, and the PC's model is unloaded, so the PC is
  free for games. No world days pass while paused. `WHY="..." scripts/long-run.sh pause` puts the reason in the
  steward log.
- `resume`: everything starts again on the same save; the target stays.
- `stop`: pause, then end the watchdog. `status`: what runs, the tick, the days left.

The watchdog checks every minute, never while paused. It restarts the world, oMLX or a node that died (at most once
per 10 minutes each) and saves `/api/metrics` hourly to `runs/long-run/metrics/`. At the target it pauses everything.
Every start, pause, resume and restart is a row in [steward-log.md](steward-log.md). The server itself saves every
240 ticks, so a crash loses at most 4 minutes. To run past the target, raise the number in `runs/long-run/target_tick`.

## The rules for the run

- The code is frozen at the start. No restarts for fixes; they wait for the end.
- No interventions: no wishes answered, no voice from the sky, no admin actions. The exceptions are a crash and a
  creature's welfare (starving in a way the world can't fix), each logged.
- When the PC is needed for something else, pause it all rather than let the gpt-oss creatures sleep, so the minds
  share the same days.

## What to collect at the end

- Day-by-day metrics per mind from the hourly snapshots: success, loops, crafting, building, inventions.
- The chronicle, inventions, myths and wishes; whether the frontier grew.
- Failure trends over 200 days (`scripts/review_world.py runs/<run>` for each run folder).
- The prompt-logged think logs as round 4's material: random ordinary situations, not failures only
  (docs/distillation.md, section 6).
