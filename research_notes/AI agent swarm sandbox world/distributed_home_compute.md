# Distributed Home Compute for an LLM Agent Swarm ("any laptop runs a script and joins the swarm world")

Research date: 2026-11-01. Scope (per the user's clarification mid-task): every home machine joins the shared world as a client, like a player joining a multiplayer game server. It runs its own local model and its own agents, and agents on different machines interact only in-world. Inference-pooling routers are a secondary option, and model-sharding is a footnote for the "one model bigger than any single machine" case. GitHub metadata (stars, last push, latest release) was pulled via `gh api` on 2026-11-01.

---

## Q1. Strategy comparison: agents-as-players (B-local) vs. inference pooling (B-router) vs. model-sharding (A), and network realities

### Takeaway
For a swarm, meaning many concurrent, small, latency-tolerant LLM calls, the "agents-as-players" pattern wins clearly. Each machine runs a local model server bound to localhost plus N agents, and only small text observations and actions cross the LAN. This works fine over home Wi-Fi. Model-sharding (exo, llama.cpp RPC, MLX distributed) is built for fitting one big model or speeding up a single stream. It is bandwidth- and latency-bound per token, wants Ethernet or Thunderbolt 5, and its concurrency support is immature. Central routers (LiteLLM, Olla, Paddler) are a useful optional layer, for example sending "big-brain" calls to the PC with the biggest GPU. They are not required for the core design.

### Cited Findings
**Model-sharding is per-token network-bound:**
- llama.cpp RPC splits layers across nodes. Jeff Geerling (Dec 2025) found it "scales but is inefficient, causing performance to decrease as you add more nodes"; exo with RDMA tensor parallelism instead sped up as nodes were added (Qwen3 235B reached about 32 tok/s on 4x M3 Ultra) — [Jeff Geerling, Dec 18 2025](https://www.jeffgeerling.com/blog/2025/15-tb-vram-on-mac-studio-rdma-over-thunderbolt-5)
- RDMA over Thunderbolt 5 cut memory-access latency between Macs from about 300 μs to under 50 μs (Geerling citing an MLX PR). Thunderbolt beats Ethernet on latency even without RDMA, though no numbers were given — [Jeff Geerling](https://www.jeffgeerling.com/blog/2025/15-tb-vram-on-mac-studio-rdma-over-thunderbolt-5)
- A Mac Studio M2 Ultra plus DGX Spark over direct 10GbE (9.41 Gbps measured) running llama.cpp RPC showed decode about 2x slower on a 7B model and about 47% slower on a 72B model than local runs. The author attributes this to sequential, latency-bound decode. This is a single-author repo with few stars — [kjaiswal/llama-cpp-distributed-benchmarks](https://github.com/kjaiswal/llama-cpp-distributed-benchmarks); [dev.to write-up](https://dev.to/ljkunal/distributed-llm-inference-across-nvidia-blackwell-and-apple-silicon-over-10gbe-2feg)
- The same author reports that MLX's ring backend hung on CUDA, which is why mixed Mac + NVIDIA setups use llama.cpp RPC: it only needs a raw compute server on each end — [dev.to](https://dev.to/ljkunal/distributed-llm-inference-across-nvidia-blackwell-and-apple-silicon-over-10gbe-2feg)
- (STALE, May 2024) An M1 Max + RX 7900 XTX test over llama.cpp RPC: each machine alone exceeded 48 t/s, but remote runs were capped at 48 t/s, and the poster said Wi-Fi on the Mac made the network the bottleneck — [r/LocalLLaMA thread, 2024](https://redlib.hbubli.cc/r/LocalLLaMA/comments/1cyzi9e/llamacpp_now_supports_distributed_inference)
- (2026, single post, seen only through a search summary) Two RTX 5090s over 2.5GbE with llama.cpp RPC ran a 122B MoE at about 96 t/s, and the author called RPC "mature enough to be a daily driver" — [r/LocalLLaMA snapshot, Apr 2026](https://reddit.sentinel-team.org/posts/1sfs0wt/snapshots/2026-04-09T16%3A11%3A00.655487Z)

**Sharding tools are weak on concurrency:**
- exo has open issues titled "Pipeline-parallel deadlock at 32+ concurrent requests — all_gather collective blocks indefinitely" (opened 2026-05-22) and "Sequential prefill blocks active decode — request for chunked / mixed batching" (opened 2026-04-16) — [exo #2108](https://github.com/exo-explore/exo/issues/2108); [exo #1908](https://github.com/exo-explore/exo/issues/1908)
- Further open exo stability issues: long-context requests to 2-node tensor instances hang or garble output (#2208, Jul 2026), and jaccl RDMA crashes on M3 Ultra "recurring in production" (#1847, Apr 2026) — [exo #2208](https://github.com/exo-explore/exo/issues/2208); [exo #1847](https://github.com/exo-explore/exo/issues/1847)

**Batching on a single machine gives swarm throughput without any network:**
- On an M1 Max (64 GB, macOS 27.0, Oct 28 2026) with Qwen3.5-9B 4-bit, single-stream llama.cpp ran at about 36.6 tok/s. llama-server with `--parallel 8` reached an aggregate 42.4 / 78.0 / 122.0 tok/s at 2/4/8 concurrent requests, with per-request speed falling to about 16.9 tok/s and median TTFT rising to 2.41 s at 8. The MLX-based "Locals" engine reached 203 tok/s aggregate at 8 streams — [lilting.ch M1 Max engine benchmark, 2026-10-28](https://lilting.ch/en/articles/m1-max-llm-engine-benchmark)

**Routers exist and are mature enough for the optional layer** (details in Q6): LiteLLM has `least-busy`, `latency-based-routing`, and other strategies with cooldowns — [LiteLLM routing docs](https://docs.litellm.ai/docs/routing).

### Inferences
- **Bandwidth needed by B-local (estimate):** an agent turn ships an observation (perhaps 1–4 KB of JSON or text) and an action (under 1 KB). Even 200 agents each acting once every 2–5 s is under about 0.5 MB/s, which is trivial for any Wi-Fi 5/6 link. Wi-Fi's few-to-tens of ms of jitter is noise next to multi-second LLM turns. Model-sharding, by contrast, crosses the network once per pipeline stage for every generated token, so Wi-Fi is effectively disqualifying and even 10GbE costs up to 2x decode speed.
- **Throughput math favors B-local.** A swarm's capacity is the sum of each machine's batched aggregate throughput. That sum scales linearly with machines, has no cross-machine coupling, and a laptop leaving does not stall anyone else. Sharding one model adds capacity (memory) but not concurrent throughput, and it creates a fragile all-nodes-must-be-up dependency.
- **"Smarter agents" without sharding:** give different machines different model tiers (the PC with a 24 GB GPU runs a 27–32B model, the M1 Max runs about 9–14B, small Macs run 3–4B). The world can then hold a mix of "big-brain" and "fast" agents. Shard only if one specific role (say, a "god/narrator" agent) truly needs a model larger than about 24 GB of usable memory.
- The 2021 M1 Max MacBook Pro has Thunderbolt 4, not Thunderbolt 5 (Apple spec, not re-verified here), so it cannot take part in exo RDMA clusters at all. exo's RDMA list names only TB5 Macs (see Q7).

### Gaps
- No rigorous Wi-Fi vs. Ethernet vs. Thunderbolt benchmark exists for the same exo/llama.cpp-RPC workload on 2026 builds. The data points above use different hardware, models and dates.
- No published measurement of world-server message sizes for LLM agent sims; the bandwidth figures above are my estimates.

---

## Q2. The node / "join script" architecture, world-server protocols, and existing examples of this pattern

### Takeaway
The cleanest precedent is "LLM bots as game clients": Mindcraft bots join a Minecraft server as ordinary players, each with its own configured model, including local Ollama. AI Town's engine treats human and agent "inputs" identically. The join UX of a token plus server URL plus N slots is well established in inference tools (Paddler `agent --slots N`, GPUStack worker token, LocalAI P2P token, exo zero-config discovery). Their join scripts can be borrowed even though their payload is inference rather than agents. Generic actor frameworks are a poor fit for mixed Mac and Windows hardware: Ray's multi-node mode is untested on macOS and experimental on Windows, and AgentScope v2 has moved to the A2A protocol.

### Cited Findings
**Agents-as-players precedents:**
- **Mindcraft** (5.9k stars, v0.1.4 Mar 2026, pushed 2026-10-27) — "Crafting minds for Minecraft with LLMs and Mineflayer". Each bot is a Mineflayer client that connects to a Minecraft server by `host`/`port` in `settings.js` (a local world is "open to LAN on localhost port 55916"). Each bot's profile JSON sets its own `model`, with `ollama` (local) and `vllm` among the supported APIs, so different bots can run different models. It warns: "Do not connect this bot to public servers with coding enabled… vulnerable to injection attacks," with `allow_insecure_coding` off by default and Docker recommended — [mindcraft-bots/mindcraft](https://github.com/mindcraft-bots/mindcraft)
- **AI Town** (a16z, 10.7k stars, pushed 2026-08) — a shared-global-state simulation engine on Convex, with Ollama local inference supported (default `llama3`). The architecture doc says "Both humans and agents submit inputs that the game engine processes," and the engine handles saving/loading state and feeding inputs. This is the authoritative-server/inputs pattern, but agent loops run server-side rather than on client machines — [ai-town README](https://github.com/a16z-infra/ai-town); [ARCHITECTURE.md](https://github.com/a16z-infra/ai-town/blob/main/ARCHITECTURE.md)
- **Project Sid** (Altera, arXiv 2411.00114, Oct 2024) — 10 to 1000+ agents in Minecraft. Its PIANO architecture lets agents act and talk in real time while keeping parallel output streams (speech, movement) coherent through a "Cognitive Controller" bottleneck. The authors report emergent specialization, rule-following and cultural transmission, and call the results preliminary — [arXiv 2411.00114](https://arxiv.org/abs/2411.00114); [third-party summary](https://papers.lunadong.com/paper/7566)

**Join-script UX precedents (inference payload):**
- **Paddler**: `paddler balancer …` plus `paddler agent --management-addr 127.0.0.1:8060 --slots 4`. Agents "can be added dynamically," and a desktop GUI is aimed at "using multiple laptops and PCs in a local AI cluster" — [intentee/paddler](https://github.com/intentee/paddler)
- **GPUStack**: workers join by running a Docker command containing a `--token` from the server UI, then "appear on the Workers page" — [gpustack/gpustack](https://github.com/gpustack/gpustack)
- **LocalAI P2P**: `local-ai run --p2p` generates a token, and workers join with `TOKEN=XXX` / `LOCALAI_P2P_TOKEN` — [LocalAI distributed docs](https://localai.io/docs/features/distribute/)
- **exo**: "Devices running exo find each other automatically, without any manual configuration, when they are on the same network and run the same version of exo." Each device serves an API and dashboard on `localhost:52415` — [exo README](https://github.com/exo-explore/exo)

**Generic distributed-agent frameworks (weak fit for mixed home hardware):**
- **Ray**: the current install docs mark multi-node clusters as untested on Apple Silicon and experimental/untested on Windows, with Windows support itself "beta" — [Ray installation docs](https://docs.ray.io/en/latest/ray-overview/installation.html)
- **AgentScope** (35k stars, v2.0.11 Oct 2026): the current README advertises the A2A protocol ("chat with any remote A2A agent via `A2AAgent`", Sep 2026). The v0.x distributed actor/RPC mode no longer appears in the README — [agentscope-ai/agentscope](https://github.com/agentscope-ai/agentscope)

**Stale volunteer-compute and multi-agent environments:**
- Petals ("Run LLMs at home, BitTorrent-style") was last released 2023-09-06 (v2.2.0) and last pushed 2024-09-07. It is effectively dormant — [bigscience-workshop/petals](https://github.com/bigscience-workshop/petals)
- Neural MMO was last released 2021, last pushed 2024-08. It is an RL environment, not an LLM-client architecture — [NeuralMMO/environment](https://github.com/NeuralMMO/environment)

### Inferences
**Recommended node process (`swarm-node`, one per machine), my design synthesis:**
1. **Probe hardware.** Read OS, chip/GPU, total and usable accelerator memory (see Q5).
2. **Ensure a local model server.** Attach to an existing one (probe `localhost:8000` for oMLX, `:11434` for Ollama, `:8080` for llama-server), or start one, always bound to `127.0.0.1`.
3. **Pick a model tier and concurrency.** Choose the tier from memory, then run a 20–60 s calibration benchmark at 1/2/4/8 parallel requests.
4. **Discover the world server** via mDNS (Q3), with a fallback to `--server ws://host:port` or a QR/URL.
5. **Open one authenticated, multiplexed WebSocket** to the world server. Send `hello{node_id, join_token, hw, model_id, slots, measured_tok_s}` and receive `welcome{agent assignments}`. For each agent, receive `observe{agent_id, tick, obs}` and send `act{agent_id, action}`. Exchange heartbeats every few seconds.
6. **Run N agent loops locally.** Each takes an observation, builds a prompt, calls the local LLM, validates the action against a JSON schema or grammar, and sends it. A local semaphore equal to the server's `slots` keeps the GPU saturated but not overloaded.
7. **Leave gracefully.** On Ctrl-C, sleep, or lid close, the node sends `bye`, and the world server marks its agents dormant (they "fall asleep" in-world) or reassigns them to another node.

**Key design decisions:**
- **The world server is authoritative and owns all agent state** (memory and persona stored server-side or synced back). Nodes are stateless "brains for hire," so a departing laptop loses nothing.
- **Asynchronous, event- or tick-based actions with deadlines** stop slow machines from stalling the world. An agent that misses a tick simply idles. This mirrors Project Sid's motivation for not blocking on sequential workflows.
- **WebSocket with JSON** is easier than gRPC for Python and JS clients and browser viewers, and has no codegen step. gRPC bidirectional streaming suits a typed schema across languages. Either works at home scale. A2A (as adopted by AgentScope) matters only if agents should be interoperable with external agent frameworks.
- **Oversubscribe agents to slots.** Agents spend part of each turn waiting for world events, so N_agents can be about 2–4x the model server's parallel slots. This is a heuristic estimate to tune empirically.

### Gaps
- No open-source project was found that implements exactly this pattern for LLM agents across heterogeneous home machines with mDNS discovery. Mindcraft (per-bot clients) is the closest. Multi-machine Mindcraft deployments are possible in principle, since each bot is just a client with a host/port, but no write-up was found.
- I did not find authoritative benchmarks comparing WebSocket and gRPC for this use; the recommendation is engineering judgment.

---

## Q3. LAN discovery (mDNS/Bonjour/zeroconf) and home-LAN security

### Takeaway
Run a pure-Python mDNS library (`python-zeroconf`, actively maintained, release 0.153.0 on 2026-10-31) inside both the world server (advertise `_swarmworld._tcp.local.`) and the node (browse). This works identically on macOS, Windows and Linux without depending on the OS's `.local` resolver, which is spotty on Windows. Always keep a manual `--server` fallback, because guest Wi-Fi and AP/client isolation block multicast. For security, under B-local only the world-server port needs to be reachable on the LAN. Model servers stay on localhost, a shared join token gates entry, and nothing is port-forwarded.

### Cited Findings
- python-zeroconf is "a pure python implementation of multicast DNS service discovery", Avahi/Bonjour-compatible, with latest release 0.153.0 (2026-10-31), still actively pushed — [python-zeroconf/python-zeroconf](https://github.com/python-zeroconf/python-zeroconf)
- mDNS uses multicast group 224.0.0.251, UDP port 5353 (library constants) — [python-zeroconf source](https://github.com/bdraco/python-zeroconf/blob/fd1c0635560304490704ef7a6677bff4fddbcdfc/zeroconf/__init__.py). The library has had Windows-specific fixes (EADDRNOTAVAIL on dummy interfaces in 0.17.7) and WSL compatibility (0.21.3) — [PyPI zeroconf 0.21.3](https://pypi.org/project/zeroconf/0.21.3)
- Native Windows `.local` resolution was historically incomplete (Windows 10 was "beginning" to add mDNS). Forum reports show inconsistent results and dependence on Bonjour, which is anecdotal evidence — [.local (Wikipedia mirror)](https://webcf.waybackmachine.org/web/20220328130540/https://en.wikipedia.org/wiki/.local); [Microsoft Tech Community thread](https://techcommunity.microsoft.com/t5/windows-10/mdns-windows-10-resolving-sub-domain-local/m-p/1598354)
- exo's troubleshooting: "guest Wi-Fi and some office networks stop devices from seeing each other: try Ethernet or a Thunderbolt cable instead." Its discovery namespace is version-scoped, so devices only connect if on the same exo version or the same custom name — [exo README](https://github.com/exo-explore/exo)
- LocalAI P2P offers `LOCALAI_P2P_DISABLE_DHT=true` for LAN-only mDNS discovery. It warns that listing a swarm on its public explorer publishes the token, so anyone can use the workers — [LocalAI distributed docs](https://localai.io/docs/features/distribute/)

**Security defaults of the components:**
- Ollama binds `127.0.0.1:11434` by default. Exposing it requires `OLLAMA_HOST=0.0.0.0:11434`, which has no auth — [Ollama FAQ](https://github.com/ollama/ollama/blob/main/docs/faq.mdx)
- llama.cpp RPC: "fragile and insecure. Never run the RPC server on an open network or in a sensitive environment!" — [llama.cpp RPC README](https://github.com/ggml-org/llama.cpp/blob/master/tools/rpc/README.md)
- Mindcraft warns that LLM-written code execution is vulnerable to injection and recommends Docker — [mindcraft](https://github.com/mindcraft-bots/mindcraft)

### Inferences
- **Service record:** `_swarmworld._tcp.local.`, with TXT keys `v=<protocol version>`, `world=<name>`, `auth=token`. Version-scope it like exo does so mismatched clients don't half-connect.
- **Security checklist (home LAN):**
  1. Model servers bind to localhost only; B-local never needs them on the LAN.
  2. The world server binds to the LAN interface only and requires a join token (printed on server start, or shown as a QR code). Use TLS optionally; a self-signed cert is fine on a LAN.
  3. No router port-forwarding and no UPnP.
  4. Agents get no shell or code execution; their actions are a closed schema validated server-side. This blocks prompt-injection between agents.
  5. On Windows, mark the network "Private" so the Defender firewall allows inbound mDNS and the app's socket. Allow-list Python or the node binary when prompted.
- If remote (non-LAN) machines ever need to join, an overlay VPN (Tailscale/WireGuard) is safer than exposure. That is outside this scope.

### Gaps
- No authoritative Microsoft doc was found on which Windows 10/11 builds natively resolve and advertise mDNS, or on default firewall behavior for UDP 5353 on Private vs. Public profiles. Test on the actual PC.
- Mesh Wi-Fi and router multicast filtering (IGMP snooping) behavior was not researched. It is a known source of mDNS flakiness, which is why a manual fallback is essential.

---

## Q4. Cross-platform local model servers per machine (Mac and the Windows/Linux PC with NVIDIA or AMD), and their concurrency behavior

### Takeaway
On Macs, use an engine with real continuous batching: oMLX (MLX, menu-bar app, continuous batching plus SSD KV cache) or llama.cpp `llama-server --parallel N`. On the PC, llama.cpp (CUDA, HIP, or the vendor-neutral Vulkan backend) or Ollama (CUDA, ROCm v7, Vulkan default-on) both work on Windows. vLLM is the high-throughput option only under Linux/WSL2 with NVIDIA. Engine choice matters as much as hardware. In an October 2026 M1 Max test, Ollama's aggregate throughput stayed flat around 54 tok/s under 8 concurrent requests, while llama-server reached 122 tok/s and an MLX engine 203 tok/s. The node script should speak the OpenAI-compatible API so any engine can plug in.

### Cited Findings
**Mac engines:**
- **oMLX** (jundot/omlx, 23k stars, v0.7.3 on 2026-10-31): "Continuous batching and tiered KV caching, managed directly from your menu bar." It handles concurrent requests through mlx-lm's BatchGenerator, with configurable max concurrency. Its block KV cache has a hot RAM tier and a cold SSD tier with prefix sharing, persisting across restarts. It serves an OpenAI-compatible API at `localhost:8000/v1` with multi-model serving and requires macOS 15+ on M1–M5. Source builds can also split a model across unequal-memory Macs (Ring) — [jundot/omlx](https://github.com/jundot/omlx)
- **mlx-lm** latest v0.32.2 (2026-10-16) — [ml-explore/mlx-lm](https://github.com/ml-explore/mlx-lm)
- **llama.cpp** (v0.8.0, 2026-10-28): "Apple silicon is a first-class citizen". Backends are Metal, CUDA, HIP (AMD), Vulkan, SYCL (Intel); Windows install via winget — [ggml-org/llama.cpp](https://github.com/ggml-org/llama.cpp)

**PC (Windows/Linux) engines:**
- **Ollama** (v0.40.13, 2026-10-28):
  - NVIDIA needs compute capability 5.0+ and driver 550+.
  - AMD via ROCm v7 on Linux covers a wide list (RX 6800 up to 9070 XT, PRO W-series). On Windows the ROCm list is narrower: RX 7600–7900 XTX and PRO W7500–W7900.
  - "Additional GPU support on Windows and Linux is provided via Vulkan… enabled by default"; on Windows "most GPU vendors drivers come bundled with Vulkan support". It can be disabled with `OLLAMA_VULKAN=0`.
  - Source: [Ollama GPU docs](https://github.com/ollama/ollama/blob/main/docs/gpu.mdx)
- **Ollama concurrency knobs:**
  - `OLLAMA_NUM_PARALLEL` (default 1), with "Required RAM will scale by `OLLAMA_NUM_PARALLEL` * `OLLAMA_CONTEXT_LENGTH`".
  - `OLLAMA_MAX_LOADED_MODELS` (default 3 x GPUs) and `OLLAMA_MAX_QUEUE` (default 512, then 503 errors).
  - KV cache quantization `OLLAMA_KV_CACHE_TYPE=q8_0` uses about half the memory of f16.
  - The FAQ notes that Windows + Radeon defaulted to 1 loaded model because of ROCm VRAM-reporting limits.
  - Source: [Ollama FAQ](https://github.com/ollama/ollama/blob/main/docs/faq.mdx)
- **vLLM:** GPUStack's v2 README lists vLLM, SGLang and TensorRT-LLM as its engines, with workers on Linux only and Windows via WSL2 — [gpustack/gpustack](https://github.com/gpustack/gpustack)

**Concurrency benchmark** (M1 Max 64 GB, Qwen3.5-9B, 2026-10-28; Ollama 0.40.11, llama.cpp 0.7.0 b11669, mlx-lm 0.32.2), aggregate tok/s at 2 / 4 / 8 concurrent requests:

| Engine | 2 | 4 | 8 | Other details |
|---|---|---|---|---|
| llama.cpp `--parallel 8` | 42.4 | 78.0 | 122.0 | 16.9 tok/s per request and 2.41 s TTFT at 8 |
| Ollama `OLLAMA_NUM_PARALLEL=8` (MLX NVFP4 backend) | 53.2 | 54.5 | 54.8 | TTFT 30 s at 8; the author reads this as "largely in sequence" |
| mlx-lm (8 slots) | 71.4 | 79.4 | 69.7 | |
| Locals (MLX) | 100.4 | 124.7 | 203.1 | |
| uzu | ~55 | ~55 | ~55 | flat, time-sliced |

Single-stream speed ranged from 36.6 (llama.cpp) to about 60 tok/s (Locals). Caveat: weights and settings differ per engine — [lilting.ch, 2026-10-28](https://lilting.ch/en/articles/m1-max-llm-engine-benchmark)

### Inferences
- **For the user's M1 Max with 32 GB:** start with oMLX or `llama-server --parallel 6–8` running a roughly 8–9B 4-bit model. Extrapolating the 64 GB benchmark, which used the same 400 GB/s-bandwidth chip, gives roughly 80–120 tok/s aggregate across 4–8 concurrent agents, at about 17–20 tok/s each. That is plenty for perhaps 10–25 agents if each acts every few seconds with short outputs. This is an estimate; 32 GB limits KV-cache headroom versus 64 GB.
- **Avoid relying on Ollama's MLX path for parallelism** until verified on the installed version. The flat-throughput result suggests requests are effectively serialized there. Ollama remains the easiest cross-platform installer, especially on the Windows PC, and its CUDA/llama.cpp path may batch differently. Benchmark it on join.
- **For the PC:** an NVIDIA card on Windows should use llama.cpp CUDA builds or Ollama. An AMD card on Windows should use Vulkan (llama.cpp or Ollama) unless it is an RX 7000-series card on the ROCm list. vLLM only makes sense if the PC runs Linux or WSL2 with NVIDIA, and it gives the best batched throughput there.
- **A thin "engine adapter" in the node script** (OpenAI `/v1/chat/completions` plus a capability probe) lets each machine use whichever engine runs best on it.

### Gaps
- No 2026 Windows benchmark was found comparing Ollama, llama.cpp CUDA and llama.cpp Vulkan concurrent throughput on consumer NVIDIA or AMD cards.
- The "Locals" engine (best M1 Max batching in that test) was not researched further: license, maturity, API.
- It is unverified whether the Ollama flat-concurrency result also holds for its GGUF/llama.cpp backend on Mac.

---

## Q5. Auto-sizing agents per machine: benchmark on join, pick the model by VRAM or unified memory

### Takeaway
Size in two stages. First, a static fit: usable accelerator memory picks the largest model tier that still leaves KV-cache room for P parallel slots. On a Mac, usable GPU memory is the wired limit, about 75% of RAM by default, so about 24 GB on a 32 GB M1 Max (estimate). Second, a dynamic calibration: a 20–60 s batched benchmark at concurrency 1/2/4/8 picks the largest P that keeps per-request tok/s above a target. Agents assigned is then about P x an oversubscription factor. Existing tools help: llmfit for model fit, `llama-batched-bench` for aggregate throughput, and GPUStack's "Auto Tune" as a conceptual model.

### Cited Findings
- **macOS GPU memory cap:** `sysctl iogpu.wired_limit_mb`, where 0 means the system default, which several guides put at about 75% of RAM. A 64 GB M1 Max user measured a default of 49152 MB (75%). No measured 32 GB default was found; 24576 MB is the 75% extrapolation. The limit can be raised manually and resets on reboot — [r/LocalLLaMA comment, 2023](https://axebps-redlib.hf.space/r/LocalLLaMA/comments/186phti/m1m2m3_increase_vram_allocation_with_sudo_sysctl/kbbt8oy/?context=3); [contracollective blog, 2026](https://contracollective.com/blog/mac-unified-memory-wired-limit-gpu-large-local-llm-2026); [llmconfigurator guide](https://llmconfigurator.com/en/guides/troubleshooting/increase-metal-vram-limit-apple-silicon)
- **llmfit** (AlexsJones/llmfit, 38.5k stars, pushed 2026-10-30): "Hundreds of models & providers. One command to find what runs on your hardware." — [AlexsJones/llmfit](https://github.com/AlexsJones/llmfit)
- **`llama-batched-bench`** benchmarks batched decoding, with parallel levels set by `-npl 1,2,4,8,16,32`, in shared-prompt and per-batch-prompt modes — [batched-bench README (mirror of upstream llama.cpp tools/batched-bench)](https://huggingface.co/kaisser/LLM-Maroc/blob/main/llama.cpp/tools/batched-bench/README.md)
- **GPUStack "Auto Tune"** "adaptively adjusts load to uncover peak throughput or find the highest concurrency that meets your service-level objectives (SLOs)" — [gpustack/gpustack](https://github.com/gpustack/gpustack)
- **Ollama memory scaling:** RAM scales by `NUM_PARALLEL x CONTEXT_LENGTH`. `ollama ps` shows the CPU/GPU split ("48%/52% CPU/GPU" means a partial offload, which you want to avoid). q8_0 KV cache roughly halves KV memory — [Ollama FAQ](https://github.com/ollama/ollama/blob/main/docs/faq.mdx)
- **Paddler** models capacity explicitly as `--slots N` per agent, and its slots keep their own context and KV cache — [intentee/paddler](https://github.com/intentee/paddler)
- **Per-request speed degrades as concurrency rises** (llama.cpp on M1 Max: 21.8 → 20.7 → 16.9 tok/s per request at 2/4/8), which is the curve the calibration should sample — [lilting.ch](https://lilting.ch/en/articles/m1-max-llm-engine-benchmark)

### Inferences
**Proposed auto-size algorithm (estimates, to tune):**
1. **Usable memory:**
   - On a Mac, `usable = iogpu.wired_limit_mb` (or 0.75 x `hw.memsize` if unset), minus about 4 GB headroom for the OS and apps, more on a laptop someone is actively using.
   - On NVIDIA, use `nvidia-smi --query-gpu=memory.total,memory.used`.
   - On AMD, use `rocm-smi`, or the Vulkan device memory reported by the engine.
2. **Model tier table** (4-bit weights, about 0.55–0.6 GB per billion params plus KV):
   - under 8 GB usable: 1–4B (Qwen 3B/4B-class)
   - 8–16 GB: 7–9B
   - 16–24 GB: 12–14B, or 9B with many slots
   - over 24 GB: 27–32B, or a mid MoE
   - The M1 Max 32 GB (about 20–24 GB usable) fits 9B with 8 slots comfortably, or 14B with 4 slots.
3. **KV budget:** `slots x ctx x per-token-KV`. Agent prompts should be kept to about 2–4K tokens through summarized memory, so 8 slots stay cheap. Use q8_0 KV where supported.
4. **Calibration:** with a fixed agent-like prompt (about 1.5K in, 150 out), measure aggregate and per-request tok/s at P = 1, 2, 4, 8 (and 16 if memory allows). Choose the largest P with per-request tok/s at or above the target (for example 12–15 tok/s) and TTFT under about 3 s.
5. **Agents to request** = P x k, with k about 2–3, since agents are not always generating. Report `slots`, `tok_s`, `model_id` and `tier` to the world server, which may assign "role-appropriate" agents (complex roles to bigger models).
6. **Re-calibrate periodically** or when the laptop moves from power to battery. On macOS use `caffeinate` to prevent sleep while joined, and drop P when the user is active or on battery.

### Gaps
- No published empirical rule was found for the agent-to-slot oversubscription ratio in LLM agent simulations; k = 2–3 is a guess.
- No measured `iogpu.wired_limit_mb` default for a 32 GB M1 Max; verify on the machine with `sysctl iogpu.wired_limit_mb`.
- llmfit's internals (how it estimates fit and speed, whether it has a machine-readable output for scripting) were not examined.

---

## Q6. Inference-pooling routers (secondary): LiteLLM, Olla, Paddler, GPUStack, LocalAI P2P/federated, llm-d, Ollama proxies, and heterogeneous Mac + NVIDIA + AMD support

### Takeaway
If a central router is wanted later (for example a shared "big-brain" model on the PC that any agent can call), the realistic choices are LiteLLM (mature, many routing strategies, cooldowns) or Olla (lightweight Go proxy with health checks, circuit breakers and native oMLX/Ollama/llama.cpp/vLLM support, but very new: v0.1.0 on 2026-11-01). Both treat each machine's existing server as a backend, so they are fully heterogeneous. Paddler is attractive for the LAN join UX, but its latest release ships only Linux x64 and macOS ARM binaries. Current GPUStack v2 is a poor fit: Linux-only workers, with macOS workers no longer supported. LocalAI P2P is still "tech preview". llm-d is Kubernetes-only.

### Cited Findings
- **LiteLLM** (62k stars, v1.106.6 on 2026-10-28; describes itself as a "Rust core with Python SDK" AI gateway with load balancing):
  - Strategies: `simple-shuffle` (default; weighted by rpm/tpm/weight), `least-busy` (fewest ongoing calls), `latency-based-routing`, `usage-based-routing(-v2)` (Redis), `cost-based-routing`, and custom.
  - Multiple deployments under one `model_name` are load-balanced.
  - Per-deployment cooldowns trigger on 429, more than 50% failures per minute, or 401/404/408 (default 5 s), with `num_retries`, `order`-based fallbacks, and immediate 429 when over `max_parallel_requests`.
  - Sources: [LiteLLM routing docs](https://docs.litellm.ai/docs/routing); [BerriAI/litellm](https://github.com/BerriAI/litellm)
- **Olla** (thushan/olla, 321 stars, v0.1.0 on 2026-11-01):
  - Priority-based load balancing with automatic failover, continuous endpoint health checks with circuit breakers, self-healing model discovery, unified model catalogue, and Anthropic Messages passthrough or translation.
  - Natively supports Ollama, LM Studio, vLLM, vLLM-MLX, llama.cpp and oMLX.
  - It is positioned as working "alongside" LiteLLM or GPUStack.
  - Source: [thushan/olla](https://github.com/thushan/olla)
- **Paddler** (1.7k stars, v4.1.0 on 2026-07-19):
  - A balancer plus agents with slots, a built-in llama.cpp engine with its own slot/KV implementation, request buffering ("scaling from zero hosts"), and a desktop GUI for "multiple laptops and PCs in a local AI cluster".
  - Release assets are only `linux-amd64` and `macos-arm`; there is no Windows binary.
  - Sources: [intentee/paddler](https://github.com/intentee/paddler); [Paddler releases](https://github.com/intentee/paddler/releases)
- **GPUStack v2** (6k stars, v2.3.0 on 2026-10-23):
  - "Only Linux is supported for GPUStack worker nodes. If you use Windows, consider using WSL2… macOS is not supported for GPUStack worker nodes."
  - Engines are vLLM, SGLang and TensorRT-LLM. Accelerators include NVIDIA, AMD, Ascend and others.
  - It offers load balancing, failure recovery, Prometheus/Grafana, and Auto Tune.
  - Source: [gpustack/gpustack](https://github.com/gpustack/gpustack)
  - **CONFLICT/STALE:** 2024–2025 launch posts and third-party guides say GPUStack supports Apple Macs (llama.cpp on Mac, vLLM on NVIDIA) — [GPUStack launch post](https://medium.com/@gpustack.ai/introducing-gpustack-an-open-source-gpu-cluster-manager-for-running-llms-0f0a3cb104a7); [localaimaster guide](https://localaimaster.com/blog/gpustack-setup-guide). Mac-worker issues existed in 2025 — [gpustack #2451](https://github.com/gpustack/gpustack/issues/2451). The current README says macOS workers are not supported.
- **LocalAI** (50k stars, v4.12.1 on 2026-10-23):
  - P2P has two modes. In federated mode, requests are routed "to a single worker node… based on the load balancer's decision", and each node loads the full model. In worker mode, llama.cpp RPC shards weights proportional to memory.
  - Discovery is libp2p/EdgeVPN with a token; `LOCALAI_P2P_DISABLE_DHT=true` makes it LAN-only.
  - Caveats: "tech preview quality", single model only, workers can't be added once inference starts, containers need host networking.
  - The docs' architecture text is internally inconsistent about whether federated requests are split.
  - A separate "Distributed Mode" (PostgreSQL + NATS) added VRAM-aware routing in April 2026 (4.1.0).
  - Sources: [LocalAI distributed docs](https://localai.io/docs/features/distribute/); [mudler/LocalAI](https://github.com/mudler/LocalAI)
- **llm-d** (v1.0.0 on 2026-10-20): "State of the art inference performance with modern accelerators on Kubernetes" — [llm-d/llm-d](https://github.com/llm-d/llm-d)
- **Ollama proxies:** "ollama_proxy_server" is now ParisNeo/lollms_hub ("A proxy server for multiple ollama instances with Key security", v9.0.0 2025-10-31, last push 2026-04) — [ParisNeo/lollms_hub](https://github.com/ParisNeo/lollms_hub). OLOL (K2/olol, 49 stars) was last pushed 2025-08-08, which is stale — [K2/olol](https://github.com/K2/olol)

### Inferences
- **For this project, a router is optional.** The natural place for one, if used, is on the world-server host. Nodes would opt in to exposing their model server to the router, behind the router's auth and on the LAN only. Roles flagged "needs big model" then route to the strongest backend, while normal agents use their own node's local model.
- **LiteLLM `least-busy`** is the right strategy for heterogeneous backends with different speeds. `latency-based-routing` also works, but per-call latency varies a lot with output length.
- **Avoid GPUStack** unless the PC runs Linux and Macs are excluded. Avoid LocalAI P2P for production use until it leaves tech preview. Both are fine to experiment with.

### Gaps
- Olla's maturity and production use: it is a v0.1.0 project, and no independent reviews were found.
- Whether Paddler has an unofficial Windows build path, or plans one, was not checked.
- LiteLLM's "Health Check Routing" page (active health probes) was not fetched.

---

## Q7. Footnote: model-sharding tools (exo, llama.cpp RPC, MLX distributed, distributed-llama, Petals), only for "one model bigger than a single machine"

### Takeaway
exo is the most polished option for Macs: auto-discovery, a multi-protocol API, and tensor parallelism. But it is Mac-centric (Linux runs on CPU only, there is no Windows build, and RDMA needs Thunderbolt 5 Macs on macOS 26.2+), and it is oriented to fitting big models, with open concurrency deadlock issues. llama.cpp RPC is the only practical way to mix a Mac with an NVIDIA or AMD PC in one model, at a significant decode penalty and with no security. Petals is dormant. For this project, keep sharding out of the core design.

### Cited Findings
- **exo** (48k stars; latest tagged release v1.0.71 on 2026-04-23, repo pushed 2026-11-01):
  - Features: automatic device discovery, "day-0 support for RDMA over Thunderbolt 5" ("99% reduction in latency", a project claim), and tensor parallelism with "up to 1.8x speedup on 2 devices and 3.2x speedup on 4 devices".
  - Backend: MLX plus MLX distributed.
  - APIs: OpenAI Chat Completions, Claude Messages, OpenAI Responses and Ollama, on port 52415.
  - The macOS app needs Sequoia 15.1+; RDMA needs Tahoe 26.2+.
  - The RDMA-capable list is TB5 Macs only: M4 Pro Mac mini, M4 Max Studio/MBP, M3 Ultra Studio.
  - RDMA requires all-to-all cabling, TB5 cables, `rdma_ctl enable` from Recovery, and exactly matching macOS versions.
  - "Currently, exo runs on CPU on Linux. GPU support for Linux platforms is under development" (`mlx-cuda12/13` extras exist in the install instructions). Windows is not mentioned.
  - Source: [exo README](https://github.com/exo-explore/exo)
- exo 1.0 launched Dec 2025 alongside macOS 26.2 RDMA — [Engadget](https://www.engadget.com/ai/you-can-turn-a-cluster-of-macs-into-an-ai-supercomputer-in-macos-tahoe-262-191500778.html); [Jeff Geerling](https://www.jeffgeerling.com/blog/2025/15-tb-vram-on-mac-studio-rdma-over-thunderbolt-5). Geerling called it prerelease ("When it works, it works great. When it doesn't…") and noted trust concerns because the developers "went AWOL for a while" — [Jeff Geerling](https://www.jeffgeerling.com/blog/2025/15-tb-vram-on-mac-studio-rdma-over-thunderbolt-5)
- **llama.cpp RPC:**
  - "proof-of-concept… fragile and insecure."
  - The `ggml-rpc-server` exposes CUDA, Metal and other devices.
  - By default it distributes weights and KV cache "in proportion to each device's available memory."
  - Source: [llama.cpp RPC README](https://github.com/ggml-org/llama.cpp/blob/master/tools/rpc/README.md)
- **LocalAI** credits exo for its MLX-distributed auto-parallel sharding and added MLX-distributed in 4.0.0 (Mar 2026) — [mudler/LocalAI](https://github.com/mudler/LocalAI)
- **oMLX** source builds can split a model across unequal-memory Macs (Ring) — [jundot/omlx](https://github.com/jundot/omlx)
- **distributed-llama** (3.1k stars, v0.16.5 on 2026-02-02, active): "Connect home devices into a powerful cluster to accelerate LLM inference" — [b4rtaz/distributed-llama](https://github.com/b4rtaz/distributed-llama)
- **Petals**: last release 2023-09, last push 2024-09, so dormant — [bigscience-workshop/petals](https://github.com/bigscience-workshop/petals)

### Inferences
- Only consider sharding if a single role needs a model above about 24 GB of usable memory and two or more machines are wired together (Ethernet at minimum, ideally TB5 Macs for exo RDMA). Even then, run it as one extra backend "brain" (an exo node exposes an OpenAI API) that the world or router calls, not as the swarm's foundation.
- For Mac + PC sharding, llama.cpp RPC over wired Ethernet is the only cross-vendor route. Expect a large decode penalty on dense models; MoE models are less penalized per the 2026 2x5090 post.

### Gaps
- No up-to-date (2026) Mac + NVIDIA llama.cpp RPC benchmark tables with full numbers were found.
- I could not verify whether exo's `mlx-cuda` extras deliver working NVIDIA GPU inference as of Nov 2026, since the README text contradicts itself (it lists CUDA extras but says Linux runs on CPU).
- distributed-llama's current backend and platform support (Apple GPU? CUDA? Windows?) were not checked.

---

## Q8. Mixed-model heterogeneity in the swarm: feature or problem? Research on heterogeneous LLM agent populations

### Takeaway
Mostly a feature. Recent work finds that model-diverse agent groups beat larger homogeneous groups on collective tasks, and that same-model populations collapse toward an "average persona" with too little behavioral variance. That is a recognized validity threat in LLM social simulation. The costs are engineering ones: capability gaps (small models break action formats or reason poorly), speed asymmetry (fast agents act more often), and reproducibility. These are handled with schema-constrained actions, time-budgeted turns, and logging which model drove which agent.

### Cited Findings
- **"Understanding Agent Scaling in LLM-Based Multi-Agent Systems via Diversity"** (arXiv 2602.03794, Feb 2026; listed at ICLR 2026):
  - Homogeneous agents saturate early because their outputs are correlated, while heterogeneous agents add complementary evidence.
  - "2 diverse agents can match or exceed the performance of 16 homogeneous agents."
  - Diversity sources: backbone model, persona/prompt, tools. The paper proposes a label-free "effective channel count" diversity metric.
  - Sources: [arXiv 2602.03794](https://arxiv.org/abs/2602.03794); [ICLR 2026 page](https://iclr.cc/virtual/2026/10018240)
- **X-MAS** (arXiv 2505.16997, May 2025): multi-agent systems with a different LLM per agent, benchmarked on 27 LLMs. "No single model excels universally," and heterogeneous systems gained up to 47% over homogeneous ones — [alphaXiv overview](https://www.alphaxiv.org/overview/2505.16997); [emergentmind](https://www.emergentmind.com/papers/2505.16997)
- **Belief coevolution** (arXiv 2607.27512, aggregator only): specialist LLMs "more than double" collective consensus shift versus persona-prompt-only diversity. The authors conclude that genuinely different models, not just persona labels, are needed for realistic belief exchange. Details unverified beyond the aggregator — [emergentmind 2607.27512](https://www.emergentmind.com/papers/2607.27512)
- **"LLM-Based Social Simulations Require a Boundary"** (Wu et al., arXiv 2506.19806; ICML 2026 position): LLMs tend toward an "average persona," and lack of heterogeneity is "not a solvable design flaw but a fundamental boundary" — [arXiv 2506.19806](https://arxiv.org/abs/2506.19806); [ICML 2026 poster](https://icml.cc/virtual/2026/poster/67234)
- **PIMMUR** (arXiv 2509.18052): an audit of 42 LLM social-simulation papers (2023–2025) lists homogeneity as a core validity threat. Agents sampled from one backbone can collapse into consensus that reflects model bias — [PIMMUR](https://arxiv.org/html/2509.18052v2)
- **"Are LLM Agents Behaviorally Coherent?"** (arXiv 2509.03736): significant internal inconsistencies across model families and sizes — [arXiv 2509.03736](https://arxiv.org/html/2509.03736v1)
- **Project Sid** reports emergent role specialization in 1000+ agent Minecraft societies (preliminary) — [arXiv 2411.00114](https://arxiv.org/abs/2411.00114)
- **Mindcraft** already supports per-bot model selection through profile JSON, so mixed-model populations are an existing practice in game-agent tooling — [mindcraft](https://github.com/mindcraft-bots/mindcraft)

### Inferences
- **Treat hardware heterogeneity as "species" or "temperament" diversity in-world.** The PC's big model drives deliberative leaders, scholars or traders; small Mac models drive quick, chatty villagers. Record `model_id` as a hidden agent attribute for analysis.
- **Mitigate the downsides:**
  1. Use a strict, small action schema with grammar/JSON-schema constrained decoding (llama.cpp grammars, or structured outputs where supported), so 3–4B models still produce valid actions. Have the server reject and re-prompt on invalid actions.
  2. Use time-budgeted turns, or action-point costs per unit of world time, so fast hardware doesn't let agents act disproportionately often (a fairness issue for simulation validity).
  3. Avoid letting agent identity hop between models mid-life, which causes personality discontinuity. Pin an agent to a model family, and prefer re-assigning it to a node with the same model when migrating.
  4. For experiments, log model, quantization, engine and seed per agent action.
- Persona prompting alone on one model is a weaker diversity source than mixing models (per 2602.03794 and 2607.27512). So the multi-machine setup is a scientific upside, not just a capacity one.

### Gaps
- No study was found specifically on mixed-model populations in persistent embodied sandbox worlds (as opposed to QA/reasoning tasks or opinion dynamics). The transfer of "diversity helps" to open-ended world sims is plausible but untested.
- A paper on networked cooperation games across nine open-weight LLMs, finding "markedly reduced variability" versus humans, surfaced in search but I could not pin its exact URL, so it is not cited above.
- The X-MAS and belief-coevolution findings were seen only through overview/aggregator pages, not the full papers.
