# Distilling a fast creature mind

Issue [020](../issues/020-distill-a-fast-mind.md) · design: [the spec](superpowers/specs/2026-11-02-distill-a-fast-mind-design.md)

A night of teacher episodes, an export, a LoRA training run on this Mac, then a live trial against the teacher.
Teachers are gpt-oss and Qwen only (Apache 2.0); Gemini outputs are never used (the export drops them, the teacher
script refuses them). The student is Qwen3-1.7B (Apache 2.0).

## 1. A night of teacher data

The practice worlds run on this Mac's CPU, headless and turn-based (the clock waits for every answer, so model speed
doesn't matter); only the thinking goes to the model server. Every creature has every harness layer (plan, disclose,
recall), every installed pack is in, recall is keywords only (Voyage is never called). Each request is exactly what a
live creature's would be (`LLMBrain`: strict JSON schema, thinking off, `reasoning_effort` low plus headroom for gpt-oss).

First a short pace check (one seed, 120 ticks), then the night. `caffeinate -i` keeps the Mac awake:

```sh
uv run python scripts/teacher_runs.py --base-url http://192.168.50.42:11434/v1 --model gpt-oss:20b --seeds 1 --ticks 120 --out /tmp/pace
nohup caffeinate -i uv run python scripts/teacher_runs.py --base-url http://192.168.50.42:11434/v1 \
  --model gpt-oss:20b --seeds 100-139 > runs/teacher-pc.log 2>&1 &
```

To use this Mac's oMLX at the same time, start a second run with its own seed range into the same folder:

```sh
nohup caffeinate -i uv run python scripts/teacher_runs.py --base-url http://127.0.0.1:8000/v1 \
  --model Qwen3.5-9B-MLX-4bit --seeds 200-239 > runs/teacher-mac.log 2>&1 &
```

- Defaults: 6 creatures, 2400 ticks (two days), `--out runs/teacher`, `--concurrency` = creatures (thinks in flight per
  turn; the PC's Ollama serves 8 at once), `--timeout 180` s per request.
- Each episode is `runs/teacher/<time>-<model>-s<seed>/` with `meta.json`, `thinks.jsonl`, `events.jsonl` and a `done`
  marker written last. A mock episode of 6 creatures and 2400 ticks makes about 2,100 thinks and 14 MB.
- One line per finished episode: `seed 100: 64.2 min, 2104 thinks, ok 81%, milestones rope@40, stone_axe@310, ...`.
- Stopping is safe (Ctrl-C, `kill`, a dropped connection, a reboot): start the same command again. Finished seeds are
  skipped; an unfinished one is moved aside as `<folder>.partial` and redone. A failed think (timeout, dropped
  connection, HTTP 408, 429 or 5xx) is retried after 5 s, 15 s, 60 s, then every 60 s; after 10 minutes of failures
  that creature idles the turn and the log says so. Any other HTTP 4xx isn't retried (waiting won't fix the request).
- At the start the teacher must be in the server's model list (`GET /models`): a mistyped name stops the run at once.
- Two runs may share `--out` as long as their models differ. A second copy of the same model into the same `--out`
  refuses to start (it holds `<out>/.teacher-<model>.lock`), since it would move the first one's episode aside.

## 2. Export

```sh
uv run python scripts/export_training.py runs/teacher --out data/student/night1
```

A folder of episodes stands for all its finished ones; a path that doesn't exist or holds no episodes is warned
about. The summary shows examples by source model and by run, the action mix, why decisions weigh what they do,
average prompt and answer length, the longest example, and skipped lines by reason. `data/` is git-ignored. Weights,
the split (by world seed, so two teachers' episodes of one seed land on the same side) and the rules are in the
script's docstring.

Only teacher episodes are exported. Live runs never are, and there is no switch for it: a live prompt quotes what other
creatures said (Gemini's creatures too) and the sky's words verbatim in its memories, and the save carries memories
across restarts, so even a live run without Gemini in it can hold Gemini's text. The server's `--log-prompts` flag
(off by default; about 6 KB a line) stays for later provenance work. Live `thinks.jsonl` lines carry the tick,
creature, model tag, kind, the parsed intention (`output`), the result (ok, no-op, message), timing, tokens and
harness layers, but no prompt.

## 3. Train

```sh
scripts/train_student.sh data/student/night1
```

mlx-lm LoRA on `mlx-community/Qwen3-1.7B-bf16` (masked prompts, 4096-token sequences, batch 1 with 8-step
accumulation, 16 layers, rank 16), fused, quantized to 8 bits into `~/models/swarm-student-<date>`. Every setting is
an environment variable listed at the top of the script. Expect about 8-10 GB of memory and roughly 1,000 examples an
hour (estimates scaled from the 0.6B smoke test): pause or slow the live world's minds for it. By default it makes one
pass over every weighted line, which a night's export can stretch to 10 hours; before training it prints its estimate
(`SECS_PER_EXAMPLE`, assumed 3.5 s). A sensible cap for one training session is about 4 hours:

```sh
ITERS=4000 scripts/train_student.sh data/student/night1
```

If the fused student's own template fails the check, the script says the student is not ready and exits non-zero.

Before training it checks, with the model's own tokenizer, that each example is exactly the serving prompt (the chat
template with `enable_thinking=False`, as the live brain asks) followed by the answer, and fits the sequence length.
For Qwen3 both render the assistant turn as `<think>\n\n</think>\n\n{...}`, so they match. After the fuse it checks
the student's own template again and lets it answer one held-out prompt.

## 4. Live trial

The student was trained on prompts with every harness layer, so give the trial's creatures all of them
(`HARNESS_ALL=plan,disclose,recall`). Transplant half of one model's creatures onto the student, e.g. 12 sleeping
gpt-oss creatures, 6 staying with the teacher on the PC and 6 moving to the student on this Mac's oMLX:

```sh
HARNESS_ALL=plan,disclose,recall MODEL_SERVER=http://192.168.50.42:11434/v1 MODEL=gpt-oss:20b CREATURES=6 \
  MODEL2="swarm-student-20261103:6@http://127.0.0.1:8000/v1" ADOPT="gpt-oss:20b=swarm-student-20261103" ./start-world.sh
```

The first model takes back its own 6; the student adopts the next 6 sleeping gpt-oss creatures (they keep their
memories). After a day or two of world time compare the halves, plus thoughts per minute from `/api/metrics`:

```sh
uv run python scripts/review_world.py runs/<the trial's run> --split
```

Log the trial and its outcome in [docs/steward-log.md](steward-log.md).
