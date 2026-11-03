# Watch log: what I'd tweak, add, moderate or administer

Claude's running notes from watching the live world. The user asked for them on Nov 3: "tail everything and get a log
of items you want to tweak, add, help mod and admin". This file holds observations and proposals. What I actually did
to the world goes in [steward-log.md](steward-log.md). Tags:
- **tweak:** change existing behaviour.
- **add:** something new.
- **mod:** creature behaviour worth stepping in on.
- **admin:** infrastructure.

## 2026-11-03 (fresh world at 10:42; public at https://swarm-world.4rc4de.com)

- **admin (done 10:48):** the student slowed from 2.8 s to 30 s per decision while it shared this Mac's GPU with
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
- **tweak (wishes):** by tick ~800 there are 36 "wishes", and every one was pulled from a reflection; no creature has
  made an explicit wish. Many are fragments: "steady supply", "tool", "world had more of the right kind",
  "group to keep trading fibers opal should". Taking wishes from reflections is noisy. Options:
  - take only explicit wish phrasing;
  - group the fragments by the item they name;
  - show the reflected ones apart from real wishes, in the panel and on the public page.
- **mod (balance, watching):** fiber and rope are the early bottleneck: about 20 of the 36 are about fiber, rope, grass
  or sticks; others ask for stone or a place to trade. Nothing granted. It's early, and finding tall grass is part of the
  game. If fiber is still the theme by day 2, consider faster grass regrowth or a bigger fiber yield.
