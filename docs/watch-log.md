# Watch log: what I'd tweak, add, moderate or administer

Claude's running notes from watching the live world. The user asked for them on Nov 3: "tail everything and get a log
of items you want to tweak, add, help mod and admin". This file holds observations and proposals. What I actually did
to the world goes in [steward-log.md](steward-log.md). Tags:
- **tweak:** change existing behaviour.
- **add:** something new.
- **mod:** creature behaviour worth stepping in on.
- **admin:** infrastructure.

## 2026-11-03 (fresh world at 10:42; public at https://swarm-world.4rc4de.com)

- **admin (done 10:48, tick ~340):** the student slowed from 2.8 s to 30 s per decision while it shared this Mac's GPU with
  Qwen3.5-9B. The 9B model's work starves the small one. So this Mac now runs the student only: its node adopted the four
  Qwen-9B creatures, making 12. Rule of thumb: one model per machine's GPU when speed matters.
- **tweak (node):** `--adopt` only fills the count the node asks for, and its own creatures come first. Adopting 4 more
  needed `:12`, not `:8`. Either the node should add adoptees on top of its own count, or the help text should say so.
- **tweak (student, round 2):** the student's failures in its first ~70 decisions are all "acts on what usually works"
  without checking the scene:
  - gathering from a boulder that isn't within reach;
  - combining a rope with things that don't go together.

  The teacher on the PC succeeds 99% of the time, the student 82%. Round 2: have the teacher label the student's own
  failed situations (DAgger), and test on several held-out episodes instead of one.
- **tweak (Qwen3.5-9B, before it left):** two failures were schema misuse: `give` with nothing in `items`, and
  `combine` with too few things. If Qwen returns, a one-line example for `give` in the prompt's tips might help.
- **admin:** the Air's Qwen3.5-4B node answers in about 33 s per decision (p50) with 3 slots: slow but alive. The Air's
  node runs inside its Claude session, so it stops if that session ends.
- **mod:** 16 wishes already by tick 441. Read and answer the ones worth answering (steward policy).
- **tweak (wishes):** by tick ~450 there are 36 "wishes", and every one was pulled from a reflection; no creature has
  made an explicit wish. Many are fragments: "steady supply", "tool", "world had more of the right kind",
  "group to keep trading fibers opal should". Taking wishes from reflections is noisy. Options:
  - take only explicit wish phrasing;
  - group the fragments by the item they name;
  - show the reflected ones apart from real wishes, in the panel and on the public page.
- **mod (balance, watching):** fiber and rope are the early bottleneck: about 20 of the 36 are about fiber, rope, grass
  or sticks; others ask for stone or a place to trade. Nothing granted. It's early, and finding tall grass is part of the
  game. If fiber is still the theme by day 2, consider faster grass regrowth or a bigger fiber yield.
- **admin (11:00, tick ~600):** with this Mac to itself, the student runs at a median of 14.6 s per decision (p90
  19 s), with 88% succeeding, for 12 creatures. This morning, with 6 creatures, it was 2.8 s. Qwen-9B did unload
  (oMLX log: freed 8.3 GB). The cause is load:
  - 12 prompts of ~1,850 tokens, of which only 46% come from the prompt cache (58% this morning), so the Mac reads
    roughly three times the prompt per minute;
  - the 1.7B model's speed is spent on reading the prompt, not on writing the answer.

  Today's speeds: gpt-oss on the PC's gaming GPU at 8.5 s, the student at 15 s, Qwen3.5-4B on the Air at 29 s.
  Round-2 levers:
  - a shorter prompt (the student needs fewer tips than a general model);
  - keeping the stable parts of the prompt first, so the cache hits more often;
  - fewer creatures per Mac when speed is the point.

### 11:13 watch (tick 1,981)
- **admin:** all healthy: 24 creatures awake; the nodes pc, student and macbook-air connected; the tunnel serving
  `live.json` from the edge (`HIT`); no errors in the world or node logs.
- **Minds since tick 600:**

  | Model | Acts | Success | p50 | Note |
  |---|---|---|---|---|
  | gpt-oss | 725 | 94% | 8.9 s | down from 99%: harder phase, and the rope stone (below) |
  | Student | 673 | 86% | 16.1 s | |
  | Qwen3.5-4B (Air) | 84 | 85% | 33.5 s | |

  No think errors anywhere.
- **mod (watching), the rope-stone fad:**
  - Teo (gpt-oss) invented the "rope stone" at tick 314: "a rope wrapped stone, useful for levers", made from
    2 rope + 2 stone. Holt (student) learned it by watching, and it spread.
  - 207 actions have involved it since, 152 of them succeeding: making it, giving it away, talking about it.
  - It does nothing: no recipe uses it, and placing it is all it does. Yet it costs 2 rope (6 fiber) while fiber is the
    most-wished-for thing.
  - No intervention: it's culture, and I want to see whether it fades on its own.
- **tweak (inventions):** an invention whose description matches no effect from the safe menu ends up inert, but
  creatures can't tell. When they make or examine one, say something like "it doesn't seem to do anything yet", so a
  useless fad costs less. Or let the inventor know at invent time what it does.
- **mod (wishes), fiber:** the top explicit wish: said 19 times by Hux, Ira, Mika, Gil, Opal and Inka. Fiber is
  actually unlimited: any grass or forest tile gives it, 1 per 2 ticks by hand and 2 with a stone knife. The felt
  shortage is gathering speed, and recipes that eat it (rope takes 3, a rope stone 6). Not granted.
- **add (idea):** if fiber still dominates by day 2, add a perception hint when gathering fiber by hand, e.g.
  "a stone knife would cut twice as much".
- **tweak (defaults, 11:40):** `start-world.sh` still defaults to 12 Gemma 4 E4B and 8 Qwen3.5-4B creatures, though
  Gemma is out (it loops; issue 003). The README now flags it, as do its "How many creatures" table and
  docs/gaming-pc.md. Proposal:
  - default the Mac to the latest student (`swarm-student-<date>`, with `HARNESS_ALL=plan,disclose,recall`) when one is
    in ~/models, otherwise Qwen3.5-9B;
  - drop Gemma from the setup's download loop.

  Not done yet: it changes what the quick start gives a newcomer, so it waits for a quiet moment. Edit start-world.sh
  only as `.new` + `mv`.

### 11:43 watch (tick 3,769)
- **admin:** healthy: 24 awake, three nodes, tunnel `HIT`, no errors. No public watchers yet.
- **Minds since tick 1,981:**

  | Model | Acts | Success | p50 |
  |---|---|---|---|
  | gpt-oss | 683 | 83% (from 94%) | 9.3 s |
  | Student | 718 | 77% (from 86%) | 16.2 s |
  | Qwen3.5-4B | 118 | 76% (from 85%) | 32.9 s |

  The drop has two causes:
  - the rope-stone fad, now 280 actions since 11:13; gpt-oss's top failure is "You don't have any rope stone" x46;
  - hungry students eating grass: "You can't eat plant fiber" x30.
- **mod (done 11:44, 11:46), hunger:** student creatures eat grass when hungry; Ira and Opal collapsed. I spoke from
  the sky to the hungry group, and fixed the world's refusal so it names the nearest food. See the steward log.
  - Watch whether the eat-grass failures stop.
  - Round-2 training should include the teacher's answers in these hungry moments.
- **add (seen):** Elm (Qwen3.5-4B, the Air) invented a rain shelter at tick 2,341 while shivering in the rain.
- **mod (watching):** the rope-stone fad is growing, not fading. It drains rope and turns into failed gives. If it
  still dominates at the next check-in, consider letting the world say "the rope stone doesn't do anything yet" when
  someone makes one (the tweak noted at 11:13).

### 12:15 watch (tick 5,695)
- **admin:** healthy: 24 awake, three nodes, tunnel `HIT`, no errors; no public watchers yet.
- **Minds since tick 3,769:**

  | Model | Acts | Success | p50 |
  |---|---|---|---|
  | gpt-oss | 876 | 79% | 9.4 s |
  | Student | 1,059 | 76% | 15.9 s |
  | Qwen3.5-4B | 114 | 79% | 37.8 s |
- **mod (follow-up), eat-grass:** after the 11:46 food hint, refusals to eat fell from 30 to 11 in half an hour, and 8
  of those 11 now name the nearest food. Better, not gone; keep watching.
- **mod (done 12:17, 12:18), stone:** the meadow's boulders are worked out, with the nearest 35+ steps away.
  - gpt-oss creatures beside the old tablet tried "gather stone" from it 53 times.
  - I answered the stone wish with directions, and the refusal now says "Stone: knock it off boulders".
- **mod (watching), the rope stone:** 411 actions in 30 minutes, about 20% of all actions, and the top failure for
  gpt-oss and the student:
  - "You don't have any rope stone";
  - "you'd need 2 rope (you have 1)".

  The user enjoys it ("some hilarious stuff emerging"): 260 lines of speech about it, and Dree handing them out like
  favours. Left alone on purpose.
- **tweak (parser):** Dree (gpt-oss) put a `combine`'s items in `target` as a JSON-list string
  (`["rope","rope","flint","flint"]`) and got "Combine what?" in a loop. Parse a JSON list in `target` as the items for
  combine and craft.
- **add (seen):** Mirth (Qwen3.5-4B, the Air) invented "spark fragments" at tick 5,610. Hux made the day's first
  explicit wish to the sky.

### 12:45 watch (tick 7,496)
- **admin:** healthy: 24 awake, two nodes (the Air retired at 12:33, and its four creatures moved to gpt-oss), tunnel
  `HIT`, no errors.
- **Minds since tick 5,695:**

  | Model | Acts | Success | p50 | Note |
  |---|---|---|---|---|
  | gpt-oss | 805 | 78% | 9.1 s | with 12 creatures since 12:33: 8.5 s, so no slowdown |
  | Student | 810 | 75% | 15.4 s | |
  | Qwen3.5-4B, before retiring | 58 | 81% | 38.6 s | |
- **mod (watching), stone:** the creatures name the stone tablet (31 times since 12:18) and placed rope stones (30) as
  gather targets on purpose. gpt-oss believes they hold stone. The new refusal ("Stone: knock it off boulders") doesn't
  change their minds, because no boulder is in sight. The meadow's boulders ran out by about tick 5,000, and the nearest
  are 35+ steps away. Two options:
  - **balance:** boulders near the meadow slowly come back, or old campsites leave rubble you can gather stone from;
  - **text:** a refusal that names a material also says where the nearest source the creature remembers is, e.g.
    "you remember boulders 35 steps southeast", using `_recall` with the source kinds.

  No hotfix: it costs them time, not lives, and it's the next balance question for the stone age.
- **mod (follow-up), eat-grass:** 12 refused meals in this stretch, about the same as last time, most now naming the
  nearest food. No collapses since tick 3,208.
- **mod (watching), the rope stone:** 345 actions in this stretch, steady at about 20%. Mirth invented the "sparkstone"
  (spark fragments, stone and 2 rope); Vex invented "plant fiber rope" (2 strong cord and 2 …). The fad is spawning
  inventions.

### 13:07 watch (tick 8,797)
- **admin:** healthy: 24 awake, two nodes, tunnel up, no errors, no public watchers.
- **Minds since tick 7,496:**

  | Model | Acts | Success | p50 |
  |---|---|---|---|
  | gpt-oss | 685 | 81% | 8.9 s |
  | Student | 777 | 75% | 13.9 s |

  The student is a little faster, now that the Air's four creatures are on the PC.
- **mod (done 13:09), stone:** stone is the top need. Evidence:
  - wishes: "two stones for the campfire" said 51 times, "stone for the fire" 14, "please give us some stones"
    wished twice;
  - 21 failed attempts to make a "stone tablet";
  - nobody has gathered from a boulder since the 12:17 answer.

  The 87 boulders within 40 steps are out of sight (the nearest is 23 south), and creatures don't explore that far
  unprompted. I spoke from the sky to the meadow and pointed them south. Next time: has anyone gathered stone from a
  boulder?
  The balance fix from 12:45 still stands: boulders near camp slowly come back, or camps leave rubble. So does the text
  fix: a material refusal names the source the creature remembers.
- **mod (watching), the rope stone:** fading as stone runs out, at 181 actions, down from 345 to 411. Teo, its
  inventor, has spent his last turns trying to get stone back out of rope stones.
- **mod (follow-up), eat-grass:** 22 refused meals this stretch, up from 12. Still no collapses since tick 3,208.
- **tweak:** gpt-oss "program"s a terminal from afar 18 times ("There's no terminal within reach to program"). Like
  `eat` and `gather`, `program` could walk to a terminal it sees or remembers before refusing.

### 13:37 watch (tick 10,595)
- **admin:** healthy: 24 awake, two nodes, tunnel up, no errors, no public watchers.
- **Minds since tick 8,797:**

  | Model | Acts | Success | p50 |
  |---|---|---|---|
  | gpt-oss | 887 | 81% | 9.2 s |
  | Student | 1,095 | 75% | 12.9 s |
- **mod (follow-up), stone: worked.** After the 13:09 voice, 10 creatures headed south to the boulder field, and 48
  stone gathers followed ("Gale gathered 3 stone, 1 flint"). Stone flows again. The balance fix (boulders coming back
  near camp) stays open for when this field runs out.
- **tweak (done 13:39), the combine parser:** 35 of 37 "Combine what?" failures were gpt-oss writing the ingredients
  as a JSON-looking list in `target`, with empty items. Dree was 13 failures in a row. `combine` now strips the brackets
  and quotes.
- **mod (watching), eat-grass:** 34 refused meals, all from the student: it tries to eat plant fiber (16) or grass
  (15) even with the food hint. It's a learned habit the hint doesn't break. Round 2 should take the teacher's answers
  in exactly these hungry moments; a single sky voice won't fix it. Still no collapses since tick 3,208.
- **add (seen):** Mirth wished to the sky: "I wish for flint, so I can strike a fire." Flint turns up while gathering
  stone, so the trip south answers it.
- **mod (watching), the rope stone:** 166 actions, steady and lower.

### 14:07 watch (tick 12,387)
- **admin:** healthy: 24 awake, two nodes, tunnel up, no errors, no public watchers. Two restarts to deploy fixes:
  13:39 (combine lists) and 14:11 (walled in).
- **Minds since tick 10,595:**

  | Model | Acts | Success | p50 |
  |---|---|---|---|
  | gpt-oss | 908 | 78% | 8.9 s |
  | Student | 1,022 | 76% | 13.2 s |

  No failure streaks of 5+ after Gale was freed. "Combine what?" fell from 35 to 14 after the parser fix (other
  phrasings remain). The rope stone is at 52 actions: the fad is ending.
- **mod (done 14:09, 14:11), Gale's basket fort:** Gale ringed herself with six storage baskets (ticks 9,888-10,278).
  With an oak and a bush they walled her in, and 28 walks to Jun failed. Moved out, and the world now refuses a
  placement that would wall in the one placing it.
- **tweak (wish board), a real bug:** the board returns at most 60 entries. Mirth's eight explicit wishes to the sky
  for flint never appeared, because 60 reflected fragments ("steady supply") fill it. Fix: explicit wishes (wished,
  failed, said) always outrank reflected-only ones, and the 60-cap applies after that ordering, or reflected fragments
  get their own list. This matters most on the public page, where watchers see the Wishes tab.
- **mod (done 14:12):** Mirth got the flint it prayed for, a gift from the sky.
- **add (seen), hoarding:** Mirth carries 16 rope, 54 sticks and 80 plant fiber, while others wish for fiber. That's
  emergent inequality. A "share" tip, or a gentle need to carry less (inventory weight), could be future content; for
  now it's a story.
- **mod (watching), eat-grass:** 20 refused meals this stretch, all from the student.

### 14:37 watch (tick 14,181)
- **admin:** healthy: 24 awake, two nodes, tunnel up, no errors, no public watchers.
- **Minds since tick 12,387:** both improved after the day's fixes.

  | Model | Acts | Success | Before | p50 |
  |---|---|---|---|---|
  | gpt-oss | 843 | 86% | 78% | 9.1 s |
  | Student | 993 | 81% | 76% | 13.3 s |

  No failure streaks. The walled-in rule hasn't had to refuse anything yet.
- **tweak (done 14:40), cooking:** gpt-oss creatures who carry an unplaced campfire combined ["fish", "campfire"]
  beside a burning one: 25 failures, and only 2 fish cooked all day. A station named among ingredients now counts as
  the place you work.
- **mod (done 14:41), Mirth's prayers:** the flint gift taught Mirth that praying works: six more flint prayers in
  150 ticks. I answered once without a gift. Lesson for stewarding: a grant for an explicit, repeated prayer is a sweet
  moment, but repeat grants turn the sky into a vending machine. Grant once, then point to the source.
- **tweak (server):** POST /api/voice with malformed JSON returns 500 with a traceback. It should be 400, like the
  other steward endpoints. My own bad request found it (empty coordinates during a restart).
- **mod (watching), eat-grass:** 35 refused meals, all from the student, though the hint now names food 4 steps away.
  Round-2 data.
- **mod, the rope stone:** 69 actions. The fad has settled into a background habit.

### 15:07 watch (tick 15,976)
- **admin:** healthy: 24 awake, two nodes, tunnel up, no public watchers. The one traceback was the 14:40 bad voice
  JSON.
- **Minds since tick 14,181:**

  | Model | Acts | Success | p50 |
  |---|---|---|---|
  | gpt-oss | 970 | 90% (from 86%) | 9.1 s |
  | Student | 1,022 | 76% (from 81%) | 13.1 s |

  No failure streaks. The student dropped because of hunger: 73 refused meals, and Ira collapsed again at tick 14,848.
- **mod (done 15:13), eat-grass, final fix:** the hint named the food, but the student kept trying to eat grass.
  `eat` of something inedible now walks to the nearest food in sight and eats there, for every mind. It's a body
  reflex, the same as "eat berries" walking to a bush. Watch: collapses should stop. The student's habit still goes to
  round 2.
- **add (seen):** Teo invented the "bark-to-stone converter" ("to get rope-stones fast"); the fad's inventor is still
  at it. Mirth invented a "warm reed blanket", and worked on a tent site.
- **mod (watching), Mirth:** 4 more prayers since the no-gift answer, down from 6.

### 15:37 watch (tick 17,771)
- **admin:** healthy: 24 awake, two nodes, tunnel up, no errors, no public watchers.
- **Minds since tick 15,976:**

  | Model | Acts | Success | p50 |
  |---|---|---|---|
  | gpt-oss | 881 | 89% | 9.0 s |
  | Student | 1,084 | 86% (from 76%) | 13.0 s |

  No failure streaks. The student is now close to gpt-oss on success, mostly because the eat reflex removed its worst
  loop.
- **mod (follow-up), eat-grass: fixed.** Since the 15:13 reflex there have been 6 walks to food (all succeeded) and 1
  refusal with no food in sight, against 73 refusals in the half hour before. No collapses.
- **mod (watching), hungry sleepers:** Jun, Holt and Mika (all student) went to sleep at satiety 10-11, 1-3 steps from
  bushes with fruit, after giving away seeds rather than eating. The world wakes a sleeper at hunger 5, and the
  reflexes should then feed them. Check for collapses next time.
- **tweak (idea):** a creature lying down to sleep while hungry, with food within a few steps, could eat first: a
  bedtime reflex. Only if collapses come back.

### 16:09 watch (tick 19,699)
- **admin:** the PC wound down at 16:08, and its 12 gpt-oss creatures sleep until morning. 12 student creatures are
  awake; tunnel up, no errors.
- **Minds since tick 17,771:**

  | Model | Acts | Success | p50 |
  |---|---|---|---|
  | gpt-oss | 908 | 85% | 9.1 s |
  | Student | 1,094 | 88% | 13.4 s |

  The student was ahead for the first time this stretch (with the world's eat reflex helping it).
- **mod (follow-up), hungry sleepers: fine.** Jun went from 10 to 27 after waking. The lowest awake satiety is now Ula
  at 22.
- **mod (morning), Suki:** Suki (gpt-oss) ended the day with 21 failures in a row: "You don't have any plant fiber rope"
  and "You don't have any rope". 44 and 41 of those across gpt-oss in this stretch: wanting an item it doesn't have.
  - **tweak:** like the material hints, "You don't have any X" could add how X is made when the creature knows the
    recipe ("You know how: 2 strong cord + ..."), and where to get it when it's a material.
  - Check Suki when the PC rejoins.

### 16:48 (review follow-ups deployed)
- **tweak (balance), seeds as food:** the reviewer counted 765 eat intents that name seeds today (570 from the student,
  177 from gpt-oss), and 630 seed meals against 441 berry meals. Seeds (food value 3) are a staple, which eats the next
  harvest.
  - Lower their food value to 1.
  - Or say "you'd rather plant these" when eating seeds while berries are in reach.
  - Watch whether farming ever starts.
- **tweak (minor):** plain `eat` with no target and only seeds carried still eats 6 seeds beside a bush (15 times
  today). Other open items, all small:
  - one berry per bush eat;
  - herbs win over a nearby bush when nothing is carried;
  - an invention with a station input can't be combined;
  - three weak test assertions.

  Details in .superpowers/sdd/hotfix-review-nov3.md.
