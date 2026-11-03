# Swarm World

A small, AI-first tile world where a swarm of local LLM creatures lives. Each creature experiences the world from inside its own body, like one dwarf in Dwarf Fortress: it only knows what it can see within a few steps, what it hears nearby, what it carries, and how its body feels. It acts by stating an intention ("walk to the oak tree", "combine stick, stone and rope", "tell Mara where the berries are"), and the world decides what actually happens.

Creatures gather wood, stone, fiber and berries. They discover recipes by experimenting, teach each other by talking or writing on signs, build campfires and workbenches, smelt ore, and eventually find strange **terminals** that run Lua programs they write themselves.

Any computer in the house can join the same world and bring its own creatures, each driven by whatever model that machine runs.

**Watch it live: https://swarm-world.4rc4de.com** (the public, read-only viewer).

It shows a snapshot of the world every 3 seconds. Snapshots are cached at Cloudflare's edge, so watchers never load the Mac, and nothing public can change the world. To preview what the public sees, open `/public/app/` on your own world. The runbook is [docs/public-viewer.md](docs/public-viewer.md); the kill switch is `scripts/public-tunnel.sh stop`.

```
   ┌──────────────── world server (this Mac) ────────────────┐
   │  tiles · objects · creatures · memory · recipes · clock │
   │  world → text (first-person senses)                     │
   │  text → world (validated intentions)                    │
   │  Lua sandbox for terminals                              │
   └──┬──────────────┬───────────────┬──────────────┬────────┘
      │ WebSocket    │ WebSocket     │ WebSocket    │ HTTP snapshots
 brain node (Mac) brain node (PC) brain node (Air) browser viewer (you)
 oMLX · the       Ollama · gpt-oss oMLX · Qwen3.5-4B   watch, click, follow
 distilled student                                  public viewer (everyone)
                                                    Cloudflare's edge, cached
```

The minds are gpt-oss on the gaming PC (Ollama), the distilled student on this Mac (oMLX) and Qwen3.5-4B on the MacBook Air. Gemma is out: it loops ([issue 003](issues/003-replace-gemma.md)).

## Setup (once)

```bash
# oMLX with grammar-constrained output (the Homebrew build needs current Command Line Tools)
uv tool install --python 3.13 "omlx[grammar] @ https://github.com/jundot/omlx/releases/download/v0.7.3/omlx-0.7.3-cp313-cp313-macosx_15_0_universal2.whl"
# Models (already downloaded on this Mac in ~/models)
for m in Qwen3.5-4B-MLX-4bit Qwen3.5-9B-MLX-4bit; do uvx --from huggingface_hub hf download mlx-community/$m --local-dir ~/models/$m; done
```

## Quick start (this Mac)

```bash
./start-world.sh                      # oMLX + world + 12 creatures on the newest ~/models/swarm-student-* with HARNESS_ALL=plan,disclose,recall (or Qwen3.5 9B alone when there is no student), opens the viewer
MODEL=Qwen3.5-9B-MLX-4bit CREATURES=10 MODEL2= ./start-world.sh   # fewer, smarter creatures
```

The world runs at 1 second per tick (a day lasts 20 minutes; `TICK=0.5` for faster). The start script also watches oMLX and restarts it if it stops answering, so long unattended runs keep going. It saves itself to `worlds/default.json` every 4 minutes and when it stops, and resumes from there next time. For a brand-new world use `./start-world.sh --fresh` (or `uv run python -m swarmworld.server --fresh`). The old save is kept as `worlds/default.<time>.bak`; rename it back to `default.json` to return to it. Add `SEED=42` for a different map.

Or by hand, in three terminals:

```bash
omlx serve --model-dir ~/models --max-concurrent-requests 16 --memory-guard-gb 20 --paged-ssd-cache-dir ~/.omlx/cache --paged-ssd-cache-max-size 10GB
uv run python -m swarmworld.server                      # world on http://127.0.0.1:7777
uv run python -m swarmworld.node --model Qwen3.5-9B-MLX-4bit:10 --slots 12
```

No model handy? `uv run python -m swarmworld.node --mock 12` runs rule-based creatures so you can watch the world work.

### On Windows

Install [uv](https://docs.astral.sh/uv/) and [Ollama](https://ollama.com), pull a model (`ollama pull qwen3.5:9b`, or `gpt-oss:20b` with 16 GB of GPU memory), then in PowerShell:

```powershell
.\start-world.ps1                                   # world + creatures on the first model Ollama has, opens the viewer
$env:MODEL = "gpt-oss:20b"; $env:CREATURES = "12"; .\start-world.ps1 --lan   # choose the model; let the house join
```

It takes the same flags and settings as `start-world.sh` (`--fresh`, `--lan`, `--no-inspiration`; `MODEL2`, `MODEL_SERVER`, `ADOPT`, `HARNESS`...). If Ollama isn't running it starts `ollama serve` itself with the settings the creatures need (8k context, 8 requests at once); Ollama's tray app ignores those settings, so quit it first for best results. Ctrl+C stops everything, and the world saves first.

## How many creatures this Mac can run

Measured on the M1 Max (32-core GPU, 32 GB) with oMLX 0.7.3 (details in [bench/RESULTS.md](bench/RESULTS.md)):

| Model | Thinks per second (saturated) | Creatures at one thought every 20 s | Character in the world so far |
|---|---|---|---|
| Qwen3.5 4B | 1.25 | about 25 | Practical: gathers, builds fires, made the first invention |
| Qwen3.5 9B | 0.78 | about 15 | Most thoughtful, slowest |

The model server, not the world, is the bottleneck. A load test with 150 rule-based creatures making about 2,600 decisions a minute kept the world clock at full speed using about 7% of one CPU core, so one world server can host far more creatures than one laptop can think for. Add more computers to add more minds. Shared models across many creatures work best. Above about 12 requests at once, each answer just waits longer, so `--slots 12` is a good default. Install oMLX **with** its grammar extra (`omlx[grammar]`), or the JSON schema is only a suggestion rather than enforced.

## Watching

Open http://127.0.0.1:7777/. Drag to pan and scroll to zoom. Click a creature to follow it and read exactly what it senses, what it last thought, what it tried, and what happened. The **Events** tab is the world's story: speech, crafting, discoveries and failures. The **Swarm** tab compares the models that live in the world.

**A voice from the sky:** you can speak into the world from the viewer, or with `curl -X POST localhost:7777/api/voice -d '{"text":"..."}'`. Add `"x"`, `"y"` and `"radius"` to speak to one area only. Creatures hear "A booming voice from the sky says: ...". It's a lever for experiments: seed an idea, then watch whether it spreads, changes plans or gets forgotten. Steward actions work from this machine and from any device on the home network (a phone in bed is fine). They never work through a tunnel or proxy: a request relayed by Cloudflare is refused, so the public can't use them.

**Wishes:** creatures say what their world lacks ("I wish we had a proper roof"), fail to make things it has never heard of, or use the `wish` action, most of all at the wishing stone at the meadow's north edge. The **Wishes** tab ranks what they want. From the home network you can answer a wish from the sky, grant an item, or note it as something to build: the creatures' own feature-request board.

**Steward actions** (home network only), for testing new content in the live world: `curl -X POST localhost:7777/api/admin/give -d '{"creature":"Mara","item":"rope","count":2}'`, and likewise `place` (`{"kind":"basket","x":30,"y":28}`), `remove` (`{"object":"o123"}`), `move` (`{"creature":"Mara","x":30,"y":29}`) and `weather` (`{"weather":"rain","ticks":300}`). Each shows up as a Steward event.

Everything is also logged to `runs/<timestamp>/`. `events.jsonl` holds what happened. `thinks.jsonl` holds every model reply, which is useful for analysis and later for fine-tuning small models on successful behavior.

## Joining from another computer

On the Mac: `./start-world.sh --lan`. It prints a join token and announces itself on the network.

On the other machine: install [uv](https://docs.astral.sh/uv/) and a model server (oMLX on a Mac; Ollama or llama.cpp on a PC), copy this folder over, then run:

```bash
./join.sh --token TOKEN                           # finds the world automatically
./join.sh --token TOKEN --model llama3.1:8        # pick the model and how many creatures it drives
.\join.ps1 --token TOKEN --model qwen3:8b:6     # Windows PowerShell (Ollama model names work)
```

The world server keeps every creature's memory. A machine that leaves just puts its creatures to sleep where they stand, in stasis: no hunger while their mind is away. They wake up when it rejoins, or when another machine with the same model adopts them. Only short text crosses the network.

How `--adopt` counts: a node first takes back its own sleeping creatures, then adopts sleeping creatures of the models named in `--adopt`, and never more than the number it asks for in total. To adopt 4 on top of its own 8, ask for 12: `--model swarm-student-20261103:12 --adopt qwen3.5-9b=swarm-student-20261103`.

## Running it day to day

The world itself is light; the minds are heavy. So the Mac hosts the world and the viewer, and another machine's GPU can do the thinking:

```bash
# minds on the gaming PC's Ollama (setup: docs/gaming-pc.md), world on this Mac
MODEL_SERVER=http://192.168.50.42:11434/v1 MODEL=gpt-oss:20b CREATURES=12 MODEL2=qwen3.5:9b:8 ./start-world.sh --lan
```

- **New minds for old creatures:** a creature is tied to the model it was born with, so a new model normally brings newcomers and the old creatures sleep until their model returns. `ADOPT="gemma-4-e4b=gpt-oss:20b qwen3.5-4b=qwen3.5:9b"` (or `--adopt OLD[=NEW]` on any node, including `join.ps1`) gives the sleeping creatures the new minds instead. They keep their bodies, memories and bonds; what they did before stays credited to the old model in the Swarm and History tabs. Ask for more creatures than there are to adopt and newcomers fill the rest.
- **Harness layers:** `--harness plan,disclose,recall` (or `HARNESS=`) gives each layer to half of each model's creatures, so the two halves can be compared. `--harness-all` (or `HARNESS_ALL=`) gives every creature all the layers named; both are world server options. A distilled student must get `--harness-all plan,disclose,recall`, the layers it was trained with.
- **One model per GPU** when speed matters. A student sharing a GPU with a bigger model slowed to 30 s per decision (see [docs/distillation.md](docs/distillation.md), section 5).
- **Deploying a change** is a restart: Ctrl-C saves, and starting again without `--fresh` resumes the same world. Pass the old `TOKEN=...` so joined machines get back in. Brain nodes reconnect on their own.
- **Developing while it runs:** `uv run pytest` uses rule-based brains, no GPU. Never start a second world on port 7777 (`start-world.sh` refuses). For a throwaway world use another port and save file: `uv run python -m swarmworld.server --port 7791 --world /tmp/scratch.json --fresh`.
- **Benchmarks** go to a machine that isn't thinking for the live world: `uv run python bench/world_bench.py --base-url http://<machine>:11434/v1 --model <name> --episodes 3`.
- **Reviewing a run:** `uv run python scripts/review_world.py runs/<timestamp>` shows how each model spends its turns, its no-op and failure rates, and the unmet desires. The backlog lives in [issues/](issues/README.md).
- **The steward:** Claude watches the live world with the owner's permission. Interventions (answering wishes, speaking from the sky, admin actions) are logged in [docs/steward-log.md](docs/steward-log.md); observations and proposals in [docs/watch-log.md](docs/watch-log.md).

## How a creature thinks

Each creature wakes when something happens to it: it finished walking, someone spoke nearby, it got hungry, someone new came into view, or it has stood idle for 30 ticks. The world server then builds its prompt:

1. **The shared rules** (identical for every creature, so oMLX caches them),
2. **Who it is**: name, two personality traits, a drive (curious, builder, social, explorer, gatherer, tinkerer, teacher), and a temperament: proactive or reactive; leader, follower, helper or loner; routine-loving or novelty-seeking. Temperament also changes mechanics: reactive creatures think on their own less often and mostly respond to events, and novelty-seekers get more hunches,
3. **What it knows**: its goal, its own reflections, the recipes it has learned, the people it knows,
4. **Recent memories**,
5. **Right now**: the first-person description of what it senses.

The model replies with one JSON intention. Talking is woven into doing: every intention has an optional `speech` line said aloud while acting ("Mara, I'll get the stone if you find sticks!"), so creatures talk while they work instead of standing around talking about work. The constrained by a JSON schema so small models always produce something parseable. Walking, gathering in bulk and resting run as plain code over several ticks without calling the model. Every 12 thoughts, a creature reflects and rewrites its own summary.

## Knowledge, culture and the tech tree

Creatures start knowing only **rope** and **campfire**. Everything else has to be found by `combine`-ing things they carry. The world gives gentle, body-level hints: hands that "itch to combine", a feeling that "one more ingredient seems to be missing", and short descriptions of what a new thing is good for. It never gives recipes.

The first era is stone, wood and farming:

- **Stone and wood:** stone knife, stone axe (logs), stone pickaxe (ore), planks, workbench, signs, walls, doors, beds, chests.
- **Sharing:** baskets (plant fiber and a stick) and chests are shared stores anyone can `store` into or `take` from; campfires burn for about two days and can be fed sticks or logs (give) to keep them going or bring cold ashes back to life.
- **Fire and food:** campfires (light at night, cooking), roasted berries, cooked fish (needs a fishing rod), cooked eggs, bread.
- **Farming:** grass sometimes yields wheat or carrot seeds (more often with a knife). A hoe lets creatures plant seeds or berries. Crops sprout, grow and ripen; wheat goes to the millstone for flour, and flour to the fire for bread.
- **Animals:** chickens, sheep and cows roam. Feed one twice and it trusts you, stays near home, and gives eggs, milk or (with a knife) wool. Wool becomes cloth.
- **Later:** clay → bricks → furnace → copper and iron → wire → building a new terminal.

Knowledge spreads three ways:

- **Watching**: creatures within 4 steps see what someone made and how, and learn the recipe.
- **Talking**: speech carries 5 steps, so you have to walk over to share. A sentence that names a product and all its ingredients ("combine flint with a stick to make a stone knife") teaches the recipe to everyone who hears it.
- **Writing**: words carved into trees and boulders, or written on signs, stay in the world. Reading a carving that spells out a recipe teaches it, so knowledge can outlive whoever wrote it.

The first creature to make each item is recorded in the Swarm tab, with the model that drives it.

## Bodies, reflexes and minds

Following Project Sid's fast/slow split, some things happen without the model. At night, creatures with nothing to do turn in (reactive ones always, proactive ones once tired). If a campfire, bed or shelter is in sight (fires glow from afar in the dark), they walk over and sleep beside it, so villages huddle around their fires. They sleep until dawn. Only hunger or being spoken to directly wakes it, and sleeping by a bed or a shelter restores it faster. Sleepers don't think, which frees the model for whoever is still awake. Rain comes and goes: it makes crops and bushes grow faster but soaks anyone out in it. Rain and cold nights wear creatures down unless they're by a fire or a shelter. Energy drains through the day and with hard work; exhausted creatures stumble along at half speed until they rest, and resting by a bed or an invented shelter is much faster. Walking, gathering a handful, resting and fishing run as plain code over several ticks. A starving creature eats food it carries by reflex. Collapsing from hunger drops everything you carry and wakes you in the meadow. Small talk is capped in memory so it can't crowd out experience.

Curious, tinkerer and builder creatures sometimes get a vague **hunch** about something they carry ("you get a hunch that your stick and flint belong together somehow"). Hunches never spell out a recipe. Start the server with `--no-inspiration` to watch purely unassisted culture.

## The land

A fresh world is 128×288 tiles. The surface is rows 0-127, a band of solid rock fills rows 128-159, and the deep takes rows 160-287 (older saves gain the deep when they load). The surface is described here; the deep has its own section below. The creatures start in a meadow at the center; around it lie open meadow with wildflowers, oak forest, pine forest climbing toward rocky hills (boulders, flint, streaked ore rock), and a lake with a sandy beach on one shore and a marsh of reeds, pools and clay where a stream comes in. Two streams run down from the hills to the lake and a river leaves it for the edge of the map. Rivers flow: anything dropped in one drifts downstream, and off the map at the edge. Flowers, reeds, mushrooms, shells, driftwood and flint are gathered like anything else; mushrooms come up again in the forests and shells and driftwood wash up on the beach. Bees and butterflies come out on fine days, fireflies at dusk; their glow lets a creature see a step farther in the dark. A creature is told the biome it is in when that changes (and when it wakes), and which way a river flows when it comes to one (`swarmworld/world/terrain.py`, pack `nature`).

## The deep and terraforming

Under the whole surface lies the deep: caves and tunnels, an underground stream and pool, ore, and darkness. A few cave mouths on the surface lead down, and `climb` takes a creature up or down. Without light a creature sees almost nothing, so they need torches (stick, plant fiber and charcoal, lit at a campfire or from another torch). Down there they mine coal, iron, copper and crystal. Crystal makes a lamp that never burns out. One ancient terminal sits deep in the caves.

On the surface, `dig` makes trenches and pits, and a trench beside water fills with water. A pit dug deep enough opens into the deep. `fill`, with dirt, stone or sand, raises the ground back up.

In the viewer, the Surface/Underground switch (or the `U` key) changes which layer you see, and following a creature that climbs switches with it. The design is in [the spec](docs/superpowers/specs/2026-11-02-underground-design.md); the work is [issue 021](issues/021-underground-layer.md).

## The almanac

`/almanac.html` is the game's reference: a **Tech tree**, every **Thing** and **Verb**, a **Census** of what exists in this world now, the content **Packs**, and the **Roadmap**. The public copy has no Packs or Roadmap tabs. See [issue 022](issues/022-almanac.md).

## A distilled mind

[Issue 020](issues/020-distill-a-fast-mind.md) teaches a small model to play like the swarm's best. Steps: pick the best decisions from teacher runs (gpt-oss only; never Gemini outputs, which Google's terms forbid using this way), export them, train a small Apache-licensed student (Qwen3-1.7B, LoRA, on this Mac), then let it play in the live world.

Round 1 (Nov 3): trained on 19,378 unique teacher decisions in 2 h 50 m. Live, 12 student creatures succeeded 88% of the time at a median 14.6 s per decision, against 98-99% and 8.5 s for gpt-oss on the PC. It acts on habit without checking the scene. Round 2 is planned. Details: [docs/distillation.md](docs/distillation.md); a visual explainer is in `docs/explainers/distilling-a-fast-mind.html`.

## Places and society

The world names the places that matter. A cluster of things creatures built becomes someone's camp ("Bo's camp", named after its founder). The ancient terminals, the lake and the meadow are landmarks too. Creatures sense nearby places and can walk to them by name, so "meet me at Bo's camp" works.

Every conversation, gift and teaching moment between two creatures is recorded. The viewer's Society tab draws it as a graph: who talks to whom, who teaches, who feeds whom, and who is left out (`GET /api/society`).

## The Chronicle

Every 600 ticks (10 minutes at the default speed), a model reads what happened and writes a short storybook chapter: the Chronicle tab in the viewer, `GET /api/chronicle`, and `runs/<timestamp>/chronicle.md`. It's the "what happened while I was away" view.

## Art and sound

The viewer uses LimeZu's art packs (Modern Interiors, Exteriors, Farm, Serene Village) and ElvGames and Pegonthetrack sound effects. These are packs the project's owner bought and holds the licenses for. Both show in the private viewer and in the public viewer, and are credited in the About panel and in the footer. Only the viewer's built sheets and clips are served; the original packs (`inbox/`) and the build scripts never are.

None of it is in git: `web/assets/limezu/`, `web/assets/sfx/`, `inbox/` and `docs/media/` are gitignored and must not be redistributed. A fresh clone falls back to Kenney's CC0 1-Bit Pack (`?skin=kenney`) and synthesized sound. `web/assets/limezu/CATALOG.md` lists what else is in the packs for future eras.

## Inventions: creatures extend the world (rung 1)

A creature can `invent` something brand new, even building on earlier inventions (up to 3 layers deep). It gives it a name, 2–4 ingredients it carries, and a sentence about what it is. The world checks it:

- the name must be new;
- the ingredients can't already be a known recipe;
- it needs at least 3 items;
- each creature gets one invention per day.

The invention becomes a real recipe in that world. Anyone can learn it by watching, being told, or combining the same things. What it does comes from a small, safe menu chosen by its name and description:

- **food**, if it's made from food and described as edible;
- **a tool** (hammer, spear, basket...): carrying it gives a bonus when gathering;
- **a shelter** (hut, tent, lean-to...): resting beside it restores energy like a bed;
- **a light** (torch, lantern...): it lights up the night like a fire;
- otherwise **a structure** to place, shown as a "creation" with its name.

The viewer draws each invention's icon by combining its ingredients' sprites, so creatures' inventions come with their own art. Inventions are saved with the world.

Beliefs can become inventions. When creatures chase a recipe that doesn't exist (one world grew a myth about a "berry-rope"), the world tells them no one has made it yet and that they could invent it, so a shared myth can turn into a real thing.

This is the first, safe rung of the self-improvement ladder from the research: data only, never code. Later rungs (inventions with new effects, sprites drawn by an image model, agent-written mods behind tests and your approval) build on the same record.

## Terminals and the scripting arc

Two ancient **terminals** sit far from the meadow, each beside a stone tablet that explains how to talk to it in Lua. A creature standing beside a terminal can `program` it. The program then runs every 20 ticks, can `scan(r)` its surroundings up to 12 steps, `find("copper")` the nearest copper, clay or berries within 25 steps, `say()` things aloud, `print()` to its screen, and keep `memory` between runs. A terminal that announces where resources lie is real infrastructure for whoever learns to build it. Creatures can later build new terminals from copper wire and iron.

Agent code runs only inside a locked-down Lua sandbox in the world server, with no file, OS, network or Python access, and with instruction and memory limits. Brain nodes never run anything the world sends them; they only receive text and return text.

## Mixing models: the world as a benchmark

Every creature is pinned to one model for life. The Swarm tab compares models on the same metrics: thinks, latency, how often their intentions succeed, unparseable replies, repeated-failure loops, unique items made, discoveries, speech, building, and collapses from hunger. Every model receives exactly the same kind of first-person text, so differences come from the minds, not the interface. `uv run python scripts/analyze_run.py` summarizes any run per model, including how each model spends its thoughts.

### A fair, turn-based benchmark

The live world rewards fast hardware: a quicker model thinks more often. For clean comparisons, `bench/world_bench.py` runs the same small scenario for each model: a fresh world with a fixed seed and N creatures of one model. It runs turn by turn, so the clock only moves when every creature has answered. It reuses the live server's code, and reports when each model's creatures first reach milestones (rope, stone knife, stone axe, a placed campfire, an invention, a hoe, a fishing rod, planks), along with success rate, parse failures, recipes passed on, and talk.

```bash
uv run python bench/world_bench.py --model Qwen3.5-4B-MLX-4bit --episodes 3
```

## Project layout

```
swarmworld/world/      catalog (items, recipes), terrain, perception (world→text), actions (text→world), simulation
swarmworld/world/packs/ content packs: one module each, registering verbs, systems, perception lines (registry.py)
swarmworld/mind/       memory, prompts
swarmworld/server/     world server: tick loop, scheduler, metrics, WebSockets, REST, public snapshots
swarmworld/node/       brain node: LLM + mock brains, join client, CLI
swarmworld/scripting/  Lua sandbox + terminals
swarmworld/net/        LAN discovery
swarmworld/data/       items.json, recipes.json, objects.json (kinds), packs/<pack>/  ← edit these to grow the world
web/                   the viewer, the public viewer and the almanac (plain JS + Canvas; LimeZu art, Kenney CC0 fallback)
bench/                 model concurrency benchmark
scripts/               analyze_run.py, review_world.py: compare models across runs
                       teacher_runs.py, export_training.py, train_student.sh, check_student.py: the distillation pipeline
                       public-tunnel.sh, public_load_test.py: the public viewer's tunnel and its load test
deploy/                Cloudflare tunnel config and cache rules
issues/                the backlog
worlds/                the living world's saves (gitignored)
docs/                  distillation, public-viewer, gaming-pc, second-mac, writing-a-pack, steward-log, watch-log, explainers/
reports/               the research report behind the design
```

Run the tests with `uv run pytest`.
