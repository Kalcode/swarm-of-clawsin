# Voxel, sandbox and programmable game worlds as a base for an LLM agent swarm

Research date: 2026-11-01. Repo stats (stars, license as GitHub detects it, last push) come from the GitHub REST API, queried on 2026-11-01 unless another source is given. "Last push" means the most recent push to any branch, not a release. ContentDB (content.luanti.org) was down for maintenance (HTTP 503) during this session. Facts about ContentDB mods therefore come from search-result snippets or the mods' GitHub repos, and are marked as such.

---

## Q1. Luanti (formerly Minetest) and Craftium: license, API, headless server, external bots, in-world computers, runtime modding, scale, macOS

### Takeaway
Luanti is the strongest open-source fit. Its engine code is LGPL-2.1+, it is very actively developed (5.18.0 came out 2026-10-29), it ships signed Apple Silicon builds, it has a dedicated-server binary, it has a Lua mod API with HTTP access to outside processes, and it has in-world Lua computers (the Mesecons luacontroller). Since 2025 there are also Mineflayer-style headless bot clients, including a Python one with an MCP server. Two main caveats: (1) new node, item and craft types can only be registered at load time, so "agents write mods" means restarting the server, although sandboxed Lua can run at runtime; (2) one documented load test shows a single server CPU saturating at about 70-100 connected clients. Craftium is a credible research wrapper, but it gives every agent its own rendering client. That suits pixel-based RL, not 50-100 text-driven LLM agents.

### Cited Findings

**Core engine status and license**
- Repo `luanti-org/luanti`: about 13.8k stars, C++, last push 2026-10-30. — [GitHub](https://github.com/luanti-org/luanti)
- Latest releases: **5.18.0 published 2026-10-29** (rc1 on 2026-10-18), 5.17.0 published 2026-08-20. — [GitHub releases](https://github.com/luanti-org/luanti/releases)
- The official downloads page still listed 5.17.0 as current stable when fetched, so it lags the GitHub release. — [luanti.org/en/downloads](https://www.luanti.org/en/downloads/)
- 5.17.0 added basic gamepad support, multi-track animation, a dummy auth backend and several security fixes. — [GamingOnLinux, Aug 2026](https://www.gamingonlinux.com/2026/08/voxel-game-creation-platform-luanti-formerly-minetest-gets-basic-gamepad-support-security-fixes/)
- Earlier cadence:
  - 5.14 shipped around Oct/Nov 2025. — [GamingOnLinux](https://gamingonlinux.com/2025/10/luanti-formerly-minetest-v5-14-brings-an-improved-minimap-particle-improvements-and-ui-tweaks)
  - 5.15.0 shipped 2026-01-23. — [FGD Planet](https://planet.freegamedev.net/category/voxel)
  - In total, about four releases in 12 months.
- **License:** engine code is under the GNU LGPL "version 2.1 of the License, or (at your option) any later version". Textures and sounds are CC BY-SA 3.0, with some CC BY-SA 4.0. The bundled Lua is MIT. — [LICENSE.txt](https://github.com/luanti-org/luanti/blob/master/LICENSE.txt)
  - The GitHub API reports the license as "NOASSERTION" because the file mixes several licenses.
- ContentDB only accepts packages under licenses that the FSF and/or OSI consider free. — [docs.luanti.org/about/contentdb](https://docs.luanti.org/about/contentdb/)

**Platforms and headless server**
- macOS: signed app bundles for **Apple Silicon (arm64)** and Intel x86_64; macOS 12.3+ recommended; `brew install --cask luanti`; MacPorts `port install luanti`. — [luanti.org downloads](https://www.luanti.org/en/downloads/)
- Other platforms: Windows 8/8.1/10/11 (installer and portable zip), Linux (Flatpak, Snap, distro packages), Android 6+. — [luanti.org downloads](https://www.luanti.org/en/downloads/)
- The man page documents two ways to run a server: `luanti --server [SERVER OPTIONS]` and a standalone `luantiserver` binary. — [doc/luanti.6](https://github.com/luanti-org/luanti/blob/master/doc/luanti.6)
- The repo also includes "Running a server with Docker" docs. — [GitHub README](https://github.com/luanti-org/luanti), [doc/docker_server.md](https://github.com/luanti-org/luanti/blob/master/doc/docker_server.md)
- Mods "are contained and ran solely on the server side". Definitions and media are sent to clients automatically, so connecting clients need no mod install. — [api.luanti.org](https://api.luanti.org/)

**Mod API facts relevant to agents** (all from [doc/lua_api.md](https://github.com/luanti-org/luanti/blob/master/doc/lua_api.md))
- Registration functions such as `core.register_node` carry the note: "**Call these functions only at load time!**" New block, item and recipe types therefore cannot be added while the server runs.
- HTTP API:
  - `core.request_http_api()` returns `fetch`, `fetch_async` and `fetch_async_get`.
  - It works only for mods listed in `secure.http_mods` or `secure.trusted_mods`.
  - It must be called at init time from the mod's main scope.
  - It requires a cURL-enabled build.
- `core.request_insecure_environment()` gives trusted mods the full, unsandboxed Lua environment. It also works only at init time.
- `core.handle_async()` and `core.register_async_dofile()` run work in separate async Lua environments.
- `core.ipc_get` / `core.ipc_set` provide "a shared in-memory key-value store" across the main, mapgen and async environments.
- Mod storage (`core.get_mod_storage()`) must be obtained at load time.

**Scale and performance (limited evidence)**
- One Docker load test simulated Minetest clients against an **AMD Ryzen 7 3700X** server. — [miney-py/minetest-client-docker](https://github.com/miney-py/minetest-client-docker)
  - 70 clients: max_lag 0.4, about 90% CPU, no issues.
  - 90 clients: max_lag 3.3, client movement stutters.
  - 100 clients: max_lag 6+, about 99% CPU, every action takes 10+ seconds.
  - The author estimates about 120 MB of RAM per client. Those clients render on the CPU, so the figure likely covers the simulated client containers, not the server.
  - No engine version or test date is given.
- A 2019 forum guide says the CPU is the main bottleneck (prefer fewer, faster cores) and recommends lowering the active block range. — [Minetest forums mirror](https://sorcerykid.github.io/minetest-forums/pages/10_22561.htm)

**External bot / agent connectors (2025-2026)**
- **luantibot** (Elliott Wen, `elliott-wen/luanti-bot`; 4 stars; last push 2026-09-16; no license found). — [luanti-diamond-agent README](https://github.com/Goldengamer255/luanti-diamond-agent); [GitHub](https://github.com/elliott-wen/luanti-bot)
  - Describes itself as "A Mineflayer-style bot library for Luanti … Pure Python, standard library only".
  - It implements the Luanti network protocol, including reliable UDP and SRP authentication with first-time registration.
  - It ships `luantibot.mcp_server`, an MCP stdio server with tools `connect`, `goto`, `dig`, `place`, `chat`, `find_blocks`, `node_at`, `craft`, `smelt`, `mine_to_depth`, `defend`, `entities`.
  - Origin: course starter code for SE325 at the University of Auckland.
  - Known limits: the client is authoritative over its own position, movement is interpolated rather than physics-based, it never sends fall-damage packets ("effectively cheating"), and it does not reconnect automatically.
- **luanti-diamond-agent:** an LLM agent built on luantibot that got from an empty inventory to diamond in VoxeLibre in 3 min 29 s with one LLM call, using about 2-3k tokens per call. It uses any OpenAI-compatible model. Single bot only; 0 stars. — [GitHub](https://github.com/Goldengamer255/luanti-diamond-agent)
- **kris072008/luanti-aibot:** a single server-side Lua mod of about 1,900 lines. — [GitHub](https://github.com/kris072008/luanti-aibot)
  - Every few seconds it sends an observation (position, inventory, surroundings, the planner's suggested step, recent actions) to Ollama (default `llama3.2`) or Gemini and gets back one JSON action.
  - It needs `secure.http_mods = aibot`.
  - Tested on a MacBook Air with VoxeLibre. 0 stars, no license.
- **LuantiBot (ll-ml):** according to a search snippet of its DeepWiki page, it combines a Rust network client, a server-side Lua instrumentation mod and an OpenAI-compatible agent loop, with a REST control API on port 9123. — [DeepWiki](https://deepwiki.com/ll-ml/LuantiBot)
  - Unverified: the page returned HTTP 429, and the GitHub API reports the repo as "Moved Permanently".
- **LLM Connect** (ContentDB mod by H5N3RG): lets players talk to an LLM inside Luanti. It has an "agent mode" with external Lua skill mods registered through a skill registry. — [ContentDB (search snippet)](https://content.luanti.org/packages/H5N3RG/llm_connect/)
- **luanti-voyager** (toddllm): an MIT-licensed experiment that drives LLMs in Luanti through Craftium. 9 stars, last push 2025-08-14. — [GitHub](https://github.com/toddllm/luanti-voyager)
- **Go and Lua protocol libraries:**
  - `anon55555/mt` is a Go implementation of the Minetest protocol (listing dated 2021). — [pkg.go.dev](https://beta.pkg.go.dev/github.com/anon55555/mt/cmd/proxy)
  - The `dragonfireclient/mt` fork says it is compatible with Minetest 5.4.1, so it may be stale. — [pkg.go.dev](https://pkg.go.dev/github.com/dragonfireclient/mt)
  - **Hydra** offers Lua bindings for the client-side protocol, aimed at bot clients ("spawn and poll multiple clients from one script"). Marked work-in-progress. — [GitHub](https://github.com/dragonfireclient/hydra-dragonfire)
  - `mt-multiserver-proxy` is a Go reverse proxy with a plugin API. — [pkg.go.dev](https://pkg.go.dev/github.com/HimbeerserverDE/mt-multiserver-proxy)

**In-world programmable computers in Luanti**
- **Mesecons luacontroller** — [mesecons.net/luacontroller](https://mesecons.net/luacontroller/)
  - Runs player-written Lua in a sandbox limited to `print`, `tostring`, `tonumber`, the `string` library, plus `pin`, `port`, `interrupt`, `digiline_send`, `mem` and `event`.
  - Limits: instruction cap `luacontroller_maxevents` (default 10000), `mem` of 100 kB, and "overheating" above 20 operations per second.
  - Digiline messages can be up to 50,000 serialized characters.
  - Interrupt timers persist across restarts.
- Repo activity: `minetest-mods/mesecons` 225 stars, last push 2026-09-08; `minetest-mods/digilines` (data-bus wires) last push 2026-07-06. — [mesecons](https://github.com/minetest-mods/mesecons), [digilines](https://github.com/minetest-mods/digilines)
- **mooncontroller** (mt-mods): "enhanced luacontroller (experimental)", last push 2026-06-19. — [GitHub](https://github.com/mt-mods/mooncontroller)
- **LWComputers** (loosewheel): programmable computers and robots, floppies, printers and graphical screens. — [ContentDB (search snippet)](https://content.luanti.org/packages/loosewheel/lwcomputers); [GitHub](https://github.com/loosewheel/lwcomputers)
  - Each computer runs Lua in its own sandboxed environment.
  - Robots can "move, detect, dig, place, craft and work with inventories".
  - Requires LuaJIT.
  - **Stale:** last push 2022-06-18.
- **Computertest** (zaners123): ComputerCraft-inspired turtles that run uploaded Lua and can mine, move and turn. Its page warns the turtle code **is not sandboxed**. MPL-2.0, last push 2022-07-24 (stale). — [ContentDB (search snippet)](https://content.luanti.org/packages/zaners123/computertest); [GitHub](https://github.com/zaners123/Computertest)
- **Adabots** (a fork of computertest): an in-game turtle polls an external program over HTTP, on port 7112 by default. — [GitHub README](https://github.com/TamaMcGlinn/minetest-adabots)
  - Supported actions: move, mine, build, detect, select slot, use chests, inspect blocks, craft.
  - Needs a custom fork of Minetest 5.6.0 plus MineClone 5. Last push 2026-09-26.
- **Turtlebots** (jmole): "Turtle Bots that you can program to build anything!", listed for Luanti 5.8+. — [ContentDB (search snippet)](https://content.luanti.org/packages/jmole/turtlebots)
- Libox Controller is marked deprecated on ContentDB. — [search snippet](https://content.luanti.org/packages/frogTheSecond/libox_controller/)

**Craftium**
- Repo `mikelma/craftium`: 214 stars, last push 2026-02-17, no GitHub releases. — [GitHub](https://github.com/mikelma/craftium)
  - Built on Luanti v5.12.0 (per its badge).
  - Implements Gymnasium and PettingZoo.
  - Supports "client/server synchronization" for "slow agents (e.g., LLMs or VLMs)".
  - Includes a `llava_agent.py` example.
  - The prebuilt wheel and Docker image target manylinux x86_64. macOS is covered only by a link to Luanti's compile guide.
- License conflict: GitHub shows LGPL-2.1 (inherited from Luanti), but the README says "MIT for code and CC-BY-SA 3.0 for content". — [GitHub](https://github.com/mikelma/craftium)
- Paper: "Craftium: Bridging Flexibility and Efficiency for Rich 3D Single- and Multi-Agent Environments" (Malagón, Ceberio, Lozano), **ICML 2025**, arXiv 2407.03969. Details below are from [arXiv HTML](https://arxiv.org/html/2407.03969v2):
  - Architecture: a modified Luanti plus a Python interface with one channel per agent. Each agent is a Luanti client that renders RGB frames and sends keyboard and mouse actions. Lua functions report reward and termination.
  - Performance: "+2670 steps per second more" than MineDojo, "38× faster" than Minecraft-based alternatives, and over 12K SPS with parallel environments. Hardware: A5000 GPU, Xeon Silver 4309Y.
  - Multi-agent tests covered only a two-agent self-play fight.
  - A zero-shot LLaVa 1.6 agent unlocked the collect-wood and collect-stone stages.
  - In optional synchronous mode, the server waits for clients.

### Inferences
- **Two good integration patterns:**
  - **(a) External network clients** (luantibot or Hydra style). Each agent is a real player, and remote Macs or PCs can run their own agents against the server over UDP. The cost is client-authoritative movement, so "must walk to talk" and speed limits need server-side enforcement in a mod.
  - **(b) A server-side "agent bridge" mod.** Agents are entities or NPCs the mod controls. The mod uses `request_http_api` to poll an external orchestrator over HTTP or long-poll, as luanti-aibot and Adabots do. This avoids per-agent network clients and lets the server enforce senses (radius-limited chat, line of sight), but agents are not real players.
  - A hybrid looks most practical: the bridge mod exposes a per-agent HTTP/JSON API, and remote machines' agent processes call it.
- **"Discover in-world scripting"** maps well onto luacontroller-style sandboxes. Agents can write and run Lua at runtime in limited nodes such as computers, turtles and digiline networks.
- **"Modify the world itself"** has two tiers:
  - Runtime: sandboxed Lua that moves blocks, triggers events and drives turtles.
  - Load time: agent-authored mods that need a server restart, since register_* calls are load-time only. These could be gated behind a review or "world update epoch" mechanism.
  - Never give agent-written code `request_insecure_environment`.
- **A turtle/computer mod probably has to be written or forked.** The Luanti turtle mods found are stale (2022) or need a custom engine fork. Combining luacontroller-style sandboxing with LWComputers-style robots is a modest Lua project (estimate: a few hundred to a couple thousand lines).
- **50-100 agents on one M1 Max.** The world server is unlikely to be the bottleneck (estimate: Luanti server well under 2-4 GB RAM, plus negligible Python bot clients). The binding constraint is local LLM throughput. The 70-100 client saturation figure came from a 2019-era desktop CPU with rendering clients on the same machine, so treat it as an upper-bound warning, not a measurement for this setup.
- **Craftium is a poor fit for 50-100 text-based LLM agents.** It runs one rendering client per agent and is x86 Linux-first. Its useful parts are the reward/termination Lua hooks and the sync mode.

### Gaps
- No measured Luanti server RAM/CPU figures for 50-100 bot players on Apple Silicon were found.
- The licenses, current status and repo URL of LuantiBot (ll-ml) could not be confirmed (HTTP 429, repo moved).
- ContentDB was down, so release dates, licenses and download counts for LWComputers, Turtlebots, LLM Connect, Mineclonia and VoxeLibre were not retrieved from ContentDB.
- Whether Craftium builds on macOS arm64 was not confirmed.
- The 5.18.0 changelog was not found in news sources yet (release 2026-10-29).
- LuaATC (advtrains Lua automation) was not researched.

---

## Q2. Minecraft-based routes: Mineflayer, Mindcraft, Voyager, CC:Tweaked, OpenComputers, MineDojo, MineLand, Malmo/MineRL, Project Sid; licensing and resource cost

### Takeaway
Minecraft has by far the richest LLM-agent ecosystem. Mineflayer and Mindcraft are MIT-licensed and very active, and MineLand measured 64 headless agents at about 6.3 GB of RAM. CC:Tweaked is the canonical in-world Lua computer and turtle mod, with HTTP and websockets. However, Minecraft itself is proprietary: humans on other machines need paid Java Edition clients, offline-mode servers are a gray area that should stay on the LAN, and several research stacks (Voyager, MineDojo, Malmo, MineLand) are archived or stale.

### Cited Findings
- **Mineflayer:** MIT, about 7.7k stars, release 4.39.0 on 2026-09-06, last push 2026-10-27. — [GitHub](https://github.com/PrismarineJS/mineflayer), [releases](https://github.com/PrismarineJS/mineflayer/releases)
- **Mindcraft** (mindcraft-bots/mindcraft): MIT, about 6.0k stars, last push 2026-10-27. — [GitHub](https://github.com/mindcraft-bots/mindcraft)
  - Supports Minecraft Java up to v1.21.11 (1.21.6 recommended).
  - Supports Ollama, including the fine-tuned `sweaterdog/andy-4:micro-q8_0`, and vLLM.
  - Runs multiple agents through multiple profile files, and task files have an `agent_count` field.
  - LLM code-writing is **disabled by default** (`allow_insecure_coding`). The README warns it is "still vulnerable to injection attacks" and recommends Docker.
  - Online servers require Microsoft auth; local play uses "open to LAN".
  - Related multi-agent paper: MineCollab, arXiv 2504.17950 (2025).
- **Voyager** (MineDojo/Voyager): MIT, about 7.3k stars, **last push 2024-04-03 (stale)**. **MineDojo:** last push 2024-03-18 (stale). — [Voyager](https://github.com/MineDojo/Voyager), [MineDojo](https://github.com/MineDojo/MineDojo)
- **Malmo** (microsoft/malmo): **archived** on GitHub. **MineRL:** last push 2025-01-22. — [Malmo](https://github.com/microsoft/malmo), [MineRL](https://github.com/minerllabs/minerl)
- **MineLand** (arXiv 2403.19267, 2024) — [arXiv HTML](https://arxiv.org/html/2403.19267v2); [GitHub](https://github.com/cocacola-lab/MineLand)
  - Design: 64+ agents with limited multimodal senses (tactile, auditory, first-person RGB with distance, obstruction and direction limits), a chat range threshold, and physical needs (health, food, oxygen).
  - Stack: a Fabric server plus a Mineflayer-based bridge. Code-based actions follow Voyager. Each code step lasts 50-200 ms.
  - Measured on an i5-12400F with 64 GB RAM (no GPU mentioned):

    | Configuration | Avg CPU | Memory |
    |---|---|---|
    | 8 agents, headless | 1.88% | 2.94 GB |
    | **64 agents, headless** | **2.87%** | **6.30 GB** |
    | 128 agents, headless | 4.00% | 9.04 GB |
    | 32 agents, with vision | 5.64% | 19.65 GB |
    | Malmo, 8 agents (comparison) | 7.90% | 18.63 GB |

  - Repo: MIT, but **archived** (last push 2025-09-30).
- **Project Sid** (Altera): "10 - 1000+ AI agents", PIANO architecture, arXiv 2411.00114 (Oct 2024). — [arXiv](https://arxiv.org/abs/2411.00114); [GitHub](https://github.com/altera-al/project-sid)
  - Repo `altera-al/project-sid`: about 1.4k stars, last push 2024-11-04, no license detected.
  - Outcomes reported in press coverage (taxes, religion spread) come from the company, not independent review. — [Tom's Hardware](https://www.tomshardware.com/tech-industry/artificial-intelligence/ai-created-a-minecraft-ai-village-with-up-to-1-000-inhabitants-project-sid-sees-ai-bots-implement-a-taxation-system-and-spread-pastafarianism-religion)
- **CC:Tweaked:** latest release **v26.3-1.120.3 on 2026-09-28**; repo last push 2026-10-30; about 1.2k stars. — [releases](https://github.com/cc-tweaked/CC-Tweaked/releases)
  - Licensing: the README carries `SPDX-License-Identifier: MPL-2.0`, and the repo's `LICENSES/` folder includes MPL-2.0, `LicenseRef-CCPL` (the original ComputerCraft Public License), Apache-2.0, MIT and CC licenses, so licensing is mixed. — [README](https://github.com/cc-tweaked/CC-Tweaked), [LICENSES](https://github.com/cc-tweaked/CC-Tweaked/tree/mc-1.20.x/LICENSES)
  - Third-party listings disagree on the license (CCPL, MIT, Custom). — [search results, e.g. modpackindex](https://www.modpackindex.com/mod/7627/cc-tweaked)
  - Its `http` module supports `http.get`/`post`/`request` plus `http.websocket`. The docs link to an "Allowing access to local IPs" guide, which implies local IPs are blocked by default (unconfirmed). — [tweaked.cc http](https://tweaked.cc/module/http.html)
  - Turtles are "a robotic device, which can break and place blocks, attack mobs, and move about the world". — [tweaked.cc](https://tweaked.cc/)
- **OpenComputers:** GitHub repo **archived** (last push 2026-08-04). — [GitHub](https://github.com/MightyPirates/OpenComputers)
- **Offline mode:** `online-mode=false` turns off account verification. Mineflayer supports `auth: 'offline'`. The `itzg/minecraft-server` Docker image with `EULA=TRUE ONLINE_MODE=FALSE` starts a server that needs no account. Guides warn against exposing offline servers publicly. — [Teramont guide](https://teramont.net/blog/minecraft-server-offline-mode-online-mode-false)
- **Bot memory**
  - The Azalea Rust bot library estimates one idle bot at 20-40 MB. Swarm bots share world data at "usually up to 1mb extra per bot". — [Azalea performance docs](https://docs.rs/crate/azalea/latest/source/src/_docs/performance.md)
  - A Mineflayer discussion reports steadily climbing RAM with many bots (memory leak). — [mineflayer #2779](https://github.com/PrismarineJS/mineflayer/discussions/2779)
- **Server software**
  - PaperMC: about 12.8k stars, last push 2026-11-01. — [GitHub](https://github.com/PaperMC/Paper)
  - Minestom: Apache-2.0 "Lightweight Minecraft server" library, last push 2026-11-01. — [GitHub](https://github.com/Minestom/Minestom)
  - Cuberite: Apache-2.0, C++ with a **Lua plugin API**, but supports only protocol 1.8-1.12.2. Last push 2026-04-25. — [README](https://github.com/cuberite/cuberite)

### Inferences
- **Cost.** Each human or GUI viewer needs a Minecraft Java Edition license, because the client is proprietary. Bots on an offline-mode LAN server need none. The ecosystem is stuck on Mojang's update cadence (ViaProxy shims, mod porting).
- **Memory on a 32 GB M1 Max.** A modded Fabric or Paper server plus 50-100 Mineflayer bots likely needs about 6-10 GB (extrapolated from MineLand's headless numbers). That competes directly with local LLM memory. Luanti plus Python bots is likely lighter (estimate, not measured).
- **CC:Tweaked is the closest existing match to "agents discover in-world programming".** Mineflayer agents could place a computer or turtle, write Lua into it, and use `http.websocket` to talk to the orchestrator. Mindcraft's `newAction` code-writing is a template for LLM-authored JavaScript skills.
- **Risk:** licensing ambiguity (CCPL legacy code), Minecraft EULA constraints on distribution, and a stack that churns with each Minecraft version.
- **MineLand is the best design reference for "limited senses + physical needs + chat radius".** Even though the repo is archived, its ideas port to any engine.

### Gaps
- Minecraft Java server RAM and CPU on Apple Silicon with 50-100 Mineflayer bots was not measured in any source found.
- A precise Mineflayer per-bot memory figure was not found.
- The exact Minecraft EULA terms for offline-mode bot servers were not reviewed.
- MineDojo/MineRL deprecation notices were not checked; only commit dates were.
- The current Java Edition price was not checked.

---

## Q3. Minecraft-like open-source alternatives: Veloren, Vintage Story, Mineclonia/VoxeLibre, Crafter, Craftax, ClassiCube, Cuberite, Minestom/Paper

### Takeaway
Apart from Luanti, none of these is a better base. Veloren is active and GPL-3.0, but it is an RPG with no bot API (you would drive its Rust client crate directly). Crafter is stale, and Craftax is a single-agent JAX RL benchmark, though both have text observations useful for prototyping. ClassiCube and Cuberite are limited Minecraft-protocol niches. Mineclonia and VoxeLibre are just Luanti games, and are good content packs on top of the Luanti choice.

### Cited Findings
- **Veloren:** GPL-3.0, Rust, about 7.7k stars, last push 2026-10-30 (GitHub mirror of GitLab). — [GitHub](https://github.com/veloren/veloren)
  - The repo contains `client`, `server`, `server-cli`, `rtsim` (real-time NPC simulation), `plugin` (with a `wit` interface folder, i.e. WASM component plugins) and `world` crates. — [GitHub contents](https://github.com/veloren/veloren)
  - The developer book says the GUI frontend `voxygen` has "no inherent coupling with the internal client library". — [Veloren book](https://book.veloren.net/contributors/developers/codebase-structure.html)
  - No Veloren bot client or bot API was found. — [search](https://book.veloren.net/contributors/developers/codebase-structure.html)
- **VoxeLibre** is described as "Minecraft-like, on Luanti", and LLM bots already target it (luanti-aibot, luanti-diamond-agent). — [kris072008/luanti-aibot](https://github.com/kris072008/luanti-aibot), [luanti-diamond-agent](https://github.com/Goldengamer255/luanti-diamond-agent)
- **Crafter** (Danijar Hafner): MIT, about 605 stars, **last push 2024-01-23 (stale)**. — [GitHub](https://github.com/danijar/crafter)
- **Craftax** ("Crafter + NetHack in JAX", ICML 2024 Spotlight): MIT, release **v1.7.0 on 2026-10-27**. — [GitHub](https://github.com/MichaelTMatthews/Craftax)
  - "Both Craftax and Craftax-Classic also support rendering observation as text for language agents."
  - It points to JaxMARL for multi-agent RL; Craftax itself is single-agent.
- **ClassiCube:** a custom Minecraft Classic client in C, BSD-style license (copyright UnknownShadow200), last push 2026-10-28. — [GitHub](https://github.com/ClassiCube/ClassiCube), [license.txt](https://github.com/ClassiCube/ClassiCube/blob/master/license.txt)
- **Cuberite:** C++, Lua plugins, Apache-2.0, Minecraft protocol 1.8-1.12.2 only. — [README](https://github.com/cuberite/cuberite)
- **Minestom** (Apache-2.0) and **Paper** are active Java servers, but they still need the proprietary Minecraft client for humans. — [Minestom](https://github.com/Minestom/Minestom), [Paper](https://github.com/PaperMC/Paper)

### Inferences
- Veloren could in principle host agents through its `client` crate or WASM plugins, but you would have to build the whole agent API in Rust. Its gameplay (combat RPG) fits "chop, mine, craft, script" less well than Luanti or Minecraft.
- Crafter and Craftax are useful as fast offline testbeds for agent prompting (text observations, crafting tech tree), not as the shared persistent multiplayer world.
- Cuberite is interesting: a Lua plugin server that speaks the Minecraft protocol, so Mineflayer bots work against older protocol versions. But it is stuck at 1.12.2 and humans still need Minecraft clients.

### Gaps
- **Vintage Story** was not researched in this session. It is widely understood to be proprietary with C# modding, which is unverified here and should be confirmed before citing.
- **Mineclonia** repo location and status were not retrieved (`mineclonia/mineclonia` is not on GitHub; it is likely on Codeberg; ContentDB was down).
- Terraria-like open-source games (e.g., TerrariaClone, Necesse) were not researched.

---

## Q4. Programmable-world games: Screeps, Bitburner, Factorio + FLE, Else Heart.Break-likes, Ludii, Gather-like worlds

### Takeaway
Screeps (ISC private server, players program units in JavaScript) and the Factorio Learning Environment (agents write Python against a live Factorio, MIT, NeurIPS 2025, multi-agent since v0.2) are the two serious "program the world" options. Both are about programming units or factories, not embodied walk-to-talk social agents. Factorio also needs a paid game license. Bitburner is single-player and Commons-Clause licensed. No open-source Else Heart.Break-style "every object runs code" game was found, so that layer would have to be built (luacontroller-style sandboxes in Luanti come closest).

### Cited Findings
- **Screeps standalone server** — [GitHub](https://github.com/screeps/screeps)
  - License: ISC.
  - Install: `npm install screeps`, then `npx screeps init` and `start`. Requires **Node.js 22 LTS+**, Python 3 and build tools.
  - Needs a Steam Web API key when no local Steam client is running.
  - NPC bots via `bots.spawn(botAiName, roomName, opts)`.
  - Admin CLI on port 21026 with a JS VM. Mods are Node modules listed in `mods.json`.
  - Last tagged release v3.4.0 (2019-05-03), but the repo was pushed 2026-04-01; about 3.4k stars. — [GitHub API/releases](https://github.com/screeps/screeps/releases)
- **Screeps + AI:** no project where an LLM plays Screeps was found. — [search](https://lobehub.com/ru/mcp/ralphschuler-screeps-api-mcp)
  - A community **Screeps API MCP server** lets MCP clients connect to official or private servers, run console commands, read room data and manage memory. — [LobeHub listing](https://lobehub.com/ru/mcp/ralphschuler-screeps-api-mcp)
  - Overmind has an RL training mode where creeps are controlled by serialized actions written to Memory. — [Overmind fork](https://github.com/0xF6/Overmind)
- **Factorio Learning Environment (FLE)**
  - License: MIT (LICENSE file, "Copyright (c) 2025 Factorio Learning Environment Contributors"). About 1.2k stars, last push 2026-09-18. — [GitHub](https://github.com/JackHopkins/factorio-learning-environment)
  - Agents generate Python programs in a REPL. There is an optional `[mcp]` extra, and the cluster starts with `fle cluster start` (Docker). — [GitHub](https://github.com/JackHopkins/factorio-learning-environment)
  - v0.2 (May 2025) added multi-agent play via "Factorio's native multiplayer". — [FLE v0.2 release](https://jackhopkins.github.io/factorio-learning-environment/release.0.2.0)
  - v0.3.0 removed the game-client dependency (headless). — [FLE v0.3.0](https://jackhopkins.github.io/factorio-learning-environment/versions/0.3.0.html)
  - Factorio is still a prerequisite, and connecting "confirms your Factorio license". — [search summary of README](https://jackhopkins.github.io/factorio-learning-environment/versions/0.3.0.html)
  - Paper: NeurIPS 2025 Datasets & Benchmarks, arXiv 2503.09617. — [NeurIPS](https://proceedings.neurips.cc/paper_files/paper/2025/hash/75f3a62e55187bc3e5e5961fa2a46bcf-Abstract-Datasets_and_Benchmarks_Track.html), [arXiv](https://arxiv.org/abs/2503.09617)
  - Showcased as "Claude Code Plays Factorio" (FLE v0.3). — [HN](https://hn.svelte.dev/item/45466865)
- **Bitburner:** TypeScript, about 1.6k stars, last push 2026-11-01. License is **"Apache 2.0 with Commons Clause"** (no right to sell). — [license.txt](https://github.com/bitburner-official/bitburner-src/blob/dev/license.txt)
- **Ludii:** a general board-game system, Java, about 170 stars, last push 2026-10-21. It is not an embodied world. — [GitHub](https://github.com/Ludeme/Ludii)
- **WorkAdventure** (Gather-Town-like 2D virtual office): about 5.9k stars, last push 2026-10-31. GitHub did not detect the license. — [GitHub](https://github.com/workadventure/workadventure)

### Inferences
- **Screeps could host LLM agents.** Each agent would be a Screeps "user" whose generated JS runs every tick, which suits the "discover programming, then script the world" arc. But there is no embodied first-person agent: units are creeps, not avatars that walk to talk. Agent count is limited by private-server tick CPU. Remote machines can connect, since it is a client/server MMO.
- **FLE** is the best existing harness for "LLM writes code that acts on a world". Its REPL/MCP design is worth copying. As the world base it fails the requirements: paid Factorio license, factory-only gameplay, and no social or senses layer.
- **Else Heart.Break and Hack 'n' Slash** are proprietary. Their mechanic ("objects run editable code", "edit game variables") is best reproduced by giving world objects sandboxed scripts that agents can read and modify (Lua in Luanti, or JS/Python in a custom world).

### Gaps
- Screeps macOS/Apple Silicon behavior (native addons such as isolated-vm) was not verified.
- Screeps maximum user/bot counts on one machine were not found.
- Factorio headless server availability on macOS arm64 (Docker x86 emulation?) was not verified.
- Factorio's current price was not checked.
- Oxygen Not Included modding, Elevator Saga and PICO-8 style worlds were not researched (deprioritized as poor fits).

---

## Q5. Lightweight custom worlds (Godot, Bevy, PyGame, browser tile worlds, AI Town, Smallville): build vs. adapt

### Takeaway
AI Town (MIT, Convex + PixiJS, Ollama by default) and Smallville are 2D social sandboxes with walking and chat but no inventory, crafting or scripting. Smallville's repo has been stale since 2024. A custom 2D tile world with a websocket server is very feasible and gives full control over senses and scripting. You would then have to build crafting, persistence and a client yourself. Adapting Luanti gets 3D voxels, crafting, multiplayer, cross-platform clients and Lua scripting for free.

### Cited Findings
- **AI Town** (a16z-infra/ai-town) — [GitHub](https://github.com/a16z-infra/ai-town)
  - MIT; about 10.7k stars; last push 2026-08-26.
  - Stack: Convex (engine, database, vector search), PixiJS and TypeScript.
  - Local LLMs: Ollama by default (`llama3`, plus `mxbai-embed-large` embeddings).
  - Self-hosts via Docker Compose (Convex backend on port 3210, frontend on 5173).
  - The map is built in Tiled and converted with `convertMap.js`.
  - The README describes only chatting and socializing characters; no inventory or crafting is mentioned.
- **Generative Agents / Smallville** (joonspk-research): Apache-2.0, about 22.3k stars, **last push 2024-08-05 (stale)**. — [GitHub](https://github.com/joonspk-research/generative_agents)
- **Engines:** Godot is MIT (about 119k stars, active). Bevy reports Apache-2.0 (about 49k stars, active). — [Godot](https://github.com/godotengine/godot), [Bevy](https://github.com/bevyengine/bevy)

### Inferences
- **Custom tile world** (estimate). A Python or TypeScript authoritative server with a grid map, tick loop, radius-limited chat and vision, inventory and recipe table, and a websocket JSON API for agents is roughly 1-3k lines for an MVP.
  - In-world scripting could be sandboxed Lua via `lupa`, or JS via QuickJS or isolated-vm. Remote machines join trivially over websockets. A browser canvas viewer is cheap.
  - The hard parts are content design, persistence, a sandbox with no escapes, and a nice human-facing client.
- **Adapting Luanti** inverts this: rendering, networking, persistence, crafting content (VoxeLibre/Mineclonia), cross-platform clients and a Lua sandbox precedent (luacontroller) already exist. The work is the agent bridge, enforcing senses, and a computer/turtle mod.
- **For text-only LLM agents, 3D adds little to the agents themselves.** They will consume structured observations, not pixels. It does add a lot to human spectating and "world feel". A 2D custom world is lighter and easier to reason about.
- **AI Town** is a good base for the social layer (memory, conversation, walking), but it would need a game-mechanics layer added on top.

### Gaps
- No existing open-source 2D template with crafting plus in-world scripting plus LLM agents was found.
- The claim that Smallville's frontend is Phaser was not verified in this session.
- Godot and Bevy headless-server support and LLM agent integrations were not researched.

---

## Q6. Candidate-by-candidate comparison (license, language, agent API, headless, multiplayer, in-world scripting, resource cost, activity, LLM integrations)

### Takeaway
Ranked for this project:
1. **Luanti with a custom agent-bridge mod**, with VoxeLibre/Mineclonia content and luacontroller/turtle-style sandboxes. This is the best open-source, Apple Silicon-native base.
2. **Minecraft + Mineflayer/Mindcraft + CC:Tweaked.** The richest agent ecosystem and the best in-world computers, but a proprietary client and a heavier server.
3. **A custom 2D tile world** (possibly AI Town-derived), for maximum control at minimum resource cost.

Screeps and FLE are better seen as design references than world bases.

### Cited Findings
Comparison matrix. Facts are cited inline; cells marked "est." are estimates.

| Candidate | License | Lang / API | External agent I/O | Headless server | Remote clients (Mac/Win/Linux) | In-world scripting | Activity (2025-26) | LLM-agent integrations |
|---|---|---|---|---|---|---|---|---|
| **Luanti** | LGPL-2.1+ code, CC BY-SA media ([LICENSE](https://github.com/luanti-org/luanti/blob/master/LICENSE.txt)) | C++ engine, Lua mods ([lua_api](https://github.com/luanti-org/luanti/blob/master/doc/lua_api.md)) | Network bot clients ([luantibot](https://github.com/Goldengamer255/luanti-diamond-agent), [Hydra](https://github.com/dragonfireclient/hydra-dragonfire)); mod HTTP API ([lua_api](https://github.com/luanti-org/luanti/blob/master/doc/lua_api.md)) | `luantiserver` / `--server` ([man](https://github.com/luanti-org/luanti/blob/master/doc/luanti.6)) | Native clients for macOS arm64/x86, Windows, Linux, Android ([downloads](https://www.luanti.org/en/downloads/)) | Luacontroller sandbox ([mesecons](https://mesecons.net/luacontroller/)); turtle mods stale | 5.18.0 on 2026-10-29 ([releases](https://github.com/luanti-org/luanti/releases)) | luantibot+MCP, luanti-aibot (Ollama), LLM Connect, Craftium |
| **Craftium** | LGPL-2.1 per GitHub vs. "MIT" per README ([GitHub](https://github.com/mikelma/craftium)) | Python Gymnasium/PettingZoo over modified Luanti | Pixel observations + keyboard/mouse; sync mode ([arXiv](https://arxiv.org/html/2407.03969v2)) | Not documented | Inherits Luanti server | Lua env mods | Last push 2026-02-17 | LLaVa demo |
| **Minecraft + Mineflayer / Mindcraft** | MC proprietary; Mineflayer and Mindcraft MIT ([mineflayer](https://github.com/PrismarineJS/mineflayer), [mindcraft](https://github.com/mindcraft-bots/mindcraft)) | JS (Node) | Rich high-level JS bot API | Yes (Paper/Fabric; Docker `itzg`) ([Teramont](https://teramont.net/blog/minecraft-server-offline-mode-online-mode-false)) | Humans need paid Java client (est.) | CC:Tweaked Lua computers/turtles with HTTP/websocket ([tweaked.cc](https://tweaked.cc/module/http.html)) | Very active | Mindcraft, MineCollab, Voyager (stale), Project Sid |
| **MineLand** | MIT, archived ([GitHub](https://github.com/cocacola-lab/MineLand)) | Python + Mineflayer + Fabric | Gym-style + code actions | Yes; 64 agents ≈ 6.3 GB ([arXiv](https://arxiv.org/html/2403.19267v2)) | MC clients | via Mineflayer | Archived 2025-09 | Built-in "Alex" agent |
| **Veloren** | GPL-3.0 ([GitHub](https://github.com/veloren/veloren)) | Rust; WASM plugins | No bot API found | `server-cli` crate | Native clients | WASM plugins (server-side) | Active | None found |
| **Crafter / Craftax** | MIT ([crafter](https://github.com/danijar/crafter), [craftax](https://github.com/MichaelTMatthews/Craftax)) | Python / JAX | Gym API, text observations (Craftax) | Library | None (single-process) | None | Crafter stale; Craftax v1.7.0 on 2026-10-27 | Text rendering for language agents |
| **Screeps server** | ISC ([GitHub](https://github.com/screeps/screeps)) | Node.js; players write JS | User code each tick; CLI; MCP server exists ([LobeHub](https://lobehub.com/ru/mcp/ralphschuler-screeps-api-mcp)) | Yes (Node 22+) | Screeps client via Steam (est.) | Core mechanic: all units scripted | Pushed 2026-04; last release 2019 | None found |
| **FLE (Factorio)** | FLE MIT; Factorio proprietary ([GitHub](https://github.com/JackHopkins/factorio-learning-environment)) | Python REPL, MCP | Agents write Python programs | Headless since v0.3 ([v0.3.0](https://jackhopkins.github.io/factorio-learning-environment/versions/0.3.0.html)) | Factorio multiplayer ([v0.2](https://jackhopkins.github.io/factorio-learning-environment/release.0.2.0)) | Agents' Python is the scripting | Active 2026-09 | Built for LLMs (NeurIPS 2025) |
| **Bitburner** | Apache-2.0 + Commons Clause ([license](https://github.com/bitburner-official/bitburner-src/blob/dev/license.txt)) | TS; players write JS | In-game scripts | n/a (single-player, est.) | No | Core mechanic | Active | None found |
| **AI Town** | MIT ([GitHub](https://github.com/a16z-infra/ai-town)) | TS, Convex, PixiJS | Convex functions; Ollama | Self-hosted Docker | Browser | None | Pushed 2026-08 | Native (LLM agents chat) |
| **Custom 2D tile world** | Yours | Any (Py/TS) | Your websocket JSON API | Trivial | Browser/websocket | Embed Lua/JS sandbox | n/a | Build it |

### Inferences
- **Recommended path (inference):** a Luanti server on the M1 Max (native arm64), plus a VoxeLibre or Mineclonia content base, plus a custom `agent_bridge` mod. The bridge mod would:
  - expose per-agent observations (radius-limited nodes, entities, chat within N blocks) and actions (move-to, dig, place, craft, say);
  - use `request_http_api` long-polling to an orchestrator, or accept luantibot-style network clients run by remote Macs or PCs;
  - provide a sandboxed "computer" or "turtle" node, modeled on the luacontroller's limits (instruction cap, memory cap, heat), where agents write Lua at runtime;
  - add a gated "world-mod proposal" pipeline that installs agent-written mods on scheduled restarts, because registrations are load-time only.
  - Humans on Windows, Linux or Mac join with the stock Luanti client to watch.
- **Fallback if ecosystem matters more than openness:** an offline-mode Paper or Fabric server with Mindcraft-style Mineflayer agents and CC:Tweaked turtles. Expect about 6-10 GB for the server plus 50-100 headless bots (extrapolated from MineLand), which competes with local LLM memory on a 32 GB machine.
- **Bottleneck in every option:** local LLM inference, not the world. 50-100 agents sharing one or two local models means each agent acts every several seconds to minutes. Turn-based or slow-tick world designs (as in Craftium sync mode and MineLand's code steps) fit better than real-time ones.

### Gaps
- No head-to-head resource benchmark of Luanti vs. a Minecraft server with N headless bots on Apple Silicon exists in the sources found. The figures above are extrapolations.
- Community-size metrics (Discord or forum activity) for Luanti vs. Minecraft agent projects were not collected beyond GitHub stars and push dates.
