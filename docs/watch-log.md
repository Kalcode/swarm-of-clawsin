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

### 18:20 watch (tick 27,543)
- **admin:** healthy: 12 student creatures awake (the PC's 12 asleep until 20:30), tunnel up, no errors.
- **Minds since tick 25,720:** the student made 820 acts, 85% successful, p50 14.1 s; no failure streaks.
  - 3,990 student prompts have been logged for round 2 since 16:13.
- **tweak (proposed), a bedtime meal:** the sixth creature today (Vex, Jun, Holt, Mika, Ula, Sorrel) lay down to sleep
  near starving, 1-4 steps from bushes with fruit.
  - The wake-at-5 alarm and the reflexes rescue them (Ula went from 3 to 62 just now), but each comes within a few
    points of collapsing.
  - Proposal: when a creature lies down to sleep hungry (satiety < 35) with food within a few steps, the body eats
    first, in the same spirit as `_go_eat`. That affects only hungry sleepers, so GC2 holds for everyone else.
  - Do it after the frontier merge, in one small batch with the seed food value.

### 18:50 watch (tick 29,320)
- **admin:** healthy: 12 student creatures awake, tunnel up, no errors. The student made 1,070 acts, 82% successful,
  p50 13.4 s.
- **mod (round-2 data), Holt's loop (11 failures in a row):** two give targets that can't work.
  - It keeps giving strong cord to Hux, a gpt-oss creature asleep in stasis while the PC is off ("You don't see 'Hux'
    here").
  - It keeps giving strong cord to the campfire ("The strong cord won't burn").

  Both are the student's habit. The teacher's answers in these moments belong in round 2.
  - **tweak (idea):** "give to someone asleep in stasis" could say "Hux sleeps far away; their mind is gone for now".

### 20:43 watch (tick 36,095): frontier on, round 2 running
- **admin:** healthy: 12 gpt-oss creatures awake on the PC; the student's 12 sleep; tunnel up; no errors.
  - The frontier is on, with no strips yet (width 128).
- **admin, PC slow:** gpt-oss on the PC answers in 53 s (p50; p90 82 s), against 9 s this afternoon, with 91%
  success. It's fully in VRAM (12.9 GB). The pattern fits Ollama answering one request at a time after the PC
  restarted (12 × ~4.5 s).
  - I asked the PC's own Claude session to check `OLLAMA_NUM_PARALLEL`, and to restart Ollama if it isn't 8.
- **admin, round 2:** the DAgger labels on this Mac's oMLX run at ~16 a minute, so all 5,463 would take ~5.6 h.
  - I capped the night at 3,000, failures first (all 951 failures plus ~2,000 others), resuming from the 253 already
    done.
  - A chain script then exports, unloads gpt-oss and trains `swarm-student-20261104`. It logs to
    runs/round2-chain.log and runs/train-student-night2.log.

### 21:13 watch (tick 37,895)
- **admin, the PC: fixed.** Since the pc node went to 4 slots (20:46), gpt-oss has made 552 acts:
  - 93% succeeded;
  - p50 6.8 s, p90 13.6 s, down from 53 s and 82 s;
  - 0 think errors and no timeouts.

  Fewer requests in flight beat 8 slots on tonight's GPU (the user is checking its clocks).
  - **Lesson:** `--slots` on the node is the throttle. Match it to what the GPU sustains, not to OLLAMA_NUM_PARALLEL.
- **Frontier:** on, no strips yet. No collapses. Round 2: 721 of 3,000 labels.

### 22:14 watch (tick 41,521)
- **admin:** healthy: gpt-oss made 638 acts, 86% successful, p50 7.4 s; no collapses. Round 2: 1,661 of 3,000 labels.
- **mod (frontier, expected):** no strips yet, and none expected tonight.
  - All four explorer-drive creatures (Holt, Jun, Cass, Gil) belong to the student and sleep until the morning.
  - The PC's 12 stay between x 51 and 75, 50+ steps from either edge, and none explored in this stretch.

  The first growth will likely come when the new student wakes the explorers, around the time of the user's Show HN
  post. Not forced: discovery is the point.
- **tweak (idea):** if growth stays rare, a land's pull could also reach curious creatures, or idle creatures could
  occasionally wander, as the spec's "Wanderers" paragraph first suggested (Decided 2 narrowed it to explorers).
  Decide after a day of data.
- **minor:** Hux repeats combine [stick, rope, rope] ("one more ingredient seems to be missing"): gpt-oss hunting for
  an invention, harmless.

### 23:43 watch (tick 46,874): the shortfall hint works; give-to-basket fixed
- **admin:** healthy since the 23:19 restart: gpt-oss made 438 acts, 76% successful, p50 7.6 s, p90 15.0 s. No collapses.
  The tunnel answers 200, and the frontier has 0 strips.
- **win:** the crafting-shortfall hint (49128af) worked on its first try. Teo had looped "combine plant fiber rope +
  2 flint", the invented *plant fiber rope*, not *rope*. Then Teo was told "You know how to make rope: 3 plant fiber ->
  rope", made 1 rope, then 1 rope enhancer, then a stone knife.
- **fix (deployed 23:49, 679e0ef):** 18 of the 49 failed gives came from Mirth trying "give basket [rope]" beside a
  basket (plan: "Store rope"). `give` to a basket or chest now stores in it. Reviewed.
- **idea (parked):** when a combine's items are one swap away from a known recipe (plant fiber rope for rope), the
  refusal could name the near miss. Hux (24 failed combines) and Tula (9) loop the same way.
- **round 2:** labeling finished with 2,997 labels, all in the training set.
  - The export wrote 27,037 training and 3,167 validation lines. Validation is teacher episodes only.
  - gpt-oss was unloaded, and training started at 23:47.
  - At about 3.9 h it finishes near 03:40, then fuses and quantizes into `~/models/swarm-student-20261104`.

### 00:13 watch (tick 48,665): three loops, three fixes
- **admin:** healthy since the 23:49 restart. gpt-oss made 474 acts, 73% successful, p50 7.5 s, p90 15.5 s. No
  collapses; the frontier has 0 strips.
- **win:** give-to-basket works. Mirth: "You put 3 rope into the basket."
- **fix (deployed 00:34, c1e81b3 + 7e3e8f7, reviewed):** the streaks were Hux 42, Cyd 36 and Gus 26.
  - Cyd asked for "spark fragment". The catalog only stripped plurals, so "spark fragment" never found the item
    named "spark fragments".
  - Cyd also asked for "spark fragmentses". Perception had been showing "2 spark fragmentses".
  - Hux was told "you could invent it", but the core prompt leaves `invent` to the tips. Invent's tip scores 3.5,
    so feeding, fire, play and dance crowd it out of the four slots. The refusal now spells out the command.
- **mind (no fix):** Gus is told "rope is 3 plant fiber; you have only 1" and retries the fishing rod anyway: a
  gpt-oss plan that won't update. Watch whether the round-2 student does better.
- **parked:**
  - A runtime invention with a plural name now shadows its singular. For example, an invention called "tents" would
    take "build tent". Unlikely, so left alone.
  - One unidentified test failed once among the first 157 tests while training loaded the Mac. Five full reruns
    passed.
- **round 2:** at step 1,000 of 4,000 the validation loss is 0.471. The steps went 3.049 → 0.648 (200) → 0.556 →
  0.492 → 0.442 (800) → 0.471 (1,000). On track for about 03:40.

### 00:43 watch (tick 50,458): the name fixes work; Hux still combines
- **admin:** healthy since the 00:34 restart. gpt-oss made 85 acts, 80% successful, p50 6.1 s, p90 11.8 s.
- **win:** Cyd's loop is gone. Gale gave Cyd 2 spark fragments, and Cyd gave 1 to Hux, "for the net".
- **fix (deployed 00:51, 4c5642a + 789bcc7, reviewed):** Hux got the spelled-out invent hint and thought "Time to
  invent the net", yet still sent `combine`. Since 16:00, gpt-oss invented once in 432 decisions with the invent
  tip shown, and never in 4,034 without it. Fix: after the hint, combining toward the same new thing again invents it.
  - The once-a-day limit and invent's item rules still apply.
  - Every item named must be held.
  - The core prompt's combine line ("to invent something new") is unchanged tonight: the round-2 student trains on it.
  - Worth revisiting for both minds later, possibly by naming invent in that line.
- **round 2:** step 1,400 of 4,000, validation loss 0.415.
