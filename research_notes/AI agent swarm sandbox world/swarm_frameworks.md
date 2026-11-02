# Multi-agent / "swarm" LLM frameworks: fit for many embodied agents in a simulated world on local models (as of 2026-11-01)

Scope: Can an existing framework run a home "AI swarm"? The setup is an M1 Max with 32 GB, local models behind an OpenAI-compatible server (oMLX, Ollama or llama.cpp), embodied agents with position, perception, proximity speech, crafting and scripts, and asynchronous ticks or events. Other machines on the LAN should be able to join later. The goal is emergence, not task automation.

Method note: Repo stars, last push dates, licenses, release tags and README claims were pulled live from the GitHub API on 2026-11-01 (`gh api repos/...`). A claim marked "(unverified this session)" comes from prior knowledge and was not re-checked here.

---

## 1. Framework survey: abstraction, concurrency, scale and memory, local models, license, activity

### Takeaway
Two groups emerge. The general-purpose agent frameworks (OpenAI Agents SDK, LangGraph, CrewAI, Microsoft Agent Framework, AG2, Agno, PydanticAI, smolagents, Google ADK, Strands, Claude Agent SDK, DSPy, Swarms) are all built around one request, one agent run, and tools. None of them models space, time, perception or proximity. Only a handful are built for simulation, and they differ a lot in fit:
- **Concordia**: a game-master pattern with an asynchronous engine, Ollama and vLLM adapters, and Apache-2.0.
- **Mesa + Mesa-LLM**: a grid ABM with LLM agents. It is pre-1.0 and has about 80 stars.
- **AgentSociety 2**: Ray-based and aimed at social science.
- **OASIS**: a social-media simulator, not a spatial world.
- **TinyTroupe**: persona focus groups, with Ollama support marked experimental.
- **AI Town**: a TypeScript/Convex starter kit with Ollama as the default.
- **Mindcraft**: Minecraft bots with Ollama and vLLM.

AgentScope's large-scale simulation features belong to v0.x only. Version 1.0 removed them.

### Cited Findings

**Live GitHub snapshot (2026-11-01; stars / last push / license):**
- OpenAI Agents SDK: 30,438 / 2026-11-01 / MIT; latest release v0.24.0 (2026-10-15) — [repo](https://github.com/openai/openai-agents-python)
- OpenAI Swarm: 22,092 / 2026-04-15 / MIT. The README says "Swarm is now replaced by the OpenAI Agents SDK… We recommend migrating to the Agents SDK for all production use cases." Treat it as stale. — [repo](https://github.com/openai/swarm)
- LangGraph: 44,285 / 2026-11-01 / MIT — [repo](https://github.com/langchain-ai/langgraph)
- CrewAI: 60,393 / 2026-11-01 / MIT — [repo](https://github.com/crewAIInc/crewAI)
- AutoGen (Microsoft): 61,663 / 2026-10-28. The README says "This project has been archived and is no longer actively maintained by Microsoft… New users should start with Microsoft Agent Framework" and "As AutoGen is in maintenance mode, contributions are limited to bug fixes, security patches…". The GitHub API still reports `archived: false`. Its README also says its Core API "implements message passing, event-driven agents, and local and distributed runtime". Treat it as stale/deprecated. — [repo](https://github.com/microsoft/autogen)
- Microsoft Agent Framework (MAF): 14,477 / 2026-11-01 / MIT; latest release python-1.24.0 (2026-10-30). It offers "graph-based workflows supporting sequential, concurrent, handoff, and group collaboration patterns; includes checkpointing", OpenTelemetry, and A2A hosting samples. The AutoGen README calls MAF 1.0 the "enterprise-ready successor to AutoGen". — [repo](https://github.com/microsoft/agent-framework); [AutoGen README](https://github.com/microsoft/autogen)
- AG2 (formerly AutoGen community fork): 5,039 / 2026-11-01 / Apache-2.0. "As of AG2 v1.0, the protocol-driven framework is the top-level package… The classic framework has moved to… ag2ai/ag2-classic". v1.0 "is not a drop-in upgrade". The README also lists an `ag2[ollama]` extra. — [repo](https://github.com/ag2ai/ag2)
- CAMEL: 18,007 / 2026-10-27 / Apache-2.0; has a cookbook for a "Customer Service Discord Bot with Local Model". — [repo](https://github.com/camel-ai/camel)
- OASIS (CAMEL): 5,373 / 2026-10-27 / Apache-2.0; latest release v0.2.5 (2025-12-04). It is "a scalable, open-source social media simulator… up to one million users on platforms like Twitter and Reddit", and it was refactored to "follow the PettingZoo style" (May 2025). — [repo](https://github.com/camel-ai/oasis)
- MetaGPT: 71,126 / last push **2026-01-21** / MIT. Config supports `api_type: "openai" # or azure / ollama / groq`. No push for about 9 months, so treat it as slowing or stale. — [repo](https://github.com/FoundationAgents/MetaGPT)
- Agno: 43,009 / 2026-11-01 / Apache-2.0. Now pitched as "the self-driving agent platform… Run agents as durable services on AgentOS". — [repo](https://github.com/agno-agi/agno)
- PydanticAI: 20,984 / 2026-11-01 / MIT. It describes a "typed, extensible agent loop with every model a string swap away" and supports durable execution via Temporal, DBOS and Prefect. — [repo](https://github.com/pydantic/pydantic-ai)
- smolagents (Hugging Face): 30,177 / 2026-10-29 / Apache-2.0. "CodeAgent writes its actions in code". It is "Model-agnostic… a local `transformers` or `ollama` model… any model from OpenAI", and it can pull tools from any MCP server. — [repo](https://github.com/huggingface/smolagents)
- Letta (MemGPT): 25,316 / 2026-10-18 / Apache-2.0. The description reads "Platform for stateful agents: AI with advanced memory that can learn and self-improve over time." — [repo](https://github.com/letta-ai/letta)
- DSPy: 38,878 / 2026-11-01 / MIT. The README says "The current LM integration uses bundled native lm15 engines, without a LiteLLM…". It is a prompt-programming and optimization library, not an agent runtime. — [repo](https://github.com/stanfordnlp/dspy)
- Google ADK (Python): 22,073 / 2026-11-01 / Apache-2.0. "While optimized for Gemini, ADK is model-agnostic, deployment-agnostic". — [repo](https://github.com/google/adk-python)
- Claude Agent SDK (Python): 8,402 / 2026-10-31 / MIT. "The Claude Code CLI is automatically bundled with the package". By default the agent gets the full Claude Code toolset (Read, Write, Edit, Bash). It targets Claude models, so it does not fit a local-model setup. — [repo](https://github.com/anthropics/claude-agent-sdk-python)
- Strands (AWS), **renamed `strands-agents/harness-sdk`**: 9,023 / 2026-10-30 / Apache-2.0. It is "Model agnostic", and its quickstart covers "Amazon Bedrock, Anthropic, OpenAI, Gemini, Ollama, and more". — [repo](https://github.com/strands-agents/harness-sdk)
- Swarms (kyegomez): 7,341 / 2026-11-01 / Apache-2.0. The README markets "The Enterprise-Grade Multi-Agent Orchestration Framework" and "infrastructure for deploying and orchestrating millions of agents". These are marketing claims; I found no independent benchmark. — [repo](https://github.com/kyegomez/swarms)
- Mesa (now under the `mesa` org): 3,932 / 2026-10-29 / Apache-2.0 — [repo](https://github.com/mesa/mesa)
- Mesa-LLM: **81 stars** / 2026-10-11 / Apache-2.0; latest release v0.3.2 (2026-04-26). The README warns "currently under active development. The API and functionality may change significantly". Listed providers include Ollama and OpenRouter. Modules include `reasoning/` (cot, react, rewoo), `memory/` (st_memory, lt_memory, st_lt_memory, episodic_memory), and `parallel_stepping.py`, which runs asyncio or threading via `astep()`. — [repo](https://github.com/mesa/mesa-llm)
- Concordia (DeepMind): 1,848 / 2026-11-01 / Apache-2.0; latest release v2.4.0 (2026-03-06). — [repo](https://github.com/google-deepmind/concordia)
- AgentScope: 35,123 / 2026-10-30 / Apache-2.0; latest release v2.0.11 (2026-10-27); "AgentScope 2.0 released!" in 2026-05. — [repo](https://github.com/agentscope-ai/agentscope); [NEWS](https://github.com/agentscope-ai/agentscope/blob/main/docs/NEWS.md)
- AgentSociety: 1,379 / 2026-10-30 / Apache-2.0; latest release agentsociety2-v2.9.3 (2026-09-24) — [repo](https://github.com/tsinghua-fib-lab/AgentSociety)
- TinyTroupe (Microsoft): 7,631 / 2026-10-23 / MIT — [repo](https://github.com/microsoft/TinyTroupe)
- Stanford Generative Agents: 22,323 / last push **2024-08-05**. Stale; useful only as reference code. — [repo](https://github.com/joonspk-research/generative_agents)
- a16z AI Town: 10,733 / 2026-08-26 / MIT — [repo](https://github.com/a16z-infra/ai-town)
- Project Sid (Altera): 1,389 / 2024-11-04 / no license. The repo holds only the paper. — [repo](https://github.com/altera-al/project-sid)
- Voyager: 7,306 / **2024-04-03** / MIT. Stale reference. — [repo](https://github.com/MineDojo/Voyager)
- Mindcraft (now `mindcraft-bots/mindcraft`): 5,953 / 2026-10-27 / MIT — [repo](https://github.com/mindcraft-bots/mindcraft)
- AgentVerse (OpenBMB): 5,167 / last push **2024-09-09**. Stale. — [repo](https://github.com/OpenBMB/AgentVerse)
- Sotopia: 341 / 2026-06-05 / MIT — [repo](https://github.com/sotopia-lab/sotopia)
- AgentTorch ("large population models"): 657 / 2026-09-12 / **AGPL-3.0** — [repo](https://github.com/AgentTorch/AgentTorch)
- YuLan-OneSim: 246 / 2026-02-02 / Apache-2.0 — [repo](https://github.com/RUC-GSAI/YuLan-OneSim)
- OpenAgents ("collaboration OS for AI agents"): 4,304 / 2026-11-01 / Apache-2.0 — [repo](https://github.com/openagents-org/openagents)
- Mastra (TypeScript): 29,259 / 2026-11-01 / license NOASSERTION — [repo](https://github.com/mastra-ai/mastra)
- BeeAI framework: 3,448 / 2026-11-01 / Apache-2.0 — [repo](https://github.com/i-am-bee/beeai-framework)
- Mem0 (memory layer): 68,239 / 2026-10-30 / Apache-2.0 — [repo](https://github.com/mem0ai/mem0)

**Core abstractions and local-model support (from READMEs):**
- OpenAI Agents SDK: "a lightweight yet powerful framework for building multi-agent workflows. It is provider-agnostic, supporting the OpenAI Responses and Chat Completions APIs, as well as 100+ other LLMs", via any-llm and LiteLLM. — [README](https://github.com/openai/openai-agents-python)
- LangGraph: "Durable execution — Build agents that persist through failures and can run for extended periods, automatically resuming". It is graph and state-machine centric and paired with LangSmith observability. — [README](https://github.com/langchain-ai/langgraph)
- CrewAI: role-playing "crews" plus "Flows: Production-ready, event-driven workflows". It is positioned as "production-ready agentic automation". — [README](https://github.com/crewAIInc/crewAI)
- AgentScope 2.0: its building blocks are a ReAct loop with "batched (sequential / concurrent) tool acting", a Toolkit (Python tools, MCP servers, skills), a model layer including **Ollama**, an "Event System… unified event bus", Memory (ReMe, Mem0 backends), and sandboxes (local, Docker, Apple Container…). The 2026-09 news adds "A2A protocol supported — chat with any remote A2A agent via `A2AAgent`". 2.0 is pitched as "a production-ready, easy-to-use agent framework", and simulation is no longer the focus. — [README](https://github.com/agentscope-ai/agentscope)
- **AgentScope's large-scale simulation and distributed mode are v0.x only.** The v0.1.7 source tree (2025-08-13) contains `rpc/` and `server/` modules. The v1.0.0 tree (released 2025-08-15) has no `rpc` or `server`, and neither does current main. Main has an `app/` package whose message bus "owns the distributed lock" for service deployment. Verified via `gh api repos/agentscope-ai/agentscope/contents/src/agentscope?ref=...` — [v0.1.7 tree](https://github.com/agentscope-ai/agentscope/tree/v0.1.7/src/agentscope); [v1.0.0 tree](https://github.com/agentscope-ai/agentscope/tree/v1.0.0/src/agentscope)
- AgentScope v0 docs: "AgentScope natively provides a distributed mode based on gRPC". Calling `to_dist()` turns an agent into an actor: "Each Agent is an Actor and interacts with other Agents through messages". — [v0 distribution docs](https://doc.agentscope.io/v0/en/_sources/build_tutorial/distribution.rst.txt); [paper: Very Large-Scale Multi-Agent Simulation in AgentScope](https://arxiv.org/html/2407.17789v2)
- Concordia: it "uses an interaction pattern inspired by tabletop role-playing games: a special entity called the Game Master (GM) simulates the environment… Entities describe their intended actions in natural language, and the GM translates these into appropriate outcomes e.g. checking physical plausibility". Entities are built from **components** ("instructions, memory and action selection"). **Prefabs** are prebuilt templates. The **engine** "requests player entity actions and asks game master entities to provide observations and resolve those actions". Engines in `concordia/environment/engines/` are `sequential.py`, `simultaneous.py` and `asynchronous.py`. — [README](https://github.com/google-deepmind/concordia)
- Concordia asynchronous engine docstring: "Fully asynchronous engine. Each player entity runs its own independent observe-act loop concurrently… The game master and its components must be thread-safe." It is thread-based (`import threading`). — [asynchronous.py](https://github.com/google-deepmind/concordia/blob/main/concordia/environment/engines/asynchronous.py)
- Concordia's LLM interface has only two methods: `sample_text(prompt, ...)` and `sample_choice(prompt, responses, ...)`. It does **not** depend on native tool calling. Wrappers include retry, call-limit and profiling. The contrib adapters are amazon, google, groq, huggingface, langchain, mistral, **ollama**, openai, together and **vllm**. — [LM README](https://github.com/google-deepmind/concordia/tree/main/concordia/language_model); [contrib/language_models](https://github.com/google-deepmind/concordia/tree/main/concordia/contrib/language_models)
- Concordia papers: the original tech report (Vezhnevets et al., arXiv 2312.03664, Dec 2023) says agents act via "a component system that alternates between LLM calls and associative memory retrieval", and the GM can call external tools. There is also a later "Concordia Design Pattern" paper. — [arXiv 2312.03664](https://arxiv.org/abs/2312.03664); [Design Pattern arXiv 2507.08892](https://arxiv.org/abs/2507.08892)
- AgentSociety 2: "LLM-native agent simulation platform designed for social science research". Reasoning patterns are "CodeGen (default), ReAct, Plan-Execute, Two-Tier, and Search routers". For "Scalable Execution", "Agents are workspace-bound stateless records driven by Ray Tasks". It also has "MCP Support". AgentSociety 1.x is "City-scale simulation with Ray distributed computing" with gRPC environment integration. — [README](https://github.com/tsinghua-fib-lab/AgentSociety)
- TinyTroupe: "developed primarily with OpenAI models and compatible endpoints in mind". A release "Adds experimental/limited Ollama support for local models". `TinyPersonFactory` generates populations in parallel. — [README](https://github.com/microsoft/TinyTroupe)
- AI Town: "By default, the app tries to use Ollama to run it entirely locally" (llama3). The backend is Convex. — [README](https://github.com/a16z-infra/ai-town)
- AI Town architecture, as summarized in a third-party landscape doc: a tick-based engine (60 ticks/sec, batched into 1 step/sec) with a "Single-threaded engine invariant" via generation numbers, and "Separate agent tables for async LLM calls (not blocking simulation loop)". This is secondary; the primary source is ARCHITECTURE.md in the repo. — [agent-valley landscape (2026-07-27)](https://github.com/emergencescience/agent-valley/blob/master/docs/research/llm-simulation-landscape.md)
- Mindcraft: "Minecraft AI with LLMs+Mineflayer". It supports `ollama` (local) and `vllm`: "For local models we support ollama and we provide our own finetuned models" (`sweaterdog/andy-4:micro-q8_0`, plus `embeddinggemma` for embeddings). — [README](https://github.com/mindcraft-bots/mindcraft)
- OASIS powers MiroFish, a commercial "predict anything" simulator that "Supports any OpenAI-compatible API" and uses Zep Cloud for memory. This comes from a secondary landscape doc. — [agent-valley landscape](https://github.com/emergencescience/agent-valley/blob/master/docs/research/llm-simulation-landscape.md)

**Structured output and tool calling with small local models:**
- Docker's evaluation covered 21 models and 3,570 tests. Qwen3 14B reached a tool-calling F1 of 0.971 (with high latency), and Qwen3 8B reached 0.933 at about half the latency. One quantized 8B model scored 0.484 on tool selection. Docker concluded the Qwen family leads open-source tool calling. — [Docker blog](https://www.docker.com/blog/local-llm-tool-calling-a-practical-evaluation/)
- A practitioner test of 7 Ollama models found the qwen3/qwen2.5 boundary predicted tool-calling success better than parameter count: all qwen2.5 models failed a simple read-then-edit task. — [dev.to](https://dev.to/kuroko1t/what-happens-when-local-llms-fail-at-tool-calling-testing-7-models-with-a-rust-coding-agent-cep)
- A blog-level report says multi-turn tool chaining is the hardest test ("almost nobody passes it"), many models ignore `tool_choice: required`, and one team chose prompt-based tool calling over Ollama's native API. These are secondary and anecdotal. — [ToolCall-15 blog](https://openagent-bot.pages.dev/blog/local-llm-tool-calling-benchmark-toolcall-15); [nativemind](https://nativemind.app/blog/ai-agent/)

### Inferences
- **Every general-purpose framework assumes a task-request lifecycle**: user message, then an agent or graph run, then tool calls, then a final answer. None has built-in concepts of world clock, position, perception radius, audibility or asynchronous wake-up on events. For an embodied simulation, all of that would sit outside the framework anyway. What the framework would actually provide is the LLM-call-plus-tool-dispatch loop, which takes about 50–150 lines of code to write directly.
- LangGraph, PydanticAI, Agno and MAF offer durability and checkpointing for long-running *workflows*. A simulation needs persistence of *world state plus per-agent memory*, which is better handled by a world-owned database such as SQLite or DuckDB.
- Concordia's two-method LLM interface (`sample_text` / `sample_choice`) is unusually friendly to small local models. A multiple-choice action selection can be constrained without relying on native tool calling, which small models do unreliably (per the Docker and dev.to findings).
- The Claude Agent SDK and Google ADK lean toward their vendors' cloud models. Claude Agent SDK bundles the Claude Code CLI and is effectively Claude-only, so it is negative for a local-only Mac setup. ADK says it is model-agnostic.
- For the general frameworks, per-call overhead on a local model is negligible compared with LLM latency. The real costs are prompt bloat (long framework system prompts and tool schemas) and abstraction that hides prompts. Both hurt small models more than large ones. I did not measure prompt sizes; this is inferred.
- Letta: stateful agents server with memory blocks and archival memory. It runs as a separate server with a REST API and supports Ollama and OpenAI-compatible backends (unverified this session; the README was only 1.4 KB). Running hundreds of Letta agents means hundreds of server-side agents with self-editing memory calls. That multiplies LLM calls per step, which is costly on one Mac.
- CrewAI, MetaGPT and CAMEL role-playing are conversation-centric team-workflow designs ("crew completes task"). They do not suit open-ended, physically situated emergence.
- Swarms markets "millions of agents", but its README shows orchestration patterns (sequential, hierarchical and others), not simulation. Treat the claim as marketing.

### Gaps
- Not verified this session: Letta's current Ollama and OpenAI-compatible support details, MAF's local-model connectors, Agno's and CrewAI's local-model paths (CrewAI historically used LiteLLM), and whether OASIS works smoothly with vLLM or Ollama today.
- No benchmarks found on framework overhead (prompt tokens added per call) for any of these frameworks with small models.
- No source evaluated grammar-constrained or JSON-schema structured outputs on Ollama, llama.cpp or MLX for agent action selection at scale.
- Swarms (kyegomez): found no independent technical evaluation.

---

## 2. Distributed agents across machines

### Takeaway
Few current frameworks offer built-in cross-machine agent distribution suited to a home LAN:
- **AgentScope**: the gRPC actor mode existed only in v0.x and was removed in 1.0 (Aug 2025).
- **AutoGen Core**: its distributed runtime is now archived.
- **AgentSociety**: built on Ray (Ray Tasks in v2, Ray-based city simulation in v1.x). It can scale out, but it is heavy, opinionated and research-oriented.
- **Concordia and Mesa-LLM**: single-process; Concordia uses threads, Mesa-LLM uses asyncio or threads.

The practical route for a home LAN is a custom world server that owns state, with agent "brain" processes on any machine connecting over a simple message transport. Each machine calls its own local model server.

### Cited Findings
- AgentScope v0.x: "natively provides a distributed mode based on gRPC"; `to_dist()`; "Each Agent is an Actor". — [v0 docs](https://doc.agentscope.io/v0/en/_sources/build_tutorial/distribution.rst.txt); [arXiv 2407.17789](https://arxiv.org/html/2407.17789v2)
- AgentScope removed the `rpc/` and `server/` modules between v0.1.7 (2025-08-13) and v1.0.0 (2025-08-15). Current 2.0 has a service-level message bus with distributed locks, plus A2A client support. — [v0.1.7 tree](https://github.com/agentscope-ai/agentscope/tree/v0.1.7/src/agentscope); [v1.0.0 tree](https://github.com/agentscope-ai/agentscope/tree/v1.0.0/src/agentscope); [README](https://github.com/agentscope-ai/agentscope)
- AutoGen Core had a "local and distributed runtime", but the repo is now archived or in maintenance mode. — [AutoGen README](https://github.com/microsoft/autogen)
- AgentSociety 2 drives agents as "stateless records… by Ray Tasks"; 1.x has "City-scale simulation with Ray distributed computing". — [README](https://github.com/tsinghua-fib-lab/AgentSociety)
- Ray is "an AI compute engine… a core distributed runtime" (44,174 stars, Apache-2.0, active as of 2026-11-01). — [repo](https://github.com/ray-project/ray)
- Concordia's asynchronous engine is thread-based within one process: "Each player entity runs its own independent observe-act loop concurrently… The game master… must be thread-safe." — [asynchronous.py](https://github.com/google-deepmind/concordia/blob/main/concordia/environment/engines/asynchronous.py)
- Mesa-LLM's parallel stepping uses `asyncio` or `threading` modes in-process. — [parallel_stepping.py](https://github.com/mesa/mesa-llm/blob/main/mesa_llm/parallel_stepping.py)
- MAF lists "Durable Task and Azure Functions samples" in a "Durable Agent Framework extension", which is a cloud-oriented route to distribution. It also lists A2A hosting. — [MAF README](https://github.com/microsoft/agent-framework)
- Project Sid ran up to 500 agents on a Minecraft server. Runs of 1000+ agents "exceeded the computational constraints of our Minecraft server environment, causing agents to be sporadically unresponsive". — [arXiv 2411.00114](https://arxiv.org/html/2411.00114)
- A16z AI Town keeps LLM calls in separate async agent tables, outside the single-threaded engine loop (secondary summary). — [agent-valley landscape](https://github.com/emergencescience/agent-valley/blob/master/docs/research/llm-simulation-landscape.md)

### Inferences
- For this use case, put the distribution seam between the **authoritative world server**, which handles ticks, physics, crafting, perception filtering and audibility, and **agent brain clients**, each of which sends `observe -> decide -> intent` over WebSocket, gRPC, ZeroMQ, NATS or Redis Streams. This is the classic MMO and game-server pattern; Project Sid (Minecraft server plus bot clients) and Mindcraft (Mineflayer clients) follow it implicitly. Another house computer then joins by running more brain clients against its own model server. No agent framework is required for this.
- Ray is overkill for a handful of home machines unless you already use it. Its value is cluster scheduling, which is not the bottleneck here; local LLM throughput is.
- Do not build on AgentScope's old distributed mode: it is frozen in v0.1.x.

### Gaps
- Did not verify whether AgentSociety 2 runs well on macOS or Apple Silicon, or with a local OpenAI-compatible endpoint.
- No source found for a home or LAN-scale multi-machine LLM agent simulation write-up.

---

## 3. Architectural patterns for embodied simulation agents, and which frameworks implement them

### Takeaway
The proven patterns are:
- A memory stream with retrieval scored on recency, importance and relevance, plus reflection and hierarchical planning (Generative Agents).
- A game master that resolves free-text intents against world rules (Concordia).
- Concurrent modules at different speeds with a bottlenecked cognitive controller (Project Sid's PIANO).
- A skill library of executable code (Voyager).
- Async LLM calls kept off the simulation tick loop (AI Town).

Only Concordia (the GM, components, associative memory, async engine) and Mesa-LLM (CoT, ReAct, ReWOO reasoning; short-, long-term and episodic memory) package some of these. PIANO-style concurrency, fast/slow split controllers, perception filtering by distance, and proximity speech all require custom code in every framework.

### Cited Findings
- **Generative Agents (Park et al. 2023)**: a memory stream (complete natural-language record), retrieval scored by recency, relevance and importance, periodic reflection into higher-level inferences, hierarchical planning (day, hour, minute), and reaction. 25 agents in a Sims-like sandbox. — [arXiv 2304.03442](https://arxiv.org/abs/2304.03442); summarized in [agent-valley landscape](https://github.com/emergencescience/agent-valley/blob/master/docs/research/llm-simulation-landscape.md)
- **Project Sid / PIANO** ("Parallel Information Aggregation via Neural Orchestration"; the architecture section says "Parallel Input Aggregation", an inconsistency inside the paper):
  - "10 distinct modules running concurrently", including Memory, Action Awareness, Goal Generation, Social Awareness, Talking and Skill Execution.
  - Modules run at different time scales. Reflex modules use "small, fast non-LLM neural networks", while goal generation reasons over graphs more slowly. Social modules engage only during interactions.
  - A **Cognitive Controller** is "solely responsible for making high-level deliberate decisions". It receives information through a bottleneck and broadcasts decisions to other modules, which conditions talking modules toward speech-action coherence.
  - The paper notes that one LLM call producing all outputs "does not scale when the number of outputs becomes large".
  - Experiments used 25–500 agents in Minecraft. GPT-4o is mentioned; the paper reports no latency or cost figures.
  - [arXiv 2411.00114 (HTML)](https://arxiv.org/html/2411.00114)
- **Concordia GM pattern**: entities describe intended actions in natural language, and the GM checks physical plausibility and resolves outcomes. Agents are built from components (memory, sensory modules, action selection). Engines support turn-taking, simultaneous and asynchronous action. — [README](https://github.com/google-deepmind/concordia); [arXiv 2312.03664](https://arxiv.org/abs/2312.03664)
- **Voyager**: an "ever-growing skill library of executable code for storing and retrieving complex behaviors"; skills transfer to new Minecraft worlds. The repo is stale (last push 2024-04). — [README](https://github.com/MineDojo/Voyager)
- **Code-as-action today**: smolagents' `CodeAgent` "writes its actions in code"; AgentSociety 2's default reasoning pattern is "CodeGen". — [smolagents](https://github.com/huggingface/smolagents); [AgentSociety](https://github.com/tsinghua-fib-lab/AgentSociety)
- **Mesa-LLM** ships reasoning modules (CoT, ReAct, ReWOO) and memory modules (short-term, long-term, combined short/long, episodic) on top of Mesa's grid and space ABM. — [mesa-llm repo tree](https://github.com/mesa/mesa-llm/tree/main/mesa_llm)
- **Mindcraft** splits LLM deliberation from Mineflayer's programmatic low-level control (pathfinding, mining) and lets the LLM write and run code. This is a working, actively maintained fast/slow split with local Ollama models. — [README](https://github.com/mindcraft-bots/mindcraft)
- **AI Town** pairs a tick-based engine with LLM calls that run asynchronously outside the loop (secondary summary of ARCHITECTURE.md). — [agent-valley landscape](https://github.com/emergencescience/agent-valley/blob/master/docs/research/llm-simulation-landscape.md)
- **OASIS** uses sparse activation: of up to 1M agents, "not all concurrently active" (secondary). — [agent-valley landscape](https://github.com/emergencescience/agent-valley/blob/master/docs/research/llm-simulation-landscape.md)
- **AgentScope 2.0** offers context management ("Automatic compaction, tool-result offload") as middleware. This is a generic piece for keeping prompts small. — [README](https://github.com/agentscope-ai/agentscope)

### Inferences
- **Event-driven thinking beats fixed-tick thinking on a single Mac.** The world ticks deterministically at a fast rate (movement, crafting timers) with no LLM involved. An agent's LLM is invoked only on salient events: someone speaks within earshot, a goal completes or fails, an unexpected entity appears, or an idle timeout fires. This follows from PIANO's "different time scales" and AI Town's off-loop LLM calls. It is the main lever for supporting many agents with limited tokens/sec.
- **Fast reflex controllers should be plain code.** Pathfinding, "walk to X", "gather until N", and "follow agent" are deterministic behaviors the LLM selects; the LLM does not micro-steer them. Mindcraft (Mineflayer skills) and PIANO (non-LLM reflexes) both do this.
- **Let deterministic code act as game master** for physics, crafting and inventory in a game world with defined rules. Concordia's LLM GM suits text worlds where rules are fuzzy. Here it would double LLM calls per action and add hallucination risk, so reserve an LLM GM only for adjudicating free-form or novel actions.
- **Perception filtering and proximity speech** (radius-based hearing, line of sight) belong in the world server. No framework surveyed provides spatial audibility. Concordia's GM could approximate it via prompts, but that is costly and nondeterministic.
- **Memory**: a per-agent SQLite or embedding store with Generative-Agents scoring plus periodic reflection summaries is enough, and it keeps prompts small. Mem0 and Letta are optional add-ons, but each adds extra LLM calls per memory write.
- **Skill library / script writing**: store agent-authored scripts as named, versioned skills (the Voyager pattern), run in a sandboxed interpreter inside the world, and retrieve by embedding. smolagents' code agent or AgentScope's sandbox could inspire this, but the in-world API must be custom anyway.

### Gaps
- Did not retrieve the full Concordia Design Pattern paper (2507.08892) text, to confirm its recommendations on async engines or on mixing grounded variables (deterministic state) with the LLM GM.
- PIANO's implementation code is not public; the repo contains only the paper.
- No quantitative source found comparing event-driven and fixed-tick LLM invocation for agent simulations.

---

## 4. Protocols: MCP and A2A in an in-world simulation

### Takeaway
MCP standardizes agent-to-tool access, and A2A standardizes agent-to-agent communication across services. In a sim where talking must be physically proximate, A2A would bypass the world's physics, so in-world speech should be a world action ("say X"), with the world server deciding who hears it. MCP is moderately useful as an optional adapter: it can expose world actions to external or off-the-shelf agent harnesses, and smolagents, AgentScope and AgentSociety 2 consume MCP. For a custom loop, a native function or JSON-schema action list is simpler and smaller in prompt tokens.

### Cited Findings
- "A2A standardises agent-to-agent communication, while MCP standardises agent-to-tool communication". MCP uses a client-server model; A2A is peer-to-peer with **Agent Cards** (JSON metadata on skills and endpoints) and JSON-RPC 2.0 over HTTP. MCP came from Anthropic (Nov 2024) and A2A from Google (Apr 2025). — [Composio](https://composio.dev/blog/mcp-vs-a2a-everything-you-need-to-know); [obot.ai](https://obot.ai/resources/learning-center/mcp-vs-a2a/); [centron](https://www.centron.de/en/tutorial/a2a-vs-mcp-protocols-for-ai-agents-and-multi-agent-system/)
- A2A repo: 26,379 stars, Apache-2.0, active 2026-11-01. MCP spec repo: 9,584 stars, active 2026-10-31. — [A2A](https://github.com/a2aproject/A2A); [MCP spec](https://github.com/modelcontextprotocol/modelcontextprotocol)
- One blog claims A2A reached v1.0 in early 2026 and that cross-vendor production use is still uncommon. This is single-source and unverified. — [per search summary of A2A vs MCP comparisons](https://pickaxe.co/post/mcp-vs-a2a-protocol)
- Frameworks with MCP support include smolagents ("tools from any MCP server"), AgentScope 2.0 (Toolkit over MCP servers) and AgentSociety 2 ("MCP Support"). A2A is supported by AgentScope 2.0 (`A2AAgent`) and MAF (hosting samples). — [smolagents](https://github.com/huggingface/smolagents); [AgentScope](https://github.com/agentscope-ai/agentscope); [AgentSociety](https://github.com/tsinghua-fib-lab/AgentSociety); [MAF](https://github.com/microsoft/agent-framework)

### Inferences
- **A2A is overkill and actually counterproductive for in-world talk.** It assumes agents are opaque web services that address each other directly. Physically proximate speech must go through the world as an event, so the world can enforce range, broadcast to bystanders, and log it for emergence analysis. A2A might matter later only as an *out-of-world* control plane, for example registering remote brain clients. Even then a simple WebSocket handshake is simpler.
- **MCP**: useful if you want any MCP-capable harness to "possess" an agent, such as a Claude Code or Codex agent joining from another machine, or a smolagents CodeAgent. Expose `look`, `move_to`, `say`, `gather`, `craft` and `run_script` as MCP tools served per agent by the world server. Costs: per-session statefulness, JSON-RPC overhead, and tool-schema tokens in every prompt. For the core swarm on a small local model, a compact custom action grammar (e.g. `sample_choice` over a short action list plus arguments) is likely more reliable.

### Gaps
- Did not verify the current A2A spec version or MCP spec version directly from the spec repos.
- No source found of MCP or A2A used in a multi-agent game simulation (as opposed to tool integrations).

---

## 5. Practitioner opinions: frameworks vs. roll-your-own for agent simulations

### Takeaway
The evidence is mostly indirect but consistent. The notable embodied and social simulations either built bespoke engines or their own research frameworks: Generative Agents, AI Town, Project Sid, Voyager, Mindcraft, OASIS (built on its own CAMEL), Concordia and AgentSociety. None of the notable ones sits on LangGraph, CrewAI or AutoGen. Anthropic's guidance and the "12-factor agents" movement push toward owning the loop and the prompts. Recent 2026 hobby simulation repos also appear to be custom builds.

### Cited Findings
- Anthropic, "Building effective agents" (Dec 19, 2024): frameworks "often create extra layers of abstraction that can obscure the underlying prompts and responses, making them harder to debug. They can also make it tempting to add complexity when a simpler setup would suffice. We suggest that developers start by using LLM APIs directly: many patterns can be implemented in a few lines of code… If you do use a framework, ensure you understand the underlying code." — [Anthropic](https://www.anthropic.com/engineering/building-effective-agents)
- "12-factor agents" (HumanLayer), principles for production LLM software: 26,945 stars, last push 2025-09-21. Its core thesis that you should own your prompts, context window and control flow is from prior knowledge and was not re-read this session. — [repo](https://github.com/humanlayer/12-factor-agents)
- An "Ask HN: Do you roll your own agent or use a framework?" thread exists (Oct 2025), but only a mirror without comments was retrievable. — [mirror](https://usaeconomy-news.blogspot.com/2025/10/hacker-news-story-ask-hn-do-you-roll.html)
- The "roll your own agent" pattern is described as "an LLM in a loop, with one tool" (Val Town template inspired by Thomas Ptacek's Fly.io post). — [Val Town](https://www.val.town/x/nbbaier/roll-your-own-agent)
- Local generative-agent town projects are typically bespoke. TheCodingLand/generative-agents simulates the D&D town Phandalin "with low-parameter, locally runnable models". mkturkcan/generative-agents aims at a cost-effective local alternative and includes a WIP game-simulation library. — [TheCodingLand](https://github.com/TheCodingLand/generative-agents); [mkturkcan via sourcepulse](https://www.sourcepulse.org/projects/1839067)
- Repos tagged `agent-simulation` and updated in 2026 are mostly standalone simulators. Examples: parastore (435 stars, "isometric 3D sandbox"), agent-arena ("drop LLM personas on a 3D map"), SKYCity ("LLM-driven 2D AI town… economic loop"), calder-station ("persistent multi-agent simulation"). — [GitHub topic](https://github.com/topics/agent-simulation)
- A July 2026 landscape review of 40+ simulation systems says "Open-source frameworks are converging on common patterns: persona-based agents, memory systems (Zep, Chroma), GraphRAG for relationships, and structured JSON-based action spaces". — [agent-valley landscape](https://github.com/emergencescience/agent-valley/blob/master/docs/research/llm-simulation-landscape.md)
- Mindcraft and AI Town both ship Ollama as a first-class or default path. That shows local-model embodied simulation is practical with purpose-built code. — [Mindcraft](https://github.com/mindcraft-bots/mindcraft); [AI Town](https://github.com/a16z-infra/ai-town)

### Inferences
- The pattern is that simulation builders use a *simulation* substrate (a game engine, Minecraft, Convex, Mesa, or their own) plus a thin LLM layer. General agent frameworks get used, if at all, for sub-tasks such as a code-writing agent.
- I verified the framework names and descriptions of the 2026 topic repos, but I did not check their dependency lists. "Custom build" is inferred from their descriptions.

### Gaps
- Could not retrieve substantive HN or Reddit comment threads; search returned mirrors and project pages only. Practitioner opinion here rests on Anthropic's guidance, project architectures, and one landscape doc rather than forum consensus.

---

## 6. Verdict for this use case: framework vs. simulation framework vs. thin custom loop

### Takeaway
**Write a thin custom agent loop around an authoritative world server.** Borrow these patterns:
- Generative Agents' memory scoring and reflection.
- Concordia's component structure, `sample_choice`-style constrained action selection, and its asynchronous per-entity observe-act loops.
- PIANO's fast/slow split, with event-triggered deliberation.
- Voyager's code skill library.
- AI Town's LLM-off-the-tick-loop design.

Use **Concordia** (Apache-2.0, active, Ollama and vLLM adapters) as the best *simulation-specific* option to prototype or study. Do not adopt it as the backbone for a deterministic, spatial, multi-machine game world. Avoid general orchestration frameworks (LangGraph, CrewAI, MAF, AG2, OpenAI Agents SDK, Agno, Swarms) as the core. Treat AgentScope's simulation claims as legacy (v0.x).

### Cited Findings
- No general framework surveyed provides space, perception or proximity; all are workflow or task oriented. See the Section 1 READMEs, e.g. CrewAI "production-ready agentic automation", MAF "production-grade AI agents and multi-agent workflows", and AgentScope 2.0 "production-ready… agent framework". — [CrewAI](https://github.com/crewAIInc/crewAI); [MAF](https://github.com/microsoft/agent-framework); [AgentScope](https://github.com/agentscope-ai/agentscope)
- Concordia is the closest simulation-native library: GM pattern, components, sequential, simultaneous and asynchronous engines, and Ollama and vLLM adapters. — [Concordia](https://github.com/google-deepmind/concordia)
- Mesa-LLM is spatial but immature: 81 stars, "API and functionality may change significantly". — [Mesa-LLM](https://github.com/mesa/mesa-llm)
- AgentScope removed its distributed and simulation runtime in 1.0. — [v1.0.0 tree](https://github.com/agentscope-ai/agentscope/tree/v1.0.0/src/agentscope)
- AutoGen is archived or in maintenance mode; Swarm has been replaced by the Agents SDK. — [AutoGen](https://github.com/microsoft/autogen); [Swarm](https://github.com/openai/swarm)
- Anthropic's guidance is to start with LLM APIs directly. — [Anthropic](https://www.anthropic.com/engineering/building-effective-agents)
- Small local models are unreliable at native multi-turn tool calling, and Qwen3-class 8–14B models are the best open options. — [Docker](https://www.docker.com/blog/local-llm-tool-calling-a-practical-evaluation/); [dev.to](https://dev.to/kuroko1t/what-happens-when-local-llms-fail-at-tool-calling-testing-7-models-with-a-rust-coding-agent-cep)

### Inferences
Suggested minimal architecture, synthesized from the patterns above (not taken from any single source):
1. **World server** (Python asyncio or any game loop). It owns the tick clock, map, entities, inventory, crafting rules, a sandboxed script runtime, perception queries (radius, line of sight) and a speech propagation radius. It emits per-agent *observation events* and accepts *intents*. It persists to SQLite or DuckDB.
2. **Agent brain** (one asyncio task per agent; later a separate process on another machine). It runs `wake on salient event or timer -> build compact prompt (persona + top-k memories + current observation + goal) -> LLM call with a small enumerated action set and JSON args (grammar or JSON-schema constrained) -> intent`. It writes memories with importance scores and reflects every N events.
3. **Reflex layer** in world code: `move_to`, `follow`, `gather_until`, `craft` and similar multi-tick behaviors run without the LLM until they complete or are interrupted.
4. **LLM gateway**: one OpenAI-compatible client with a concurrency limiter sized to the model server's parallel slots, priority (conversation responses before background reflection), and per-machine routing.
5. **Optional MCP facade** over the intent API, so external agent harnesses can join as players. Not A2A.

Other recommendations:
- PydanticAI or the raw `openai` client is a reasonable *library* for typed outputs inside step 2 if desired. Both are small and model-agnostic, and neither imposes an orchestration model.
- If a quick proof of concept is wanted before building the world, run Concordia's asynchronous engine with the Ollama adapter on a text-only world. This exercises memory, persona and dialogue emergence on local models. Then port the components into the custom loop.

### Gaps
- No measured data in this research on tokens/sec, concurrency limits, or batching behavior for oMLX, Ollama or llama.cpp on an M1 Max with 32 GB. These numbers determine how many agents can deliberate per minute and should come from the hardware/model-serving research thread.
- Did not test Concordia or Mesa-LLM on Apple Silicon.
