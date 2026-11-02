# First runs: what the swarm did (1 Nov 2026)

Machine: M1 Max, 32-core GPU, 32 GB. oMLX 0.7.3 with grammar-constrained JSON. Population: 12 creatures on Gemma 4 E4B and 8 on Qwen3.5 4B, all on this one Mac. About 50–60 thoughts a minute in total, so each creature thinks roughly every 20 seconds.

## What emerged

- **First invention after about 3 minutes of world time.** Bo (Qwen 4B) put flint and a stick together and made the first stone knife. Twelve seconds later Tib made one too, and within the hour several creatures had knives.
- **Stone axe on day 2.** Lune (Qwen 4B) worked out stick + stone + rope.
- **Fires as social centers.** Creatures craft campfires and place them as night falls. Bo's thought: "I want to share the warmth with Dov who is just 5 steps east of me."
- **Information sharing without being told to.** Dune: "I found some wild grass patches just north of us that yield lots of plant fiber, which can be made into rope." Gale suggested a trip northeast for wood and berries.
- **Food sharing.** Tib: "Gale, here, take these berries. They might help fill your belly." Bea offered clay and berries to Holt.
- **Hunger and the commons.** Bushes near the meadow get picked bare. Two Gemma creatures collapsed from hunger, lost everything they carried, and woke up in the meadow.
- **Models have personalities.** Qwen 4B creatures gather 2–3 times more, craft, and made every invention so far. Gemma 4 E4B creatures are sociable: they produce about 3× more speech and placed a campfire, but almost never experiment. That's a real result for the "world as benchmark" idea.

- **Teaching, unprompted.** Elm (Qwen 9B): "Watch closely, Wade! Here is the stone knife I made by combining flint and stick." Wade: "Elm, please combine that stick and flint now so I can learn." Watching someone craft up close now teaches the recipe, so demonstrations work.
- **The first invention.** Dov (Qwen 4B, a cheerful, practical tinkerer) invented the **stone hammer**, "a heavy hammer for smashing roots" (2 stone knives + 2 flint + 2 stone, at a campfire). Invented tools now give a gathering bonus, so inventing pays off.
- **Cumulative innovation, attempted.** Dov tried to build on his own invention: a "stone chisel", "a tool that splits stone by pressing the edge of the hammer against the blade", from his stone hammer and a knife. Bo tried a "Stone Arrowhead": "A sharp arrowhead made from stone and flint, perfect for hunting." Both were blocked by rules I'd made too strict (inventions needed a fire nearby and couldn't use other inventions). Both rules are relaxed now: invent anywhere, up to 3 layers of invention on invention.
- **More firsts.** Pip invented the **glowstick** ("A glowing stick that illuminates the dark"), which now really lights the night. Lune discovered the **hoe**, which opens farming. Orla invented a **scraper** ("perfect for scraping bark from stumps").
- **Worrying about sleepers.** You noticed creatures fretting over friends who were "asleep": the 9B elders whose minds were offline, standing still and never answering. Sleepers are now clearly "curled up on the ground fast asleep", and speaking to one says they don't hear you.
- **Bonds in private reflections.** Dov's summary: "Pip matters most because his promise to help weave a rope gives me purpose even when hunger and the dark woods leave me feeling lost."
- **Bigger minds discover faster.** A Qwen 9B elder, Teo, discovered roasted berries minutes after joining.

The chronicler's first chapter:

> The third day ended as the setting sun cast long shadows. After the exhaustion of the day, Vex and Zinn found themselves overcome by hunger. Yet, amidst this need, Dov carefully shaped the first stone knife, while Lune assisted by tending a small, needed campfire. Various voices echoed with planning: Imo and Orla discussed the need for more food, while Gale suggested a journey northeast for both wood and berries. Bea offered clay and berries to Holt, hinting at the budding cooperation around this small band of survivors.

## What broke, and the fix

| Problem seen | Fix |
|---|---|
| oMLX accepted the JSON schema but didn't enforce it (no grammar extra) | Reinstalled as `omlx[grammar]`; replies are now always valid JSON |
| Social creatures "walk to" someone they're already standing beside, with a greeting attached | `walk_to` with text now speaks when the target is within earshot |
| "Gather the bush" when the bush is 2 steps away → failure, wasted think | Gathering, reading and eating walk over first, then act |
| Item names with counts ("3 stick") | Counts are stripped when resolving names |
| Creatures picking at empty bushes beside them | Gathering prefers a full bush in sight |
| Endless "It is indeed a lovely day!" | Overheard talk is capped at 3 slots in memory, and the prompt asks for useful talk; greetings dropped sharply |
| Hardly anyone experimented | When carrying 2+ kinds of things: "Your hands itch to try combining..."; near-misses say one ingredient is missing; combinations that contain a recipe make it |
| Crafted campfires stayed in pockets | Crafting a structure says to `place` it |
| Ambiguous combinations (log → planks or charcoal?) | Choose by what the creature names, then what it can finish now, then what it hasn't made yet |
| Chronicle never ran because creatures kept all slots full | The chronicle job jumps the queue (one request per 5 minutes) |
| Starving creatures kept gathering instead of eating what they carried | A hunger line in their senses lists the food they carry, and a survival reflex eats it when they're near collapse |
| With 24 creatures each thinks only every ~40 s, and hunger outpaced thought | World clock slowed to 1 s per tick (days are 20 minutes); berries are more filling |
| Inspiration never fired (creatures are never idle) | A small chance per thought, by drive (curious and tinkerer creatures most) |
| Teachers put "stick, flint" in the target and only flint in items | Combine reads ingredients from both fields |
| Inventions that are tools became statues | Inventions are food, tools (gathering bonus) or structures |
| Creatures hunted "elusive plant fiber" while standing on grass | Senses now say "Tall grass grows all around you; its tough stems could be gathered as plant fiber." Rope (3 fiber) gates axes, pickaxes, hoes and fishing rods |
| Three models on one 32 GB Mac caused memory throttling (~20 thoughts/min, 7.9 GB swap) | Back to two models here. The four 9B "elders" sleep in stasis with their memories until a bigger machine joins and adopts them |
| Sleeping creatures still got hungry and starved | Sleep is stasis: no needs while a creature's brain node is away |
| Creatures stacked on the same tile (you spotted it) | One creature per tile: walkers wait, detour or stop beside whoever is in their spot; existing piles shuffle apart; animals block too |

## Numbers to watch

`GET /api/metrics` (and the viewer's Swarm tab) per model: thoughts, average latency, action success rate, parse failures (zero since grammar), repeated-failure loops, gathered, crafted, discoveries, speech, built, collapses. Metrics persist in the world save.

## The scripting arc so far

No terminal has been programmed yet, but Pip (Qwen 4B) has made the terminal a personal quest: "the full recipe is hidden in the terminal code... Let's go deeper to solve it." Pip has read the tablet, walked to the terminal and tried `program` once with no code. Terminals now glow with "READY: awaiting a Lua program" and example code. When you used the voice from the sky ("Stone speak Lua"), Pip relayed it to Gale within a minute.

## Next steps (ideas)

- **Bring a second machine.** The four Qwen 9B elders are asleep in the world waiting for a node that can run a 9B model. Your PC with Ollama (`.\join.ps1 --token T --model qwen3:8b:6`) would wake them or add new minds.
- **Rung 2 of self-improvement:** creature-written Lua that can do more than speak and scan, e.g. a terminal-driven "golem" that gathers and hauls, under the same sandbox, plus a council vote before world rules change.
- **Generated sprites for inventions:** today an invention's icon is composed from its ingredients' sprites. A local image model, or an occasional cloud call, could draw real sprites in the LimeZu style.
- **The next era:** pottery and kilns, a bakery, a smithy, then the Modern packs for a long road to electronics, which is where the terminals point.
- **Fine-tuning:** `runs/*/thinks.jsonl` holds every decision with its outcome in `events.jsonl`. Successful episodes are the training data for a small "Swarm World native" model (the MineCollab recipe).
- **Seeing culture over days:** let the world run overnight and read the Chronicle tab in the morning.
