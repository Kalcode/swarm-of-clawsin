# Concurrency benchmark: creature thinks on one laptop

Machine: Apple M1 Max (32-core GPU, 32 GB). Server: oMLX 0.7.3 at `http://127.0.0.1:8000/v1`, `--max-concurrent-requests 16`, paged SSD prefix cache on. Run on 2026-11-01.

Workload: each request is one creature think, built like this:
- A shared system prompt of about 2,015 tokens (world rules). oMLX also injects about 390 tokens of JSON-schema instructions (see the notes below), so the shared prefix is about 2,406 tokens.
- A unique first-person observation of about 175 tokens.
- A request for the 7-field intention JSON, with `max_tokens` 120, `temperature` 0.8, strict `json_schema` and `enable_thinking: false`.

Each level N runs N workers in a closed loop with 2 requests each. "Thinks/s" means completed requests divided by wall time. About 93% of prompt tokens were prefix-cache hits on every level.

Script: `uv run python bench/bench_concurrency.py --model M --levels 1,4,8,16 --rounds 2`. Raw data is in `bench/results/*-20261101-17*.json`.

## Results

**Qwen3.5-4B-MLX-4bit** (mean output about 66 tokens)

| N | reqs | wall s | thinks/s | mean s | p50 s | p95 s | TTFT s | out tok/s | prompt tok/s | schema-valid |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 2 | 2.5 | 0.80 | 1.24 | 1.24 | 1.31 | 0.47 | 57 | 2078 | 2/2 |
| 4 | 8 | 7.8 | 1.02 | 3.52 | 3.56 | 4.82 | 1.05 | 65 | 2639 | 7/8 |
| 8 | 16 | 13.4 | 1.20 | 5.91 | 5.15 | 9.87 | 1.72 | 77 | 3091 | 14/16 |
| 16 | 32 | 25.5 | **1.25** | 11.69 | 11.73 | 18.83 | 3.62 | 85 | 3238 | 28/32 |

A partial second pass with 4 rounds per level gave 0.88, 1.02 and 1.25 thinks/s at N=1, 4 and 8, which matches. It was stopped before N=16 when the GPU was needed for live runs, so it wrote no JSON.

**Qwen3.5-9B-MLX-4bit** (mean output about 88 tokens)

| N | reqs | wall s | thinks/s | mean s | p50 s | p95 s | TTFT s | out tok/s | prompt tok/s | schema-valid |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 2 | 4.5 | 0.45 | 2.24 | 2.24 | 2.30 | 0.66 | 41 | 1149 | 2/2 |
| 4 | 8 | 14.7 | 0.55 | 7.16 | 7.22 | 9.09 | 1.52 | 52 | 1406 | 8/8 |
| 8 | 16 | 20.9 | 0.76 | 9.73 | 8.96 | 15.15 | 2.73 | 65 | 1972 | 16/16 |
| 16 | 32 | 41.2 | **0.78** | 19.23 | 18.41 | 30.99 | 5.48 | 66 | 2004 | 30/32 (2 truncated at 120 tokens) |

**gemma-4-e4b-it-4bit** (mean output about 82 tokens)

| N | reqs | wall s | thinks/s | mean s | p50 s | p95 s | TTFT s | out tok/s | prompt tok/s | schema-valid |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 2 | 3.2 | 0.62 | 1.60 | 1.60 | 1.63 | 0.36 | 51 | 1607 | 2/2 |
| 4 | 8 | 8.2 | 0.97 | 4.02 | 4.00 | 4.95 | 0.76 | 79 | 2498 | 8/8 |
| 8 | 16 | 12.7 | 1.26 | 5.93 | 5.67 | 7.73 | 1.40 | 102 | 3253 | 16/16 |
| 16 | 32 | 23.4 | **1.37** | 11.00 | 10.47 | 15.16 | 2.54 | 116 | 3518 | 32/32 |

No request failed at the HTTP level. Throughput is about flat from N=8 to N=16: the server is saturated by N=8 or N=12, and higher concurrency only adds latency.

## Conclusions

The laptop sustains about **1.25 to 1.4 thinks/s** with the 4B-class models and about **0.8 thinks/s** with the 9B model. Concurrency helps much less than expected: going from 1 to 16 in flight gives only about 1.6x for Qwen 4B, 1.7x for the 9B and 2.2x for Gemma.

**Why it doesn't scale further.** I ran a separate decode-only test (50-token prompts, 200-token outputs, no prefix). It reached about 230 to 260 tok/s in aggregate for 4B and Gemma at N=16, and about 160 tok/s for the 9B. However, time to first token grows roughly linearly with N even for 50-token prompts: at N=16 the slowest request waited about 4.2 s on 4B, 2.7 s on Gemma and 7.2 s on 9B. Each new request costs about 0.2 to 0.45 s of mostly serialized server time for admission, prefix restore, prefill and cache store. With short replies of about 70 to 90 tokens, that per-request overhead dominates.

**Creatures supported.** A creature that thinks every T seconds adds 1/T thinks/s of load. The table shows the maximum (peak thinks/s × T, rounded down) and, in parentheses, a comfortable figure at 80% utilization that keeps queues bounded.

| Model | Peak thinks/s | Every 10 s | Every 20 s | Every 30 s |
|---|---|---|---|---|
| Qwen3.5-4B | 1.25 | 12 (10) | 25 (20) | 37 (30) |
| Qwen3.5-9B | 0.78 | 7 (6) | 15 (12) | 23 (18) |
| Gemma 4 E4B | 1.37 | 13 (10) | 27 (21) | 41 (32) |

Expect p95 latency of about 8 to 10 s for the 4B models (about 15 s for the 9B) near these loads, so a creature's think can lag its interval. Real prompts will carry memory and recent events, which means longer and more varied tails, more prefill and lower throughput. Treat these numbers as an upper bound.

**Recommendations**
- **About 25 creatures: Gemma 4 E4B**, with each creature thinking every 25 to 30 s (comfortable for 27 to 32 creatures; at 20 s it would run at about 90% utilization). Gemma had the highest throughput and was 100% schema-valid without enforcement (58/58 under load, 8/8 in the probe). Qwen3.5-4B has about the same throughput but produced invalid JSON in 7 of 58 load-test requests while grammar is off; it is the fallback. Qwen3.5-9B can only reach 25 creatures with a 40 s interval or longer.
- **About 50 creatures: no single model on this laptop handles it at 30 s intervals or shorter.** With Gemma it needs about a 45 s average interval; with 4B, about 50 s. Ways to get there:
  1. Make thinking event-driven, so creatures only think when an activity finishes. Walking and gathering already span several ticks.
  2. Shorten outputs: a shorter thought and compact JSON. Gemma and the 9B often pretty-print.
  3. Add a second machine running its own brain node.
  4. Install grammar support, then re-test oMLX scheduler settings. Untested candidates are `decode_fairness`, `chunked_prefill` and burst decode.
- Use **8 to 12 slots** per node. Slots beyond that only add latency.

## Notes for the brain client

**(a) `response_format` json_schema is accepted, but this install does not enforce it.** oMLX 0.7.3 was installed without the `grammar` extra (no xgrammar). It returns HTTP 200 and falls back to prompt injection: it adds about 390 tokens of schema instructions to the system message, which are cached. Every such response carries this header:
`Warning: 199 omlx "response_format strict json_schema not enforced; grammar-constrained decoding unavailable, output is best-effort and NOT schema-enforced"`.
In the probe, a prompt saying "ignore JSON, write a poem" got a plain-text poem from all three models.

Valid-output rates:
- Qwen3.5-4B: 7/8 in the probe (one missing `items`) and 51/58 under load.
- Qwen3.5-9B: 8/8 and 56/58; both failures were truncated at `max_tokens` 120.
- Gemma: 8/8 and 58/58.

What to do:
- Keep lenient parsing and validation in the client.
- Log the `Warning` header.
- Use `max_tokens` of about 160 for the 9B.
- To get real enforcement, reinstall with the extra, for example `uv tool install --force 'omlx[grammar]==0.7.3'` (this pins xgrammar 0.2.8), restart the server and re-run `--probe-only`. The header should disappear.

**(b) Qwen3.5 thinks by default.** The reasoning goes into a separate `message.reasoning_content` field, never into `content` (no `<think>` tags). By default, even 400 tokens of reasoning didn't finish, so the reply ended with `finish_reason: length` and had no `content`. Sending **`chat_template_kwargs: {"enable_thinking": false}` turns it off**: `reasoning_tokens` is 0, there is no `reasoning_content`, the JSON is in `content` and `finish_reason` is `stop`. Always send it. One more reason: if grammar is installed later and thinking is left on, oMLX auto-sets `thinking_budget = max_tokens // 2`.

**(c) Gemma 4 E4B works with the same request shape.** It never produced reasoning, with or without the kwarg; sending the kwarg is harmless. It tends to pretty-print the JSON, which still parses. Its per-model default temperature in oMLX is 1.0, and the request's 0.8 overrides it.

**(d) `usage` fields.**
- Standard: `prompt_tokens`, `completion_tokens`, `total_tokens`, plus aliases `input_tokens` and `output_tokens`.
- **Cache hits are reported in `prompt_tokens_details.cached_tokens`.** After warm-up this was 2,406 of about 2,580 prompt tokens (93%) on every request, block-granular, restored from the paged cache in about 4 ms.
- `completion_tokens_details.reasoning_tokens`.
- oMLX timing extensions, in seconds or tok/s: `time_to_first_token`, `prompt_eval_duration`, `generation_duration`, `total_time`, `prompt_tokens_per_second`, `generation_tokens_per_second`, and `model_load_duration` on a cold load.

**Other observations**
- The memory guard (balanced tier) gives oMLX a budget of about 13 GB on this machine. When one model needs prefill headroom, oMLX evicts the others while they are idle; the log shows "Evicting idle model 'gemma-4-e4b-it-4bit' …". A mixed-model swarm on one server will therefore churn model loads. A cold 9B load plus warm-up took about 16 s.
- Model IDs match the directory names under `~/models`.
