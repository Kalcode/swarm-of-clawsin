# Local LLM inference on Apple Silicon for a many-agent swarm (M1 Max, 32 GB): oMLX vs the alternatives

Research date: 2026-11-01. Target machine: MacBook M1 Max, 32 GB unified memory, 10 CPU cores (GPU core count, 24 or 32, not stated by the user; it matters, see below), Ollama already installed.
Convention: "Cited Findings" are verified against the linked page in this session. "Inferences" are my reasoning or estimates. Anything dated before mid-2026 is flagged.

---

## 1. What exactly is "oMLX"?

### Takeaway
"oMLX" almost certainly means **jundot/omlx**. It is an Apache-2.0, Python and MLX-based, OpenAI- and Anthropic-compatible LLM server for Apple Silicon, run from a native macOS menu-bar app. Its main features are continuous batching (via mlx-lm's BatchGenerator), a vLLM-style paged KV cache with prefix sharing, and a second cache tier on SSD. It is very active (23k+ stars, latest stable 0.7.3 released 31 Oct 2026) and supports M1. Other GitHub repos named "omlx" are forks of it.

### Cited Findings
- **Identity and description.** jundot/omlx describes itself as an "LLM inference server with continuous batching & SSD caching for Apple Silicon — managed from the macOS menu bar". Tagline: "LLM inference, optimized for your Mac". — [GitHub jundot/omlx](https://github.com/jundot/omlx)
- **Author.** GitHub user "jundot" (README contact: junkim.dot@gmail.com and omlx.ai/me). License: Apache-2.0. On 2026-11-01 the repo showed about 23.3k stars, 2.1k forks, about 3,577 commits, 379 issues and 201 PRs. — [GitHub jundot/omlx](https://github.com/jundot/omlx)
  - A third-party wiki reported 17,042 stars, an older snapshot. — [dennislwm/playradar wiki](https://github.com/dennislwm/playradar/wiki/OmlX)
- **Lineage.** The author's post in the MLX repo discussions says oMLX started from vllm-mlx v0.1.0, then added multi-model serving and a tiered KV cache aimed at coding agents. The post is from about March 2026. — [ml-explore/mlx Discussion #3203](https://github.com/ml-explore/mlx/discussions/3203)
- **Same-name repos are forks.** WhaleChao/omlx and apetersson/omlx carry the same description as jundot/omlx. — [WhaleChao/omlx](https://github.com/WhaleChao/omlx), [apetersson/omlx](https://github.com/apetersson/omlx)
- **Unrelated "omlx" name.** A PyPI package called `flyteplugins-omlx` exists, a Flyte plugin. I did not verify how it relates to jundot/omlx. — [PyPI flyteplugins-omlx](https://pypi.org/project/flyteplugins-omlx/)
- **Batching and concurrency.**
  - Continuous batching runs through mlx-lm's BatchGenerator.
  - "Max concurrent requests" can be set from the CLI or the admin panel. The default is 8 and the README example uses 16.
  - — [GitHub jundot/omlx](https://github.com/jundot/omlx)
- **KV cache.**
  - Block-based, "inspired by vLLM", with prefix sharing and copy-on-write.
  - The hot tier is in RAM. The cold tier is on SSD in safetensors format and survives server restarts.
  - Optional Affine4/Affine8 KV compression.
  - — [GitHub jundot/omlx](https://github.com/jundot/omlx)
- **Multi-model serving.** LRU eviction, manual load/unload, model pinning, a per-model idle TTL, and a cap on total process memory (default: system RAM minus 8 GB). Per-model profiles are exposed as `<model>:<profile>`. — [GitHub jundot/omlx](https://github.com/jundot/omlx)
- **API endpoints.** `/v1/chat/completions`, `/v1/completions` (both streaming), `/v1/messages` (Anthropic), `/v1/embeddings`, `/v1/rerank`, `/v1/models`, `/tokenize`, `/detokenize`. — [GitHub jundot/omlx](https://github.com/jundot/omlx)
- **Tool calling and structured output.**
  - mlx-lm function-calling formats, auto-detected for Llama, Qwen, DeepSeek, Gemma, GLM, MiniMax, Mistral and Kimi K2.
  - JSON-schema validation, plus bare JSON, EBNF and regex grammars.
  - MCP tool integration.
  - — [GitHub jundot/omlx](https://github.com/jundot/omlx)
- **Model types.** LLMs (any mlx-lm model), VLMs (Qwen3.5 series, GLM-4V, Pixtral and others), OCR models, embedding models and rerankers. GGUF runs through an external engine. — [GitHub jundot/omlx](https://github.com/jundot/omlx)
- **App and tools.** The menu-bar app is native Swift/SwiftUI, not Electron, and auto-restarts the server after a crash. The `/admin` dashboard includes a chat UI, a Hugging Face model downloader and a benchmark tool. — [GitHub jundot/omlx](https://github.com/jundot/omlx)
- **Requirements.**
  - macOS 15.0+ (Sequoia), Python 3.11–3.13, Apple Silicon M1 through M5.
  - The optional native custom kernels need full Xcode with the Metal toolchain.
  - The project site gives 16 GB RAM as the minimum and recommends 64 GB+.
  - — [GitHub jundot/omlx](https://github.com/jundot/omlx), [omlx.ai](https://omlx.ai)
- **Install steps.**
  - DMG: download from Releases and drag to Applications. The app is signed and notarized and auto-updates.
  - Homebrew: `brew tap jundot/omlx && brew install jundot/omlx/omlx`. Add `--with-custom-kernel` if full Xcode is installed.
  - From source: `git clone https://github.com/jundot/omlx && make install`, or `make install-no-kernels`.
  - Run: `omlx serve --model-dir ~/models`, which serves at http://localhost:8000/v1. It also reads the existing Hugging Face cache and LM Studio model folders.
  - — [GitHub jundot/omlx](https://github.com/jundot/omlx), [omlx.ai](https://omlx.ai)
- **Recent releases (2026).**
  - 0.7.3 stable, 31 Oct; 0.7.3rc1, 27 Oct; 0.7.3.dev2, 25 Oct; 0.7.3.dev1, 24 Oct; 0.7.2, 21 Oct. The year is inferred: 0.4.4rc2 shipped on 15 June 2026.
  - 0.7.3 changes:
    - The batch KV cache is updated in place, which lowers memory use with many long conversations.
    - Batched decode reads each weight once for all batch rows.
    - Hybrid Qwen models reuse a shared system prompt across conversations.
    - Fixes a prefill memory guard that could reject every prompt after overlapping requests until restart.
    - Uses the verify MMA kernel for 6-bit and 8-bit layers on M1/M2.
  - 0.7.3rc1 changes:
    - New "Float16 Activations" option for M1/M2. Qwen3.6-35B-A3B oQ4e decode went from 75.9 to 82.4 tok/s (+9%) on an M1 Max.
    - The memory guard re-reads `iogpu.wired_limit_mb` while the server runs.
    - Relaxed timeout before M5, aimed at Metal `0000000e` errors during long prefills.
  - 0.7.3.dev1 adds an `X-oMLX-Cache-Store: off` header that keeps one-shot requests out of the prefix cache.
  - — [jundot/omlx releases](https://github.com/jundot/omlx/releases)
- **Release cadence.** oMLX 0.4.4rc2 was released 15 June 2026, so the project went from 0.4.x to 0.7.3 in about 4.5 months. — [Popular AI, Aug 17 2026](https://www.popularai.org/p/ollama-num-parallel-mac-mlx), [jundot/omlx releases](https://github.com/jundot/omlx/releases)

### Inferences
- jundot/omlx is the intended project. The name, Mac focus, menu-bar app and the concurrency and caching features all match what the user described.
- **Maturity.** Development is fast and the project is popular, but it is pre-1.0 and changes almost daily. The release notes fix memory-guard, cache-accounting and tool-call parsing bugs every week. Expect some churn, and pin a version once things work.
- **The paged SSD prefix cache is the standout for the swarm.** Every agent prompt shares a long prefix (world rules), and each agent's own prefix (persona and memory) recurs from tick to tick. oMLX can keep those KV blocks in RAM or on SSD instead of recomputing them. This matters a lot on an M1 Max, where prompt processing (prefill) is slow (see section 3).

### Gaps
- No published oMLX benchmark covers a 32 GB M1 Max or more than 8 concurrent requests.
- The GitHub Releases section did not render on the main repo page, so release dates come from the releases page, which shows day and month only.
- I did not verify whether similarly named projects such as "mlx-omni-server" exist or could be what the user meant.

---

## 2. How oMLX compares to Ollama, LM Studio, mlx_lm.server, vllm-mlx and llama.cpp

### Takeaway
On this Mac, oMLX and vllm-mlx are the MLX-native servers with real continuous batching plus prefix caching. llama.cpp's `llama-server` is the most battle-tested cross-platform option, also with continuous batching and a prompt cache. **Ollama's new MLX engine still serializes concurrent requests** as of late Oct 2026, and its MLX preview required more than 32 GB RAM. LM Studio has had MLX continuous batching since 0.4.2 (Feb 2026). Plain `mlx_lm.server` accepts concurrent requests but scaled poorly in the one M1 Max test found.

### Cited Findings

**Ollama**
- Ollama's FAQ defines `OLLAMA_NUM_PARALLEL` as the "maximum number of parallel requests a loaded model can process". The default is 1. Raising it increases memory use because context allocation grows with the number of parallel slots. — [Popular AI, Aug 17 2026](https://www.popularai.org/p/ollama-num-parallel-mac-mlx)
- **MLX engine launch.** Previewed 30 March 2026 in Ollama 0.19, initially for Qwen3.5-35B-A3B only. The post says: "Please make sure you have a Mac with more than 32GB of unified memory."
  - Claimed on its test hardware: prefill 1810 tok/s and decode 112 tok/s (NVFP4), versus 1154 and 58 tok/s for Q4_K_M on 0.18.
  - The engine reuses its cache across conversations and keeps shared prefixes longer.
  - The post does not mention parallel requests.
  - — [Ollama blog, MLX](https://ollama.com/blog/mlx)
- **The MLX runner ignores OLLAMA_NUM_PARALLEL.** Issue #17280 (21 July 2026) reports that requests still serialize with `OLLAMA_NUM_PARALLEL=8`, while a GGUF model on the same server did run in parallel. — [Popular AI](https://www.popularai.org/p/ollama-num-parallel-mac-mlx), [ollama issue #17280](https://github.com/ollama/ollama/issues/17280)
- **The fix is not merged.** PR #17317 adds continuous batching to the MLX runner (passes `--parallel`, adds MultiSeq caches and a continuous-batch decode loop). It was still open on 2026-11-01, with one approval on 28 Oct 2026 and no benchmark results posted. — [ollama PR #17317](https://github.com/ollama/ollama/pull/17317)
- **Qwen3.5 hybrid models also forced serial on the GGUF path.** Qwen3.5 and qwen35moe logged "model architecture does not currently support parallel requests" and were forced to `Parallel:1`. PR #17144 removes them from the blocklist; as of Aug 2026 it was open and tested only on CUDA. — [Popular AI](https://www.popularai.org/p/ollama-num-parallel-mac-mlx), [issue #14638](https://github.com/ollama/ollama/issues/14638), [PR #17144](https://github.com/ollama/ollama/pull/17144)
- **Measured on an M1 Max (64 GB), 28 Oct 2026.**
  - Setup: Ollama 0.40.11 with `OLLAMA_NUM_PARALLEL=8`, Qwen3.5-9B MLX NVFP4.
  - Aggregate throughput stayed flat at 53.2 / 54.5 / 54.8 tok/s for 2 / 4 / 8 concurrent requests.
  - Median time to first token (TTFT) rose from 4.85 s to 13.2 s to 30.1 s. In other words, the requests were queued.
  - — [lilting.ch M1 Max engine benchmark](https://lilting.ch/en/articles/m1-max-llm-engine-benchmark)

**LM Studio**
- 0.4.0 (28 Jan 2026) added parallel requests with continuous batching for the llama.cpp engine. The `n_parallel` setting ("Max Concurrent Predictions") defaults to 4. — [LM Studio 0.4.0 changelog](https://lmstudio.ai/changelog/lmstudio-v0.4.0), [LM Studio 0.4.0 blog](https://lmstudio.ai/blog/0.4.0)
- 0.4.2 (6 Feb 2026) added parallel requests for MLX through continuous batching in mlx-engine 1.0.0, text-only at the time. — [LM Studio 0.4.2 changelog](https://lmstudio.ai/changelog/lmstudio-v0.4.2)

**mlx-lm built-in server (`mlx_lm.server`)**
- The official doc warns: "The MLX LM server is not recommended for production as it only implements basic security checks." It also says the server processes requests one at a time when `--kv-bits` (quantized KV cache) is set. — [mlx-lm SERVER.md](https://github.com/ml-explore/mlx-lm/blob/main/mlx_lm/SERVER.md)
- mlx-lm continuous batching was announced by Awni Hannun on 3 Dec 2025 (an older item). — [Popular AI](https://www.popularai.org/p/ollama-num-parallel-mac-mlx)
- **Measured on an M1 Max, 28 Oct 2026.** mlx-lm 0.32.2 with 8 slots on Qwen3.5-9B MLX 4-bit reached 71.4 / 79.4 / 69.7 tok/s aggregate at 2 / 4 / 8 concurrent. Under identical settings, the "Locals" engine reached 100.4 / 124.7 / 203.1 tok/s. — [lilting.ch](https://lilting.ch/en/articles/m1-max-llm-engine-benchmark)
- **Shared prompt cache race.** LocalAI ported mlx-lm's `LRUPromptCache` because a single shared prompt cache could corrupt KV state under concurrent requests. It also notes upstream deliberately does not match single-token prefixes. — [LocalAI mlx_cache.py](https://gitea.varghacsongor.hu/GithubMirror/LocalAI/src/commit/3370d807c2f311f7d9cfe05156ff432b562a1949/backend/python/mlx/mlx_cache.py)

**vllm-mlx (waybarrios/vllm-mlx)**
- "High-performance OpenAI and Anthropic compatible LLM inference server for Apple Silicon". Apache-2.0, about 1.6k stars. The README pins 0.4.1 as its reference release. — [GitHub waybarrios/vllm-mlx](https://github.com/waybarrios/vllm-mlx)
- **Features.**
  - Continuous batching is opt-in with `--continuous-batching`.
  - Paged KV cache with prefix sharing, a trie-based prefix cache, an SSD-tiered KV cache (`--ssd-cache-dir`), and `--warm-prompts` for prefix preloading (claims 1.3–2.25× faster TTFT).
  - JSON Schema via `response_format` (lm-format-enforcer) and 19 tool-call parsers.
  - Anthropic `/v1/messages`, MTP speculative decoding (`--enable-mtp`), and a `/metrics` endpoint.
  - `vllm-mlx bench-serve` for concurrency sweeps.
  - — [GitHub waybarrios/vllm-mlx](https://github.com/waybarrios/vllm-mlx)
- **Install.** `pip install 'vllm-mlx==0.4.1'`, then `vllm-mlx serve <hf-repo> --continuous-batching`. — [GitHub waybarrios/vllm-mlx](https://github.com/waybarrios/vllm-mlx)
- **arXiv paper** (Barrios, Jan 2026; M4 Max 128 GB, an older item), 4-bit decode tok/s for vllm-mlx / vllm-metal / mlx-lm / llama.cpp:

  | Model | vllm-mlx | vllm-metal | mlx-lm | llama.cpp |
  |---|---|---|---|---|
  | Qwen3-0.6B | 525.5 | 365.8 | 356.2 | 281.5 |
  | Qwen3-4B | 159.0 | 137.3 | 128.9 | 118.2 |
  | Qwen3-8B | 93.3 | 87.1 | 79.9 | 76.9 |
  | Qwen3-30B-A3B | 109.7 | 110.3 | 107.4 | 89.9 |
  | Llama-3.2-3B | 203.6 | 174.3 | 167.5 | 155.8 |
  | Gemma 3-4B | 152.5 | 117.0 | 105.4 | 123.2 |

  - Text prefix cache: Qwen3-4B with a 512-token shared prefix, TTFT fell from 245 ms to 42 ms (5.8×).
  - — [arXiv 2601.19139 HTML](https://arxiv.org/html/2601.19139v2)
- vllm-metal is the official vLLM backend for Apple Silicon. It also provides continuous batching but, per the paper, lacks multimodal support and vision caching. — [arXiv 2601.19139](https://www.arxiv.org/abs/2601.19139)

**llama.cpp `llama-server`**
- **Flags** (current README):
  - `-np, --parallel N`: number of server slots, default -1 (auto).
  - `-cb, --cont-batching`: enabled by default.
  - `-kvu, --kv-unified`: a single KV buffer shared across all sequences; on by default when slots are auto.
  - `--kv-unified-per-slot N`: per-slot context cap.
  - `--cache-prompt`: enabled by default.
  - `--cache-reuse N`: reuses KV through shifting.
  - `-cram, --cache-ram N`: prompt cache in host RAM, default 8192 MiB.
  - `--slot-save-path`.
  - `GET /slots` for monitoring.
  - — [llama.cpp server README](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)
- **Structured output and tools.** `--grammar` and `--json-schema`, plus per-request `grammar` and `json_schema` fields. Tool calling through `--jinja` (enabled by default) for "~any model". Speculative decoding through `--spec-type` (draft model, EAGLE3, MTP, n-gram). — [llama.cpp server README](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)
- **Determinism caveat.** The README warns that with `cache_prompt`, logits are not guaranteed bit-identical across batch sizes, so results can be nondeterministic. — [llama.cpp server README](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)
- **Measured on an M1 Max (64 GB), Oct 2026.** llama.cpp build 11669, Qwen3.5-9B UD-Q4_K_XL, `--parallel 8 --ctx-size 32768` (4,096 tokens per slot):

  | Concurrency | Aggregate tok/s | Per-stream tok/s | Median TTFT |
  |---|---|---|---|
  | 2 | 42.4 | 21.8 | 0.69 s |
  | 4 | 78.0 | 20.7 | 1.34 s |
  | 8 | 122.0 | 16.9 | 2.41 s |

  Single-stream speed without speculative decoding was 36.6 tok/s. — [lilting.ch](https://lilting.ch/en/articles/m1-max-llm-engine-benchmark)

### Inferences
Synthesized comparison for this use case (late 2026):

| Stack | Continuous batching on Mac | Prefix / prompt cache | Structured JSON / tools | Fit for an agent swarm on a 32 GB M1 Max |
|---|---|---|---|---|
| **oMLX** | Yes (mlx-lm BatchGenerator), default 8 concurrent, configurable | Paged RAM + **SSD** tier, prefix sharing, copy-on-write | JSON schema, regex, EBNF; many tool parsers | **Best fit**: MLX speed, caching built for repeated long prefixes, easy Mac app. Pre-1.0 churn. |
| vllm-mlx | Yes (`--continuous-batching`) | Paged + trie prefix + SSD tier, warm-prompts | JSON schema via lm-format-enforcer; 19 tool parsers | Strong alternative and oMLX's upstream; CLI-only, smaller community. |
| llama.cpp server | Yes (default), unified KV | Prompt cache, RAM cache, cache-reuse, slot save | GBNF grammar and JSON schema (very robust); `--jinja` tools | Most stable. GGUF on Metal is usually somewhat slower than MLX per stream but scales well (122 tok/s at 8 streams for a 9B). |
| LM Studio | Yes for both llama.cpp and MLX engines (since 0.4.2) | Engine-dependent | (not verified this session) | Fine for prototyping, GUI-first; less control. |
| Ollama (installed) | **No on the MLX runner** (PR open). GGUF runner honors `OLLAMA_NUM_PARALLEL`, except for Qwen3.5-family hybrids that are blocklisted. | MLX path has improved caching; GGUF path uses llama.cpp's prompt cache per slot | JSON / format and tools supported (not re-verified this session) | **Not recommended as the swarm server** today. Keep it for one-off use; don't rely on it for concurrency. |
| mlx_lm.server | Batches but scaled poorly (about 70 tok/s at 8 streams, M1 Max, 9B) | LRU prompt cache | Basic | Dev and testing only ("not recommended for production"). |

- For a swarm, the deciding features are (a) continuous batching, (b) a paged prefix cache that reuses shared world-rules and per-agent prefixes, and (c) grammar-constrained JSON so agents always emit parseable actions. oMLX has all three. llama.cpp is the conservative fallback if oMLX proves unstable.

### Gaps
- No head-to-head oMLX vs llama.cpp vs vllm-mlx benchmark on the same Mac at 8–32 concurrent requests was found.
- LM Studio's current (late-2026) MLX parallel defaults and structured-output support were not verified this session.
- Ollama's GGUF-path aggregate throughput on Mac under `OLLAMA_NUM_PARALLEL` was not found. The lilting test used the MLX path.
- `mlx_lm.server`'s current batching CLI flags are not documented in SERVER.md. I could not confirm whether flag names like `--decode-concurrency` belong to upstream or to the separate mlx-openai-server project.

---

## 3. Benchmarks of aggregate throughput with N concurrent requests on M-series Macs

### Takeaway
Batching on Apple Silicon gives about 1.6–4× aggregate throughput. Gains flatten past roughly 8–16 streams, while per-stream speed drops sharply. On an M1 Max specifically, the best data points are:
- Qwen3.6-35B-A3B on oMLX (64 GB machine): 71 → 94 → 116 tok/s at 1 / 2 / 4 concurrent.
- Qwen3.5-9B: about 122 tok/s at 8 concurrent on llama.cpp, and about 203 tok/s on the "Locals" engine.

Prefill on an M1 Max is only about 450–600 tok/s for a 35B-A3B model, so prompt caching matters as much as batching.

### Cited Findings
- **oMLX, M1 Max 32-core GPU, 64 GB, Qwen3.6-35B-A3B 4-bit** (oMLX v0.4.3, macOS 26.5.1, 2026-06-09):
  - Batching: TG 71.1 tok/s at 1×, 94.1 at 2× (1.32×), 115.5 at 4× (1.62×).
  - 1k context: PP 454 tok/s, peak memory 19.3 GB.
  - 4k context: PP 591 tok/s, TG 68.9 tok/s, TTFT 6.9 s, peak memory 20.0 GB.
  - — [oMLX benchmark 5n5khp20](https://omlx.ai/benchmarks/performance/5n5khp20)
- **oMLX vendor numbers, M3 Ultra 512 GB** (pp1024/tg128, no cache reuse):

  | Model | 1× | 2× | 4× | 8× |
  |---|---|---|---|---|
  | Qwen3-Coder-Next-8bit | 58.7 | 100.5 | 164.0 | 243.3 (4.14×) |
  | Qwen3.5-122B-A10B-4bit | 56.6 | 92.1 | 135.1 | 190.2 (3.36×) |
  | MiniMax-M2.5-8bit | 34.0 | — | — | 126.3 (3.71×) |
  | GLM-5-4bit | 16.7 | — | — | 60.3 (3.61×) |

  — [omlx.ai](https://omlx.ai)
- **M1 Max 64 GB, Qwen3.5-9B 4-bit, 28 Oct 2026, aggregate tok/s at 2 / 4 / 8 concurrent:**
  - llama.cpp (`--parallel 8`): 42.4 / 78.0 / 122.0
  - Magnitude: 56.8 / 72.2 / 133.0
  - Locals: 100.4 / 124.7 / 203.1
  - mlx-lm 0.32.2: 71.4 / 79.4 / 69.7
  - uzu: about 55, flat
  - Ollama MLX: about 54, flat (serialized)
  - Caveats: single author, different quant formats per engine, Ollama speculation could not be disabled.
  - — [lilting.ch](https://lilting.ch/en/articles/m1-max-llm-engine-benchmark)
- **Same test, single-stream decode on Qwen3.5-9B (M1 Max, 64 GB):**
  - llama.cpp GGUF: 36.6 tok/s; 48–60 with MTP speculation.
  - Locals MLX 4-bit, 1 slot: 60.0.
  - Ollama MLX NVFP4: 47.3.
  - The MLX 4-bit weights were about 5.98 GB.
  - — [lilting.ch](https://lilting.ch/en/articles/m1-max-llm-engine-benchmark)
- **vllm-mlx, M5 Max 128 GB, Qwen3-8B-4bit, about 3.6k-token prompts** (Jul 2026):

  | Concurrency | Aggregate completion tok/s | Per-request tok/s | TTFT p50 |
  |---|---|---|---|
  | 1 | 82 | 87 | — |
  | 5 | 193 | 42 | — |
  | 10 | 197 | 20.3 | — |
  | 15 | 215 | 16.3 | 9.6 s |

  End-to-end requests per minute peaked at about 2× baseline at c=5–10. — [vllm-mlx Discussion #637](https://github.com/waybarrios/vllm-mlx/discussions/637)
- **vllm-mlx paper, M4 Max** (Jan 2026): Qwen3-0.6B went from 441 tok/s at 1 concurrent to 1642 tok/s at 16 (3.7×), "over 25 requests per second". Qwen3-8B scaled 2.6× at 16 concurrent. — [arXiv 2601.19139 HTML](https://arxiv.org/html/2601.19139v2)
- **Memory bandwidth.** M1 Max has 400 GB/s. The M4 Max cited in the paper has 546 GB/s. — [Apple newsroom, Oct 2021](https://www.apple.com/newsroom/2021/10/introducing-m1-pro-and-m1-max-the-most-powerful-chips-apple-has-ever-built/), [arXiv 2601.19139 HTML](https://arxiv.org/html/2601.19139v2)
- **Qwen3.6-35B-A3B on a 24-GPU-core M1 Max, 32 GB** (MTPLX 2.9.1 runtime, Aug 2026):
  - Decode about 42 tok/s at short context, 39.2 at about 2K context, 36.9 at about 8K.
  - Peak RAM 20.6–23.3 GB with no jetsam kills.
  - — [Layr-Labs/d-inference issue #724](https://github.com/Layr-Labs/d-inference/issues/724)

### Inferences
- **GPU core count matters for estimates.** A 24-core and a 32-core M1 Max differ substantially. Decode on the same model measured about 42 tok/s on 24 cores (different runtime) versus about 69–71 tok/s on 32 cores (oMLX). The user should check their GPU core count (About This Mac or `system_profiler SPDisplaysDataType`).
- **Estimated aggregate decode on this M1 Max (32 GB) with oMLX.** Extrapolated from the data above; not measured.
  - Qwen3.6-35B-A3B 4-bit: about 70 tok/s at 1; about 115 at 4; perhaps 130–160 at 8. Little gain beyond that, and KV memory runs out first on 32 GB.
  - 8–9B dense 4-bit: about 55–60 at 1; about 120–200 at 8; perhaps 200–250 at 16.
  - 3–4B 4-bit: about 100–120 at 1 (M4 Max figure scaled by bandwidth); perhaps 300–450 at 16–32.
  - 0.6–2B: higher still, but agent quality is weak.
- **Prefill is the hidden bottleneck.** At about 450–600 tok/s PP for a 35B-A3B model (and likely around 1–2k tok/s for a 4B), each 1,000 uncached prompt tokens costs roughly 1–2 s of GPU time for the mid model. Prefill competes with decode in the same batch, so a swarm that re-sends 3–4k-token prompts without cache hits will be prefill-bound. Prefix-cache hit rate is therefore the number-one lever: put static world rules first, then a slowly changing agent memory, then new observations last.

### Gaps
- No public measurements were found for 16 or 32 concurrent requests on any M1-class Mac, or for oMLX at 8× on an M1 Max.
- No oMLX numbers were found for small (≤9B) models on an M1 Max.
- The "Locals" engine's provenance and maturity were not investigated.

---

## 4. Which models to run in 32 GB for agentic, tool-use and game-agent work (late 2026)

### Takeaway
The leading late-2026 candidates that fit in 32 GB:
- **Qwen3.6-35B-A3B**: MoE, about 3B active, Apache-2.0, 262K context. About 20–23 GB peak at 4-bit and about 40–70 tok/s on an M1 Max depending on GPU cores.
- **Gemma 4 26B-A4B**: MoE, native function calling.
- **GLM-4.7-Flash 30B-A3B** and **Nemotron 3.5 Lightning 30B-A3B**: agent-oriented MoEs.
- **Qwen3.5-9B / 4B and Gemma 4 E4B**: small dense or efficient models, the realistic choice when agent count matters more than per-agent intelligence.

On a 32 GB machine that also runs a game world, a 35B-A3B model leaves little KV-cache room for many concurrent sequences. A smaller model shared by all agents is usually the better swarm choice.

### Cited Findings
- **Qwen release landscape.**
  - Qwen3.5 small models: 9B, 4B, 2B, 0.8B (2 Mar 2026). Mid and large: 27B, 35B-A3B, 122B-A10B, 397B-A17B.
  - Qwen3.6: 35B-A3B (16 Apr 2026) and 27B (22 Apr 2026).
  - Qwen3.8: only 27B dense (14 Aug 2026) and 2.4T-A95B (12 Aug 2026), plus the Flash-Next MoE preview (125B + 51B n-gram embeddings, 6B active), which is far too big for 32 GB. No small Qwen3.8 models are listed.
  - — [GitHub QwenLM/Qwen3.8](https://github.com/QwenLM/Qwen3.8), [Qwen3.8-Flash-Next HF](https://huggingface.co/Qwen/Qwen3.8-Flash-Next)
- **Atomic Chat's 32 GB guide (Aug 25, 2026)**, footprints on 32 GB unified memory:

  | Model | Total / active params | Quant | Footprint | Context | Agent-related notes |
  |---|---|---|---|---|---|
  | Qwen3.6 35B-A3B | 35B / ~3B | Q4_K_M | 21.2 GB | 262,144 native | MCP-Atlas 62.8, Terminal-Bench 2.0 51.5 |
  | Nemotron 3.5 Lightning 30B-A3B | 30B / ~3B | IQ4_NL | 19.7 GB | — | "designed for agents, tool calls, and structured output" |
  | GLM-4.7-Flash 30B-A3B | ~30B / 3B | Q5_K_M | 21.57 GB | — | Tau2-Bench 79.5; preserved thinking grows context quickly |
  | Gemma 4 31B dense | 30.7B | Q5_K_M | 21.8 GB | — | — |
  | Devstral Small 2 24B | 24B dense | Q6_K | 19.35 GB | — | Mistral function calling |

  — [Atomic Chat](https://atomic.chat/blog/guides/best-local-llm-32gb)
- **Gemma 4** (early April 2026) comes in E2B, E4B, 26B A4B (MoE) and 31B dense, Apache 2.0. All support function calling, structured JSON output and system instructions. Context is 128K for E2B/E4B and 256K for 26B/31B. Sources are secondary news coverage. — [SiliconANGLE, Apr 2 2026](https://siliconangle.com/?p=737125), [Notebookcheck](https://www.notebookcheck.net/Gemma-4-on-Hugging-Face-Google-s-Easter-surprise-for-download.1265198.0.html)
- **Qwen3.6-35B-A3B on a 32 GB M1 Max (24-core GPU):** about 37–43 tok/s and 20.6–23.3 GB peak. The same issue says gpt-oss-20b needs about 20 GB to load on that platform's memory gate. — [Layr-Labs issue #724](https://github.com/Layr-Labs/d-inference/issues/724)
- **Qwen3.6-35B-A3B on a 64 GB M1 Max (32-core GPU):** 68.9–71.1 tok/s decode and 19.3–20.0 GB peak on oMLX. oMLX 0.7.3rc1 reports 82.4 tok/s with the new M1/M2 Float16 Activations option. — [oMLX benchmark](https://omlx.ai/benchmarks/performance/5n5khp20), [oMLX releases](https://github.com/jundot/omlx/releases)
- **Small-model weight sizes** (vllm-mlx README):
  - Qwen3-0.6B-8bit: 0.7 GB
  - Llama-3.2-3B-Instruct-4bit: 1.8 GB
  - Qwen3-30B-A3B-4bit: about 18 GB
  - Qwen3.5-9B MLX 4-bit: about 5.98 GB (lilting.ch)
  - — [GitHub waybarrios/vllm-mlx](https://github.com/waybarrios/vllm-mlx), [lilting.ch](https://lilting.ch/en/articles/m1-max-llm-engine-benchmark)
- **Third-party speed estimates for a 32 GB M1 Max.** These are not measurements and the sources disagree widely: Gemma 4 26B MoE Q6_K at about 29.7 tok/s; GPT-OSS 20B Q6_K at about 31.8 tok/s. — [canitrun.dev M1 Max](https://canitrun.dev/gpus/m1-max/)
- **Native kernels.** oMLX's README lists "Qwen3.5" among the models that need native custom kernels, and full Xcode is required to build them. — [GitHub jundot/omlx](https://github.com/jundot/omlx)

### Inferences
- **Memory budget (estimates).** With the GPU allowed about 24 GB (see section 5) and a game world needing a few GB of CPU RAM:

  | Option | Weights (4-bit) | KV / batch headroom | Notes |
  |---|---|---|---|
  | Qwen3.6-35B-A3B | ~19–21 GB | ~1–4 GB | Strongest agentic quality that fits. Tight; may need the wired limit raised and short contexts. |
  | Gemma 4 26B-A4B | ~14–16 GB (my estimate at ~4.5 bits/weight) | ~8 GB | Good middle ground; verify MLX support and tool-call parser in oMLX. |
  | gpt-oss-20b | ~12–13 GB (MXFP4, my estimate) | — | Not re-verified this session. |
  | Qwen3.5-9B / Gemma 4 E4B / Qwen3.5-4B | ~6 GB / ~3–5 GB / ~2.5–3 GB | ~15–20 GB | Room for a large batch of 16–32 sequences with long prompts. |

- **One shared model vs several tiny models.** Serve **one model to all agents.**
  - Continuous batching amortizes weight reads across sequences, and the prefix cache shares the world-rules prefix only within one model.
  - Several different models split memory and bandwidth, and each loses batching efficiency.
  - A reasonable two-tier design: one small fast model (4–9B) for routine agent actions, plus a mid MoE (Qwen3.6-35B-A3B or Gemma 4 26B-A4B) loaded on demand for rare "important" reasoning. oMLX supports multi-model with LRU, pinning and TTL. However, the two models together likely won't fit alongside a game on 32 GB unless the big one is 26B-A4B and the small one is 4B or less.
- **Hybrid attention helps concurrency.** Qwen3.5/3.6 are hybrid linear-attention plus attention models (inferred from the "rotating and recurrent caches for Qwen3.5-style hybrid models" wording in Ollama PR #17317). That gives smaller per-sequence KV growth, which suits many concurrent agents. Prefix-cache support for hybrids depends on the server; oMLX 0.7.3 explicitly added shared-system-prompt reuse for hybrid Qwen. Ollama's GGUF path blocklisted these architectures from parallel requests.
- **Turn off thinking for agent ticks.** Thinking or reasoning modes multiply output tokens. For JSON actions, set thinking off and use grammar-constrained JSON to keep outputs at roughly 50–200 tokens.

### Gaps
- No direct MLX benchmarks on an M1 Max were found for Gemma 4 26B-A4B, Gemma 4 E4B, Qwen3.5-4B/9B under oMLX, gpt-oss-20b, GLM-4.7-Flash or Nemotron 3.5 Lightning.
- Official Gemma 4 model cards were not fetched; the details come from news coverage.
- No independent benchmark of "game agent" quality across these models was found. Tool-use scores are vendor-reported (Tau2, MCP-Atlas, Terminal-Bench).
- Phi, Ministral, SmolLM and Llama late-2026 versions were not researched due to time limits.

---

## 5. How much unified memory macOS lets the GPU use (wired limit) on a 32 GB Mac

### Takeaway
By default macOS caps GPU-wired memory at a fraction of RAM. `sysctl iogpu.wired_limit_mb` returns 0, meaning "system default", not "unlimited". On 32 GB machines the observed working set is about 21–24 GB. You can raise it temporarily with `sudo sysctl iogpu.wired_limit_mb=<MB>`; the setting resets on reboot. oMLX's own default cap is RAM minus 8 GB (24 GB here), and oMLX re-reads the sysctl live.

### Cited Findings
- **Default value.** `iogpu.wired_limit_mb=0` means "use the system default", not "no limit". A GitHub note labels the default as roughly 75%. A 64 GB M1 Max user measured a default of 49152 MB, which is 75%. — [devnote override macOS metal vram cap](https://github.com/ivanopcode/devnote-override-macos-metal-vram-cap), [r/LocalLLaMA thread, Nov 2023 (older)](https://axebps-redlib.hf.space/r/LocalLLaMA/comments/186phti/m1m2m3_increase_vram_allocation_with_sudo_sysctl)
- **Observed on a 32 GB M1 Max Mac Studio** (macOS 26.6.2): "Metal working set: 24 GB; usable memory: 23.3 GB". — [Layr-Labs issue #724](https://github.com/Layr-Labs/d-inference/issues/724)
- **Observed on a 32 GB M1 Pro:** usable memory was only 17.3–17.4 GB per that tool's doctor check. This may reflect the tool's own accounting. — [Layr-Labs issue #724](https://github.com/Layr-Labs/d-inference/issues/724)
- **Suggested settings for 32 GB.** Guides suggest `sudo sysctl iogpu.wired_limit_mb=24576` (24 GB) or up to 28672 (28 GB). The change does not survive a reboot unless added to `/etc/sysctl.conf`, and guides advise leaving about 8–16 GB for macOS. Older macOS versions used the key `debug.iogpu.wired_limit`. — [contracollective guide, 2026](https://contracollective.com/blog/mac-unified-memory-wired-limit-gpu-large-local-llm-2026), [llmconfigurator guide](https://llmconfigurator.com/pl/guides/troubleshooting/increase-metal-vram-limit-apple-silicon)
- **MLX wired limit API.** MLX exposes `mx.set_wired_limit`, and the effective ceiling appears as `recommendedMaxWorkingSetSize` in `mx.metal.device_info()`. — [MLX docs set_wired_limit](https://ml-explore.github.io/mlx/build/html/python/_autosummary/mlx.core.set_wired_limit.html)
- **oMLX memory settings.**
  - Total memory limit defaults to system RAM minus 8 GB.
  - `--memory-guard` has tiers, with `balanced` as the default.
  - `--hot-cache-max-size` and `--paged-ssd-cache-max-size` control the cache tiers.
  - From 0.7.3rc1, the memory guard re-reads `iogpu.wired_limit_mb` live.
  - — [GitHub jundot/omlx](https://github.com/jundot/omlx), [jundot/omlx releases](https://github.com/jundot/omlx/releases)

### Inferences
- **Practical budget on this 32 GB MacBook.** About 22–24 GB for the model plus KV cache. The game world, IDE and browser plus macOS need the remaining about 8–10 GB.
- Raising the limit to 26–27 GB (`sudo sysctl iogpu.wired_limit_mb=26624`) is possible if the game is light. Going higher risks swap and jetsam kills of the game process.
- For the swarm, a model of 6–15 GB is preferable to a 20 GB model, because the leftover GPU memory becomes concurrent-sequence KV capacity, which directly sets how many agents can think at once.
- Run `sysctl iogpu.wired_limit_mb` and `python -c "import mlx.core as mx; print(mx.metal.device_info())"` to see the real ceiling on this machine.

### Gaps
- I found no authoritative Apple document stating the exact default fraction for 32 GB machines. Some reports say about 2/3 of RAM on ≤36 GB Macs and about 3/4 above; I could not verify that this session. The observed 24 GB working set on a 32 GB M1 Max suggests about 75%.

---

## 6. Practical recommendation: what's realistic for about 10, 25, 50 and 100 agents on this machine

### Takeaway
Use **oMLX** (fallback: llama.cpp `llama-server`) with **one shared model**, prompts structured for maximum prefix-cache hits, thinking turned off, and short grammar-constrained JSON outputs. LLM-bound "think" rates are roughly:
- ~10 agents: one think every ~5–15 s each.
- ~25 agents: every ~10–30 s.
- ~50 agents: every ~20–45 s.
- ~100 agents: every ~45–90 s.

The larger counts require a small (4B-class) model plus event-driven, not per-tick, LLM calls. **All figures here are estimates** extrapolated from the benchmarks above, not measurements.

### Cited Findings
- Aggregate decode scaling flattens past about 8–16 concurrent streams, and per-stream speed drops sharply. Qwen3-8B on an M5 Max: 82 → 197 → 215 tok/s at c=1 / 10 / 15, with per-request speed falling from 87 to 16 tok/s and TTFT reaching 9.6 s at c=15. — [vllm-mlx Discussion #637](https://github.com/waybarrios/vllm-mlx/discussions/637)
- On an M1 Max, a 9B model reaches about 122–203 tok/s aggregate at 8 concurrent, depending on engine. — [lilting.ch](https://lilting.ch/en/articles/m1-max-llm-engine-benchmark)
- On an M1 Max (32-core GPU), Qwen3.6-35B-A3B on oMLX reaches about 116 tok/s aggregate at 4 concurrent, with PP about 450–590 tok/s. — [oMLX benchmark](https://omlx.ai/benchmarks/performance/5n5khp20)
- A prefix-cache hit cut TTFT 5.8× for a 512-token shared prefix. — [arXiv 2601.19139 HTML](https://arxiv.org/html/2601.19139v2)
- oMLX's default max concurrency is 8 and is configurable. Its example uses 16. — [GitHub jundot/omlx](https://github.com/jundot/omlx)

### Inferences
**Assumptions** (all estimates): each agent "think" means about 2–4k prompt tokens, of which about 300–800 are new or uncached per tick, and about 100–200 output tokens (JSON action, thinking off). Throughput is about 1 think/s for the 35B-A3B, about 1.5–2.5 thinks/s for a 9B, and about 3–5 thinks/s for a 4B, after counting both prefill and decode.

| Agents | Suggested model | Server config | Realistic think rate per agent | Notes |
|---|---|---|---|---|
| ~10 | Qwen3.6-35B-A3B 4-bit (best quality), or Qwen3.5-9B for speed | oMLX, max concurrent 8–10 | 35B-A3B: one think every ~10–15 s. 9B: every ~5–8 s. | 35B-A3B at ~20 GB is tight on 32 GB; cap context at ~8–16k. Gemma 4 26B-A4B is the roomier mid option. |
| ~25 | 8–9B dense (Qwen3.5-9B) or Gemma 4 E4B | oMLX, concurrency 16, SSD cache on | ~every 10–20 s (9B) or 15–30 s | Stagger agent ticks so the batch stays full; avoid synchronized ticks. |
| ~50 | 4B-class (Qwen3.5-4B, Gemma 4 E4B) | oMLX or llama.cpp, concurrency 16–32 | ~every 15–30 s (4B) | Use utility AI or behavior trees between LLM calls. Call the LLM only on salient events (new agent met, goal done, conflict). |
| ~100 | 2–4B (Qwen3.5-4B/2B, Gemma 4 E2B/E4B) | Concurrency 32, aggressive prefix caching | ~every 30–90 s if every agent uses the LLM | Realistic only with a hierarchy: most agents scripted, LLM used for planning every N ticks or for "leader" agents. Consider batching several agents into one prompt (one call returns JSON actions for 5–10 NPCs), which amortizes the shared prefix. |

**Engineering tips** (inferences that follow from the cited mechanics):
- **Prompt layout for cache hits:** `[static world rules + tool schema] → [agent persona + long-term memory summary (changes rarely)] → [recent event log (append-only)] → [current observation + instruction]`. Never put timestamps or random IDs near the top of the prompt.
- **Output size:** use JSON-schema-constrained output (oMLX, vllm-mlx and llama.cpp all support it) with a small action schema, and a low `max_tokens` (about 150).
- **Concurrency setting:** raise oMLX max concurrency from 8 to about 16. Beyond about 16–32 on an M1 Max, the gain is mostly in queueing fairness, not throughput, while TTFT grows.
- **Scheduling:** run the sim tick independently of LLM latency. Each agent submits a think request, keeps acting on its last plan until the reply arrives, and the queue depth throttles itself.
- **Ollama:** keep the installed copy for ad-hoc use, but don't use it as the swarm server until PR #17317 (MLX continuous batching) ships. If you must use Ollama, use GGUF models with `OLLAMA_NUM_PARALLEL`, and note that Qwen3.5-family architectures are blocklisted from parallel on that path (PR #17144 pending).
- **Hardware footnote:** more RAM and a newer chip (M4/M5 Max, 64–128 GB) would roughly double to triple both batch capacity and prefill speed. Not a recommendation, since the hardware is fixed.

### Gaps
- No end-to-end benchmark of an LLM agent swarm (for example Generative-Agents-style) on Apple Silicon was found. Agent counts and think rates above are my estimates and should be validated with `vllm-mlx bench-serve` or oMLX's built-in benchmark on this exact machine, using a realistic agent prompt.
- The real prefix-cache hit rate for a game swarm depends on prompt design and was not measured anywhere.
