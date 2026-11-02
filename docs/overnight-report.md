# Swarm World: what happened

Report written 2026-11-01 23:20. The world is on **day 7** (night, tick 8227), with 20 creatures. In the window covered: 3065 events and 1713 things said.

## Growth

From day 2 to day 7: knowledge in the society (recipes known, summed over creatures) went from **73 to 130**, structures from 4 to 20, camps from 2 to 7, and relationships from 46 to 96.

## The Chronicle

**Day 2, night.** Day 2 arrived, bringing the steady rhythm of small beginnings. Dune shared berries with Yves, and Lune entrusted a seed-bomb to Inka. While Tib, Dov, and Gale each crafted a stone knife, Bo successfully fashioned a rope from plant fiber. The flickering glow of campfires, tended by Dov and Tib, provided warmth as the creatures gathered, adding to the communal bounty of the day. Though several voices discussed finding more stone and attempting to combine materials, the immediate needs of sustenance and warmth were being tended to.

**Day 4, night.** Day 4 dawned, bringing the need for greater coordination as the group faced dwindling supplies and inclement weather. Pip found a suitable place for their tent, while Dov maintained the campfire's steady warmth. Dune, showing resourcefulness, successfully fashioned baskets from plant fibers, and Lune also honed their craft by creating stone knives and segments of rope. Despite the immediate need for sustenance prompting discussions among Yves, Cass, and Zinn about the food situation, the communal efforts continued, aided by shared burdens and the small comforts of the gathered group.

**Day 5, dusk.** Day 5 dawned, and the group found themselves gathered amidst the persistent rain. Dov maintained the campfire's warmth while Ari, Cass, and the others gathered needed sustenance, with some agreeing to check on the bounty of ripe berries. Dune contributed a signal tether, and while Holt, Lune, and Pip each contributed strands of useful rope, Orla reinforced their craft by producing another berry-rope. They shared the remains of their meal, pooling their efforts against the encroaching chill and the steady drumming of the rain.

**Day 6, night.** Day 6 found the group enduring the damp chill, the early signs of strain evident in Bo's faintness. Driven by the need for better warmth and sustenance, Lune, Gale, and the others worked together, Lune successfully combining stick, stone, and rope to create the first stone axe. While Cass and Dune continued to weave and bind, Lune also mixed berries and rope, giving birth to the first seed-bomb. The group collectively found that survival required constant movement between the dwindling meal, the pressing need for dry wood, and the vital pursuit of new shelter stability.

**Day 7, day.** Day 7 dawned, and the need for warmth and sustenance remained pressing. Gale and Lune continued their efforts, contributing to the stores of sturdy rope, while Bo crafted another basket to hold the day's findings. Tib and Dov labored together, gathering fibers and considering mixing them with clay for future use, a suggestion offered in response to the gnawing hunger. Troubling the group, the fire needed tending, and the mention of a complaining stomach hung in the air amidst the pressing need for more wood and stone.

## Firsts

- tick 178: **Lune** invented the **seed-bomb** (tool): "a small explosive for gathering grass" [qwen3.5-4b]
- tick 311: **Tib** first made **stone knife** [qwen3.5-4b]
- tick 839: **Dune** invented the **signal tether** (structure): "A rope holding three plant fibers, woven tight to form a binding cord." [qwen3.5-4b]
- tick 2737: **Pip** invented the **tent** (shelter): "A temporary shelter made from a berry, a woven fiber, and a smooth stone." [qwen3.5-4b]
- tick 4390: **Dune** first made **basket** [qwen3.5-4b]
- tick 5069: **Orla** invented the **berry-rope rope** (structure): "Something Orla invented." [qwen3.5-4b]
- tick 6232: **Lune** first made **stone axe** [qwen3.5-4b]
- tick 6982: **Dov** first made **fishing rod** [qwen3.5-4b]
- tick 7329: **Gale** invented the **warm cloak** (structure): "Something Gale invented." [qwen3.5-4b]
- tick 7652: **Orla** invented the **ember** (structure): "Something Orla invented." [qwen3.5-4b]

## Culture

65 recipes passed from one creature to another (57 by watching, 8 by listening). The latest:

- Vex learned to make stone axe by watching Gale.
- Dov learned to make stone axe by watching Gale.
- Tib learned to make stone axe by watching Gale.
- Lune learned to make ember by watching Orla.
- Bea learned to make basket by watching Dov.
- Vex learned to make basket by watching Dov.

Words left in the world:

- Gale carved words into a tree stump: "Signal Tether Recipe: 1 berry-rope rope + 2 plant fiber near campfire."

## Terminals

- No creature has programmed a terminal yet.

## Society

Strongest ties:

- Inka and Moss: 87 talks, 1 gift
- Pip and Gale: 59 talks, 1 teach
- Orla and Gale: 49 talks, 1 teach
- Tib and Gale: 30 talks, 4 teachs
- Yves and Ari: 46 talks
- Holt and Yves: 44 talks
- Zinn and Bea: 35 talks
- Yew and Lune: 33 talks

Most connected: Gale, Yves, Dune, Pip, Moss.

Camps: Tib's camp, Gale's camp, Dov's camp, Cass's camp, Bo's camp, Dov's second camp, Dov's third camp.

## The minds, compared

| model | creatures | thinks | success_rate | crafted | discoveries | inventions | built | writing | speech | collapses |
|---|---|---|---|---|---|---|---|---|---|---|
| gemma-4-e4b | 12 | 2081 | 0.97 | 25 | 0 | 0 | 1 | 0 | 1092 | 3 |
| qwen3.5-4b | 8 | 1362 | 0.74 | 120 | 4 | 6 | 20 | 1 | 618 | 1 |

## Turn-based benchmark (latest run)

Turn-based episodes of 400 ticks. Milestones: how many episodes reached it, and the average tick when they did.

| model | episodes | thinks | success | parse fail | learned | speech | crafted | rope @tick | stone_knife @tick | stone_axe @tick | campfire_placed @tick | invention @tick | hoe @tick | fishing_rod @tick | planks @tick |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gemma-4-e4b-it-4bit | 1 | 345 | 93% | 0.0 | 1.0 | 52 | 11 | 1/1 ~152 | 0/1 | 0/1 | 1/1 ~320 | 0/1 | 0/1 | 1/1 ~268 | 0/1 |
| Qwen3.5-4B-MLX-4bit | 1 | 324 | 77% | 0.0 | 3.0 | 6 | 59 | 1/1 ~152 | 1/1 ~224 | 1/1 ~369 | 1/1 ~183 | 1/1 ~178 | 0/1 | 1/1 ~456 | 0/1 |

## Overheard

- Gale to Yves: "Hello! Zinn said hello too. Shall we trade what we find for stories?"
- Yew to Imo: "Those berries sound good, but I don't feel like combining anything complex right now. Are you suggesting a specific combination?"
- Inka to Moss: "I am very hungry and tired. We should find food before the cold sets in."
- Yves: "It sounds like a good time to check those bushes; we might find something edible."
- Pip to Gale: "The grass should be dry enough to bundle, Gale. Just a few more steps and we can tie it off."
- Moss to Inka: "Okay, Inka. Let's focus on finding good wood for the shelter."
- Inka: "It is indeed dark. Finding a proper spot to settle sounds wise, though I wish we had a roaring fire nearby."
- Orla: "Let's see if seeds and fibers can start fire like carrot seeds, I'll keep testing until it works!"
