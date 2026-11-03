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
