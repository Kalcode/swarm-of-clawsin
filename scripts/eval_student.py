"""Does a student pick the teacher's action (and target) on held-out decisions?

    uvx --from mlx-lm==0.32.2 python scripts/eval_student.py VALID.jsonl ADAPTER_DIR_OR_NONE N PAIRS_OUT.json

VALID.jsonl is an export's valid.jsonl (whole teacher episodes the student never trained on). The same N decisions are
drawn every time (a fixed shuffle), so rounds compare like for like; use an episode no compared round trained on
(data/student/night1/valid.jsonl is s101, held out from rounds 1-3). Greedy decoding on the base model plus the
adapter, with the serving template (no thinking). Prints one JSON line; writes [teacher action, student action,
teacher target, student target] pairs to PAIRS_OUT.json. Results: docs/distillation.md, section 6."""

import json
import random
import sys
import time

from mlx_lm import generate, load

BASE = "mlx-community/Qwen3-1.7B-bf16"

valid, adapter, n, pairs_out = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
rows = [json.loads(line) for line in open(valid)]
random.Random(7).shuffle(rows)
rows = rows[:n]
model, tok = load(BASE, adapter_path=None if adapter == "none" else adapter)

parsed = act = act_target = 0
secs = []
pairs = []
for r in rows:
    msgs, want = r["messages"][:-1], json.loads(r["messages"][-1]["content"])
    prompt = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True, enable_thinking=False)
    t = time.time()
    out = generate(model, tok, prompt, max_tokens=220, verbose=False)
    secs.append(time.time() - t)
    try:
        got = json.loads(out[out.index("{"): out.rindex("}") + 1])
    except ValueError:
        continue
    parsed += 1
    pairs.append([want.get("action"), got.get("action"), want.get("target"), got.get("target")])
    if got.get("action") == want.get("action"):
        act += 1
        if str(got.get("target", "")).strip().lower() == str(want.get("target", "")).strip().lower():
            act_target += 1

secs.sort()
print(json.dumps({"adapter": adapter, "n": n, "parsed": parsed, "action_match": act, "action_target_match": act_target,
                  "secs_p50": round(secs[len(secs) // 2], 2), "secs_p90": round(secs[int(len(secs) * 0.9)], 2)}))
json.dump(pairs, open(pairs_out, "w"))
