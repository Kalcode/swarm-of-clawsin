# Deep-simulation worlds and agent research environments as a base for a local LLM agent swarm

Research date: 2026-11-01. GitHub figures (stars, last push, license detected by GitHub, archived flag) were pulled live from the GitHub REST API on 2026-11-01. They are cited to each repo URL. "NOASSERTION"/"none" means GitHub could not detect a standard license file, not that the project has no license. Anything marked **[unverified]** comes from background knowledge and was not confirmed by a source during this session.

---

## Q1. Open-source deep simulations: which could serve as the world (CDDA/BN, KeeperRL, roguelikes, DF-likes, economy/strategy sims, Mindustry, SS14, Veloren, Luanti, etc.)?

### Takeaway
No open-source game combines Dwarf-Fortress-level emergent depth, a structured bot API, native multiplayer, and in-world programming. The strongest partial fits are: **Cataclysm: DDA / Bright Nights** (deepest crafting data, but single-player and no external API; BN has Lua), **Mindustry** (real in-world programming through logic processors that can drive units to mine and build, plus a headless multiplayer server, but it is a factory RTS, not a survival or social sim), **Luanti (Minetest) + Craftium** (open-source Minecraft-like with Lua modding, a client/server design, and a research fork that already supports multi-agent work and slow LLM agents), and **Space Station 14** (deep emergent multiplayer sim, MIT, but real-time and C#-heavy, with no player scripting confirmed). Mining CDDA's JSON as *content* for a custom world may be worth more than running CDDA itself.

### Cited Findings

**Cataclysm: Dark Days Ahead (CDDA)**
- Repo stats: 13,447 stars, last push 2026-11-01, C++. Very active. — [GitHub CleverRaven/Cataclysm-DDA](https://github.com/CleverRaven/Cataclysm-DDA)
- License: "Cataclysm is licensed under the Creative Commons Attribution-ShareAlike 3.0 Unported License." This is CC-BY-SA, not a software license, so derived data or content must be share-alike. — [CDDA LICENSE.txt](https://github.com/CleverRaven/Cataclysm-DDA/blob/master/LICENSE.txt)
- Data scale: the game uses "~half a million lines" of hand-written JSON for items, recipes, monsters and so on. That makes the crafting tree fully data-driven and moddable without C++. — [CDDA docs: The JSON Interface](https://docs.cataclysmdda.org/c++/JSON_INTERFACE.html)
- Lua was removed from mainline CDDA: PR #28572 "Get rid of Lua modding" was merged 2019-03-14, and #28711 "Removed Lua references from Android build files" followed on 2019-03-15. — [PR #28572](https://github.com/CleverRaven/Cataclysm-DDA/pull/28572); [PR #28711](https://github.com/CleverRaven/Cataclysm-DDA/pull/28711)
- Reason given in the forum proposal: the maintainer lacked time, contributors showed little interest in Lua modding, and the only known uses were Lua mapgen and a zombie-speed mod. — [CDDA Discourse "Remove lua?"](https://discourse.cataclysmdda.org/t/remove-lua/7492)
- A feature request to integrate an external human-behaviour or AI backend into the game (issue #67645) was closed as "not planned". Upstream is not pursuing AI hooks. — [CDDA issue #67645](https://github.com/CleverRaven/Cataclysm-DDA/issues/67645)
- Existing LLM integration: **CDDAi**, "AI-powered autonomous player" for CDDA. It combines ASCII terminal screen capture with JSON game-state parsing and makes LLM decisions through OpenRouter or the Anthropic API. MIT, 3 stars, last push 2026-01-04, so a hobby-scale proof of concept. — [GitHub rekon307/CDDAi](https://github.com/rekon307/CDDAi)

**Cataclysm: Bright Nights (BN)** and other forks
- BN repo (now `cataclysmbn/Cataclysm-BN`): 1,297 stars, last push 2026-11-01. Same CC-BY-SA 3.0 license for the game. Docs and scripts are AGPL-3.0-only. — [GitHub cataclysmbn/Cataclysm-BN](https://github.com/cataclysmbn/Cataclysm-BN); [BN LICENSE.txt](https://github.com/cataclysmbn/Cataclysm-BN/blob/main/LICENSE.txt)
- BN re-added Lua modding. A September 2023 changelog announced "Lua modding". — [r/cataclysmbn changelog Sep 16 2023 (mirror)](https://lr.in.psf.lt/r/cataclysmbn/comments/16k7f6p/cbn_changelog_september_16_2023_lua_modding)
- How BN Lua works: an in-game Lua console in the debug menu; running the game with `--lua-doc` generates `lua_doc.md` with the full API; example mods live in `data/mods/`. The guide notes some APIs (preload modification of JSON definitions, finalization) are still TODO. — [BN "Modding with Lua"](https://cataclysm-bn.pages.dev/mod/lua/tutorial/modding)
- Secondary source (AI-generated DeepWiki, lower reliability): Lua support is optional at compile time, `LUA_API_VERSION = 2`, load order `preload.lua → main.lua → finalize.lua`. — [DeepWiki: Cataclysm-BN Lua scripting](https://deepwiki.com/cataclysmbnteam/Cataclysm-BN/8.2-lua-scripting)
- Cataclysm: The Last Generation (TLG), another active fork: 432 stars, last push 2026-11-01. — [GitHub Cataclysm-TLG](https://github.com/Cataclysm-TLG/Cataclysm-TLG)

**Dwarf-Fortress-likes / colony sims (open source)**
- **KeeperRL** (dungeon-keeper/DF-like): GPL-2.0, C++, 1,012 stars. Last commit 2025-10-27 ("Add witch adventurer"), so about 12 months without commits. — [GitHub miki151/keeperrl](https://github.com/miki151/keeperrl)
- **Ingnomia** (Gnomoria-style colony sim): AGPL-3.0, C++, 276 stars, last push 2026-09-12. — [GitHub rschurade/Ingnomia](https://github.com/rschurade/Ingnomia)
- **Nox Futura** (Rust DF-like): GPL-3.0, 155 stars, last push 2022-06-17. Stale. — [GitHub thebracket/noxfutura](https://github.com/thebracket/noxfutura)
- **Unknown Horizons** (Anno-like economy sim): Python, 1,559 stars. Last release 2019.1 (2019-01-12), though maintenance PRs were merged in Sep–Oct 2026. — [GitHub unknown-horizons](https://github.com/unknown-horizons/unknown-horizons); [releases](https://github.com/unknown-horizons/unknown-horizons/releases)

**Classic roguelikes (open source; all single-player)**
- **Brogue CE**: AGPL-3.0, C, 1,513 stars, last push 2026-10-31. — [GitHub tmewett/BrogueCE](https://github.com/tmewett/BrogueCE)
- **Dungeon Crawl Stone Soup (DCSS)**: C++, 3,057 stars, last push 2026-11-01. — [GitHub crawl/crawl](https://github.com/crawl/crawl)
- DCSS has a **Webtiles websocket API**. The `dcss-api` Python/Rust wrapper supports logging in, starting a game and sending commands, targets stone_soup 0.29–0.31, and recommends a local server built with WEBTILES (rate limit of one command per 100 ms on public servers). — [PyPI dcss-api](https://pypi.org/project/dcss-api); [GitHub EricFecteau/dcss-api](https://github.com/EricFecteau/dcss-api/)
- `dcss-ai-wrapper`, "An API for Dungeon Crawl Stone Soup for Artificial Intelligence research": MIT, 47 stars, last push 2026-08-17. — [GitHub dtdannen/dcss-ai-wrapper](https://github.com/dtdannen/dcss-ai-wrapper)
- **Angband**: C, 1,576 stars, last push 2026-10-27. — [GitHub angband/angband](https://github.com/angband/angband)
- **Sil-Q**: last push 2026-06-18. — [GitHub backwardsEric/sil-q](https://github.com/backwardsEric/sil-q)
- **ToME 2** (the older "Troubles of Middle-earth", not Tales of Maj'Eyal): 112 stars, last push 2025-12-13. — [GitHub tome2/tome2](https://github.com/tome2/tome2)
- **HyperRogue**: GPL-2.0, 722 stars, last push 2026-09-17. — [GitHub zenorogue/hyperrogue](https://github.com/zenorogue/hyperrogue)

**Economy / strategy sims**
- **OpenTTD**: C++, 8,447 stars, last push 2026-11-01. — [GitHub OpenTTD/OpenTTD](https://github.com/OpenTTD/OpenTTD)
- **Simutrans**: 452 stars, last push 2026-08-01. — [GitHub aburch/simutrans](https://github.com/aburch/simutrans)
- **Unciv** (open Civ V clone): MPL-2.0, Kotlin, 11,518 stars, last push 2026-11-01. — [GitHub yairm210/Unciv](https://github.com/yairm210/Unciv)
- **Freeciv**: GPL-2.0, C, 1,626 stars, active. Freeciv-web: 2,215 stars, last push 2026-03-27. — [GitHub freeciv/freeciv](https://github.com/freeciv/freeciv); [GitHub freeciv/freeciv-web](https://github.com/freeciv/freeciv-web)
- **CivRealm**, "an interactive environment for the open-source strategy game Freeciv-web" (an agent-research API, including LLM agents per its ICLR 2024 paper **[paper not fetched]**): GPL-3.0, 165 stars, last push 2024-09-11. Stale. — [GitHub bigai-ai/civrealm](https://github.com/bigai-ai/civrealm)
- **OpenRCT2**: GPL-3.0, 16,529 stars, active. **Shapez CE**: GPL-3.0, 207 stars, active. **Wesnoth**: GPL-2.0, 6,969 stars, active. — [OpenRCT2](https://github.com/OpenRCT2/OpenRCT2); [shapez-community-edition](https://github.com/tobspr-games/shapez-community-edition); [Wesnoth](https://github.com/wesnoth/wesnoth)

**Mindustry (factory/RTS with in-world programming)**
- GPL-3.0, Java, 29,562 stars, last push 2026-11-01. The most-starred project in this survey. — [GitHub Anuken/Mindustry](https://github.com/Anuken/Mindustry)
- Mindustry Logic ("mlog"), added in v6, is an assembly-inspired language that "runs one instruction at a time". It can read block and unit info, control buildings and turrets, control units, use memory cells, draw on displays and print messages. Processor blocks: Micro, Logic, Hyper and World Processor. — [Mindustry wiki: Logic intro](https://mindustrygame.github.io/wiki/logic/0-introduction/)
- From the source (`LStatements.java`), the instruction set includes `ubind`, `ucontrol`, `uradar`, `ulocate`, `getblock`, `setblock`, `spawn`, `setrule`, `explosion`, `fetch`, `sync`, `setprop`, `makemarker`, `weatherset`, `spawnwave` and others. Several are marked `privileged()`, meaning World-Processor-only. — [Mindustry LStatements.java](https://github.com/Anuken/Mindustry/blob/master/core/src/mindustry/logic/LStatements.java)
- `ucontrol` subcommands (from `LUnitControl.java`): `move`, `approach`, `pathfind`, `boost`, `target`, `itemDrop`, `itemTake`, `payTake`, `mine`, `flag`, `build`, `deconstruct`, `getBlock`, `within`. Programs can make units mine, haul, build and deconstruct. — [Mindustry LUnitControl.java](https://github.com/Anuken/Mindustry/blob/master/core/src/mindustry/logic/LUnitControl.java)
- JavaScript mod scripting exists: `core/assets/scripts/` contains `base.js` and `global.js`. JVM plugins are the server-side path. — [Mindustry scripts dir](https://github.com/Anuken/Mindustry/tree/master/core/assets/scripts); [xpdustry/toxopid (Gradle plugin for mods/plugins)](https://github.com/xpdustry/toxopid)
- The headless dedicated server runs on the JVM (hosting-vendor source, moderate reliability). — [supercraft.host Mindustry server setup](https://supercraft.host/wiki/mindustry/server_setup/)
- **Mindcode**, a high-level language that compiles to mlog: MIT, 172 stars, last push 2026-11-01. — [GitHub cardillan/mindcode](https://github.com/cardillan/mindcode)

**Space Station 13/14**
- **SS14**: MIT code, C#, 3,895 stars, last push 2026-11-01. Some assets may be CC-BY-NC-SA 3.0. — [GitHub space-wizards/space-station-14](https://github.com/space-wizards/space-station-14); [license summary via project-awesome](https://project-awesome.org/r/space-wizards-space-station-14)
- **RobustToolbox** (SS14 engine): code contributed before 2019-03-13 is GPL-3, code after is MIT; images and models are CC-BY-SA 3.0 US. The engine needs the content repo to run. — [RobustToolbox legal.md](https://github.com/space-wizards/RobustToolbox/blob/master/legal.md)
- **tgstation** (SS13): AGPL-3.0, written in BYOND's DM language, 1,942 stars, active. — [GitHub tgstation/tgstation](https://github.com/tgstation/tgstation)

**Other multiplayer open worlds**
- **Veloren** (voxel RPG, Rust): GPL-3.0, 7,670 stars, last push 2026-10-30. — [GitHub veloren/veloren](https://github.com/veloren/veloren)
- **Unvanquished** (FPS/RTS): 1,131 stars, active. — [GitHub Unvanquished](https://github.com/Unvanquished/Unvanquished)
- **Luanti (formerly Minetest)**, "open source voxel game-creation platform with easy modding": C++, 13,803 stars, latest release 5.18.0 on 2026-10-29. — [GitHub luanti-org/luanti](https://github.com/luanti-org/luanti); [releases](https://github.com/luanti-org/luanti/releases)
- Luanti licensing: engine code is GNU LGPL (2.1 per license text) and media is CC BY-SA 3.0/4.0. — [Luanti LICENSE.txt](https://github.com/luanti-org/luanti/blob/master/LICENSE.txt)
- **Craftium**, a Luanti fork for agent research. It offers Gymnasium (single-agent) and PettingZoo (multi-agent) APIs, Lua API extensions for building environments, soft resets, and "Luanti client(s)/server synchronization for slow agents (e.g., LLMs or VLMs)". It claims "+2K steps per second more than Minecraft-based alternatives". ICML 2025 paper. The pre-built wheel shown is manylinux x86_64. 214 stars, last push 2026-02-17. — [GitHub mikelma/craftium](https://github.com/mikelma/craftium); [Craftium paper arXiv 2407.03969](https://arxiv.org/abs/2407.03969)

**Reference only (not open source)**
- Minecraft-based LLM agent work (Mindcraft, Voyager, Project Sid) relies on Mineflayer (MIT, 7,694 stars), but the Minecraft server is proprietary. — [GitHub PrismarineJS/mineflayer](https://github.com/PrismarineJS/mineflayer)

### Inferences
- **CDDA/BN as a running world is a poor fit for a swarm.** It is single-player (one avatar; NPCs are internal AI), it has no headless or bot API (CDDAi has to scrape the terminal screen), and mainline dropped Lua in 2019. BN's Lua could in principle expose game state and accept commands from inside, but making it multi-agent or networked would mean deep engine surgery. CDDA's JSON corpus (items, materials, recipes, qualities, tool requirements, mutations) is an excellent ready-made crafting ontology to import into a custom world. Mind CC-BY-SA 3.0: data derived from it must stay CC-BY-SA with attribution.
- **Mindustry is the only mainstream open-source game where in-game programming can act physically** (units mine, build, haul, and world processors can change the map). It is the closest existing analogue to "agents discover scripting and script the world". Its weaknesses for this use: no survival, social or hunger systems, no "senses" model, an RTS-camera player abstraction, and Java/JVM plugins as the only server-side bot path. An agent could plausibly write mlog (or Mindcode) to automate production, which makes a good "late-game" skill to test.
- **Luanti + Craftium is the most practical 3D "Minecraft-like" base.** It has a native client/server design (other home machines join as clients), a large Lua mod ecosystem, and a research fork already built for slow LLM agents in multi-agent settings. **[unverified]** In-world programming is available through community mods such as Mesecons "Luacontrollers" (sandboxed Lua in-game) and LWComputers/Digistuff. Downside: the default action space is low-level keyboard/mouse and pixels. For small text LLMs you would write a Lua mod exposing structured observations ("what's around me") and high-level actions ("walk to", "dig", "craft").
- **SS14 has the richest *emergent multiplayer* systems in this list.** **[unverified]** These include atmospherics, chemistry, power grids, medical, and a device-linking/signal system. But it is real-time, combat-heavy, round-based, C#/.NET, and needs a substantial engine. Treat it as inspiration rather than a base. SS13's tgstation had in-game programmable circuits and NTSL scripting in some codebases **[unverified]**, but DM/BYOND servers are Windows/Linux-centric **[unverified]**.
- **KeeperRL, Ingnomia and Nox Futura** are interesting DF-likes, but small or stale and lacking API hooks. They would need the same engine surgery as CDDA without the content depth.
- **Economy sims (OpenTTD, Simutrans, Unciv, Freeciv)** are deep in logistics and economics, not in survival or crafting. **[unverified]** OpenTTD and Simutrans have Squirrel-scripted AI and GameScript APIs, OpenTTD has a network "admin port", and Freeciv has a server/client protocol (CivRealm wraps it). These suit "civilization-scale" agents, not embodied ones.

### Gaps
- No maintained multiplayer fork of CDDA/BN turned up (not exhaustively searched). Historic "multiplayer" was shared-terminal hacks **[unverified]**.
- Tales of Maj'Eyal (ToME4) is not on GitHub. Its license (GPL-3 code, proprietary assets per background knowledge **[unverified]**) and API status were not checked.
- Licenses for DCSS (GPL-2+?), Angband (GPL-2/Moria dual?), Unknown Horizons (GPL-2?) and OpenTTD (GPL-2) were not confirmed; GitHub reported NOASSERTION/none.
- The Mindustry World Processor wiki page returned 404. World-processor capabilities are inferred from source-code statement names, not docs.
- macOS Apple Silicon support was not explicitly verified for SS14 server, Luanti server, Mindustry server (JVM, so very likely), Craftium (only Linux wheel shown), or BN with Lua.
- I found no performance data for dozens of external agents in any of these games.

---

## Q2. Agent research environments with crafting, survival or social depth: status and agent-friendliness

### Takeaway
The research environments have clean Python observation/action APIs, but most are either **single-agent** (NLE, MiniHack, Crafter, Craftax, TextWorld, Jericho, ScienceWorld, ALFWorld) or **built for RL pixel/tensor agents** (Melting Pot, Neural MMO, Overcooked). The LLM-native social simulators (Generative Agents, AI Town, Concordia, Sotopia) have shallow physical or crafting systems. Several important ones are now **archived or stale** (facebookresearch NLE, MiniHack, LIGHT, ParlAI, openai/neural-mmo, Voyager, Generative Agents repo, MineLand). The best "depth + multi-agent + open source" research platforms are **Craftium (Luanti)**, **Neural MMO (2.0 / NMMO3 in PufferLib)**, **Melting Pot** and **Concordia**'s Game-Master pattern.

### Cited Findings

**NetHack family**
- `facebookresearch/nle` is **archived** (last push 2024-05-06). Development continues at `NetHack-LE/nle`: 143 stars, last push 2026-10-31, release v1.3.0 on 2026-04-22. — [GitHub facebookresearch/nle](https://github.com/facebookresearch/nle); [GitHub NetHack-LE/nle](https://github.com/NetHack-LE/nle); [NLE releases](https://github.com/NetHack-LE/nle/releases)
- MiniHack is **archived**: Apache-2.0, 518 stars, last push 2025-02-12. — [GitHub facebookresearch/minihack](https://github.com/facebookresearch/minihack)
- BALROG (LLM/VLM agentic benchmark over BabyAI, Crafter, TextWorld, BabaIsAI, MiniHack, NetHack): MIT, 276 stars, last push 2026-04-09. Live leaderboard at balrogai.com, "updated weekly". — [GitHub balrog-ai/BALROG](https://github.com/balrog-ai/BALROG); [balrogai.com](https://balrogai.com/)

**Crafter / Craftax**
- Crafter (2D Minecraft-like survival/crafting benchmark): MIT, 605 stars, last push 2024-01-23. Frozen but stable. — [GitHub danijar/crafter](https://github.com/danijar/crafter)
- Craftax (JAX re-implementation plus a much harder "Full" version with NetHack-like dungeon floors; ICML 2024): MIT, 469 stars, last push 2026-10-27. — [GitHub MichaelTMatthews/Craftax](https://github.com/MichaelTMatthews/Craftax); [craftaxlm citation block on PyPI](https://pypi.org/project/craftaxlm/0.0.34/)
- PufferLib (MIT, 6,573 stars, last push 2026-10-14, default branch `5.0`) bundles C/CUDA "ocean" environments, including `craftax`, `craftax_classic`, `nethack` and `nmmo3`. — [GitHub PufferAI/PufferLib](https://github.com/PufferAI/PufferLib); [PufferLib ocean/nmmo3](https://github.com/PufferAI/PufferLib/tree/5.0/ocean/nmmo3)

**Neural MMO**
- `openai/neural-mmo` is **archived** (last push 2023-07). `NeuralMMO/environment`: MIT, 579 stars, last push 2024-08-30. Stale. — [GitHub openai/neural-mmo](https://github.com/openai/neural-mmo); [GitHub NeuralMMO/environment](https://github.com/NeuralMMO/environment)
- Neural MMO 2.0: standard configuration of **128 agents** on procedurally generated maps, a flexible task/reward definition system, and a full rewrite with "three-fold improved performance". — [arXiv 2311.03736](https://arxiv.org/abs/2311.03736)
- NMMO3 lives in PufferLib as a C/CUDA environment (`ocean/nmmo3/nmmo3.h`, `nmmo3.cu`, `config/nmmo3.ini`). A secondary source describes a default 512×512 map and 26 discrete actions. — [PufferLib repo tree](https://github.com/PufferAI/PufferLib/tree/5.0/ocean/nmmo3); [DeepWiki (fork, secondary)](https://deepwiki.com/thegovind/pufferlib/6.10-other-ocean-environments)

**Melting Pot / Concordia (DeepMind)**
- Melting Pot: Apache-2.0, 903 stars, release v2.4.1 on 2026-09-30. "Over 50" multi-agent substrates and "over 256" test scenarios for social generalization (cooperation, competition, trust). Built on DeepMind Lab2D (`dmlab2d`) prebuilt wheels; `pip install dm-meltingpot`. — [GitHub google-deepmind/meltingpot](https://github.com/google-deepmind/meltingpot)
- Concordia, "a library for generative social simulation": Apache-2.0, 1,848 stars, last push 2026-11-01. A **Game Master** (inspired by tabletop RPGs) simulates the environment: agents state intended actions in natural language, and the GM checks plausibility and describes their effects in a physically or digitally grounded world. — [GitHub google-deepmind/concordia](https://github.com/google-deepmind/concordia); [arXiv 2312.03664](https://arxiv.org/abs/2312.03664)

**Text-game environments**
- TextWorld: 1,457 stars, last push 2026-11-01. Jericho (Z-machine text adventures): GPL-2.0, 341 stars, active. ScienceWorld: Apache-2.0, Scala, 401 stars, last push 2026-08-20. ALFWorld: MIT, 902 stars, last push 2026-02-08. — [TextWorld](https://github.com/microsoft/TextWorld); [Jericho](https://github.com/microsoft/jericho); [ScienceWorld](https://github.com/allenai/ScienceWorld); [ALFWorld](https://github.com/alfworld/alfworld)
- LIGHT (Facebook text fantasy world) is **archived**: 72 stars, last push 2023-09. ParlAI is also **archived**. — [GitHub facebookresearch/LIGHT](https://github.com/facebookresearch/LIGHT); [GitHub facebookresearch/ParlAI](https://github.com/facebookresearch/ParlAI)
- TextArena (competitive text games for LLM eval/RL): MIT, 436 stars, last push 2026-10-05. Sotopia (social-interaction environment, ICLR 2024): MIT, 341 stars, last push 2026-06-05. — [TextArena](https://github.com/TextArena/TextArena); [Sotopia](https://github.com/sotopia-lab/sotopia)
- Overcooked-AI: MIT, 1,028 stars, last push 2025-03-22. — [GitHub HumanCompatibleAI/overcooked_ai](https://github.com/HumanCompatibleAI/overcooked_ai)

**LLM-native social worlds ("Smallville" lineage)**
- Generative Agents (Smallville): Apache-2.0, 22,323 stars, last push 2024-08-05. Stale. — [GitHub joonspk-research/generative_agents](https://github.com/joonspk-research/generative_agents)
- AI Town (a16z): MIT, TypeScript, 10,733 stars, last push 2026-08-26. — [GitHub a16z-infra/ai-town](https://github.com/a16z-infra/ai-town)

**Minecraft-family LLM agent projects**
- Mindcraft (LLM agents in Minecraft via Mineflayer): MIT, 5,953 stars, last push 2026-10-27. — [GitHub mindcraft-bots/mindcraft](https://github.com/mindcraft-bots/mindcraft)
- Voyager: MIT, 7,306 stars, last push 2024-04-03. Stale. — [GitHub MineDojo/Voyager](https://github.com/MineDojo/Voyager)
- Project Sid (Altera): simulations from about 10 to over 1,000 agents in Minecraft using the PIANO architecture. It reports agents developing specialized roles, following and changing shared rules, and passing on cultural and religious practices. Repo: 1,389 stars, last push 2024-11-04. — [arXiv 2411.00114](https://arxiv.org/abs/2411.00114); [GitHub altera-al/project-sid](https://github.com/altera-al/project-sid)
- MineLand ("Simulating Large-Scale Multi-Agent Interactions with Limited Multimodal Senses and Physical Needs") is **archived**: MIT, 113 stars, last push 2025-09-30. — [GitHub cocacola-lab/MineLand](https://github.com/cocacola-lab/MineLand)
- Craftium (Luanti) offers a PettingZoo multi-agent API and client/server synchronization for slow LLM/VLM agents (see Q1). — [GitHub mikelma/craftium](https://github.com/mikelma/craftium)

### Inferences
- **For an LLM swarm, the useful research assets are mostly *design patterns* and *eval harnesses*, not worlds to inhabit.** BALROG's harness (text observation, natural-language action, progress metric) is a good template for an agent loop. Concordia's Game Master is the cleanest pattern for **open-ended invention**: a deterministic simulation handles physics, crafting and inventories, and an LLM "GM" adjudicates novel actions or inventions that fall outside the rules.
- **Neural MMO is the closest research analogue to "many agents, resources, professions, markets"**, but its API is tensor-shaped for RL, and the active code is now NMMO3 in C/CUDA inside PufferLib. CUDA is not native on Apple Silicon. **[unverified]** The C path may build CPU-only.
- **Melting Pot** is great for social-dilemma evaluation but uses pixel observations and small grid substrates. **[unverified]** Its dmlab2d wheel availability for macOS arm64 is uncertain.
- **Project Sid is the best evidence that a "civilization" can emerge from LLM agents in a crafting world at 1,000-agent scale.** It used a proprietary game (Minecraft) and cloud LLMs, and the repo is not a runnable framework (README/paper only per its last-push date).
- **Craftium is the only maintained, fully open-source, multi-agent, 3D crafting research environment found that explicitly supports slow LLM agents.** It is the most direct "repurpose" candidate among research tools, subject to verifying macOS builds.

### Gaps
- I did not verify whether NLE, Melting Pot (dmlab2d), Craftium or PufferLib's NMMO3 build natively on macOS arm64.
- I did not find Concordia documentation on local-LLM support. The arXiv abstract mentions only cloud models. **[unverified]** The current codebase has pluggable language-model wrappers, including Ollama.
- The Neural MMO 2.0 abstract does not confirm its specific systems (foraging, combat, professions, exchange). **[unverified]** Background knowledge says it has all of these.

---

## Q3. The text/MUD/MOO route: is a MUD or MOO with in-world programming the ideal world for text-native LLM agents?

### Takeaway
The text route is the most LLM-native option and the only one with mature, decades-old **in-world programming**. In MOOs (LambdaMOO, ToastStunt, mooR), users create objects and write verbs *while connected*, which maps almost exactly onto "discover scripting and script the world". **Evennia** (Python, BSD-3, active) is the most practical modern engine. It already ships an LLM NPC contrib with async LLM calls and an "in-game Python" contrib that lets trusted users attach Python callbacks in-world. It also has native telnet/websocket networking so remote home machines can join. What a MUD lacks is physical simulation depth: crafting, materials, ecology and senses must be built on top.

### Cited Findings

**MOO family (in-world programming)**
- In a MOO, users "can program inside the server, which changes the environment for everyone". They create rooms and objects, generic objects others can reuse, and interface changes. Most commands are handled by procedures called **verbs** written in the MOO language. Shared verb libraries are called Utilities. — [Wikipedia: MOO](https://en.wikipedia.org/wiki/MOO)
- History: Stephen White's first MOO server came out in May 1990. Pavel Curtis (Xerox PARC) released LambdaMOO on 1990-10-30 and opened it publicly in February 1991. LambdaMOO "continues, though server development has slowed". The **Wizard** flag grants near-total database rights. — [Wikipedia: MOO](https://en.wikipedia.org/wiki/MOO)
- In MOO, all code lives in **verbs attached to database objects** rather than in free functions. Cores (LambdaCore, JHCore, ToastCore) are the starting object databases. — [mooR book: The MOO programming language](https://timbran.codeberg.page/moor-book-html/the-moo-programming-language.html); [mooR book: Understanding MOO cores](https://timbran.codeberg.page/moor-book-html/the-system/understanding-moo-cores.html)
- Stunt/ToastStunt (LambdaMOO forks) add multiple inheritance, anonymous objects, HTTP, JSON↔MOO translation, a map datatype and a RESTful interface. ToastStunt also adds 64-bit integers and SQLite. — [GitHub toddsundsted/stunt](https://github.com/toddsundsted/stunt); [Wikipedia: MOO](https://en.wikipedia.org/wiki/MOO)
- Repos: ToastStunt is 95 stars, last push 2026-10-16. A LambdaMOO repo (`wrog/lambdamoo`) is 93 stars, last push 2026-11-01. — [GitHub lisdude/toaststunt](https://github.com/lisdude/toaststunt); [GitHub wrog/lambdamoo](https://github.com/wrog/lambdamoo)
- **mooR**: "A system for building shared, programmable, online spaces. Compatible with LambdaMOO. Built for the future." AGPL-3.0, Rust, 219 stars, last push 2026-11-01. It does not support ToastStunt WAIFs and "will mostly reject a textdump from ToastStunt". — [GitHub timbran-project/moor](https://github.com/timbran-project/moor); [mooR book](https://timbran.codeberg.page/moor-book-html/the-system/understanding-moo-cores.html)

**LPMud / other MUD drivers (in-world LPC programming)**
- FluffOS ("Actively maintained LPMUD driver (LPC interpreter, MudOS fork)"): 465 stars, last push 2026-11-01. LDMud: 157 stars, last push 2026-10-08. DGD: AGPL-3.0, 111 stars, last push 2026-08-31. CoffeeMud (Java, Apache-2.0, "full featured, mature MUD"): 237 stars, last push 2026-11-01. — [FluffOS](https://github.com/fluffos/fluffos); [LDMud](https://github.com/ldmud/ldmud); [DGD](https://github.com/dworkin/dgd); [CoffeeMud](https://github.com/bozimmerman/CoffeeMud)

**Evennia**
- Evennia: BSD-3-Clause, Python, 2,117 stars, last push 2026-10-24. — [GitHub evennia/evennia](https://github.com/evennia/evennia)
- **LLM contrib**: `LLMClient` sends prompts to a local or remote LLM server, and `LLMNPC` is talked to with `talk <npc> <msg>`. All calls are **asynchronous**, so a slow LLM does not stall the server. The default backend is text-generation-webui on port 5000 (`LLM_HOST`, `LLM_PATH` configurable). Per-NPC prompt prefix and capped chat memory. — [Evennia docs: LLM contrib (6.x)](https://www.evennia.com/docs/6.x/Contribs/Contrib-Llm.html); [llm_npc source](https://evennia.com/docs/latest/_modules/evennia/contrib/rpg/llm/llm_npc.html)
- **In-game Python contrib**: builders attach Python callbacks to objects, rooms, exits and characters through events, using the in-game `call` command. The docs warn it "will run arbitrary Python code without much restriction". Permission groups decide who can edit callbacks with or without admin validation. — [Evennia docs: In-game Python](https://www.evennia.com/docs/latest/Contribs/Contrib-Ingame-Python.html)

**Existing LLM-agents-in-MUD projects**
- **LLMUD**, "A shared text world where language-model agents and people explore, collaborate, and tell stories": built on **Evennia** (Midgaard sample world). Agents connect over Telnet port 4000 and humans use the web client on 4001. Local models via **Ollama** (sample `llama3.2:3b` profile) or OpenAI. Each agent needs its own account and profile and gets room text, returning **one printable command per turn** (multi-line or empty output is rejected). The README advises judging success by world state, not agent claims. It is a prototype with no scoring or reset. MIT, 1 star, last push 2026-09-21. — [GitHub nvillar/llmud](https://github.com/nvillar/llmud)
- Ian Bicking's "Intra" (July 2025, a single-player LLM text adventure) says a MUD built on these techniques "could be really great". He flags **latency and concurrency** as the first problems with multiple users. — [Intra design notes](https://ianbicking.org/blog/2025/07/intra-llm-text-adventure)
- I found little peer-reviewed research on LLM agents in MUDs specifically. Searches mostly returned Minecraft-agent and text-world-model papers. — [search context: A Survey on LLM-Based Game Agents, arXiv 2404.02039](https://arxiv.org/pdf/2404.02039)

### Inferences
- **A MOO is the closest existing system to the user's "agents discover scripting, then modify the world" goal.** The programming language *is* the world's extension mechanism, objects and verbs persist in a shared database, permissions (player → programmer → wizard) give a natural "tech tree" for code privileges, and **[unverified]** classic MOO servers enforce per-task tick and seconds limits plus object quotas, a built-in sandbox against runaway agent code. mooR (Rust, active, LambdaMOO-compatible) is the most modern MOO server. ToastStunt adds JSON/HTTP, which helps bridge to agent processes.
- **Evennia is the most pragmatic engine.** It is Python, so the agent harness, world simulation and LLM tooling can share a language. It is async (Twisted), has telnet, websocket and web-client networking built in for remote home machines, and has persistent Django-backed objects. Its in-game Python contrib is *unsandboxed*, so agent-authored code would need a custom sandbox such as RestrictedPython, a WASM or Lua sandbox, or a small purpose-built DSL.
- **The text route plays to small models' strengths (text in, short command out) and avoids their worst weakness (vision; see Q5).** LLMUD shows a 3B Ollama model can be wired into Evennia, but it reports no capability results.
- **Main risks:** (1) shallow physics and crafting unless built, though CDDA JSON could seed materials and recipes; (2) MUD commands are free-text, so small models need a constrained command grammar or tool-calling schema; (3) a "must walk to talk" design is natural in MUDs (say/emote is room-scoped), but "senses" (sight radius, hearing through walls, smell) need to be added.

### Gaps
- MOO per-task tick and second limits and quota mechanics were not confirmed from a source this session (the Wikipedia article does not cover them).
- I found no project running *many* LLM agents that write MOO verbs, and no benchmark of LLMs writing MOO or LPC code.
- I did not measure Evennia's scalability to dozens of concurrent agent connections. **[unverified]** Background: Evennia handles hundreds of connections easily, and the LLM inference would be the bottleneck.

---

## Q4. Per-candidate comparison: license, language, programmatic observation/action, headless/server, multi-agent, network play, depth, in-world code, activity, LLM integrations

### Takeaway
Ranked by fit for "many local-LLM agents in a deep, networked, scriptable world": **(1) a custom world on Evennia or mooR** (LLM-native, in-world code, networking built in; depth must be built), **(2) Luanti/Craftium** (3D crafting, Lua, client/server, multi-agent research hooks; needs a structured text API layer), **(3) Mindustry** (real in-world programming plus headless multiplayer server; wrong genre), **(4) CDDA/BN** (best crafting content; worst agent and multiplayer story). The research environments (NLE, Crafter/Craftax, Melting Pot, NMMO) are better as benchmarks than as a home world.

### Cited Findings
The matrix below summarizes facts cited in Q1–Q3. Row facts carry the citations given there. Cells marked **[u]** are unverified background knowledge, and "build" means you would have to write it.

| Candidate | License (verified) | Lang | Obs/action API today | Headless / server | Multi-agent / network | Depth (crafting/emergence) | Agent-written code in world | Activity (2026) | Existing LLM integration |
|---|---|---|---|---|---|---|---|---|---|
| CDDA ([repo](https://github.com/CleverRaven/Cataclysm-DDA)) | CC-BY-SA 3.0 | C++ | None. Screen-scrape + JSON save parse (CDDAi) | No [u] | Single-player only [u] | Very high: ~500k lines JSON items/recipes | No (Lua removed 2019, [PR](https://github.com/CleverRaven/Cataclysm-DDA/pull/28572)) | Very active | CDDAi (hobby) |
| Cataclysm-BN ([repo](https://github.com/cataclysmbn/Cataclysm-BN)) | CC-BY-SA 3.0 (+AGPL docs) | C++/Lua | Lua mods + in-game Lua console ([doc](https://cataclysm-bn.pages.dev/mod/lua/tutorial/modding)) | No [u] | Single-player [u] | Very high | Lua, but for modders, not in-fiction | Active | None found |
| Mindustry ([repo](https://github.com/Anuken/Mindustry)) | GPL-3.0 | Java | JVM plugins; mlog processors; JS mods | Yes, JVM headless server | Native multiplayer server | Medium: logistics/factory, no survival or social | **Yes**: mlog processors control units (mine/build), world processor edits map | Very active (29.5k stars) | None found |
| Luanti ([repo](https://github.com/luanti-org/luanti)) | LGPL-2.1 code, CC-BY-SA media | C++/Lua | Lua mod API (server-side) | Yes, dedicated server [u] | Native client/server multiplayer | Medium-high: voxel crafting, games such as Mineclonia [u] | Via mods (e.g., Mesecons Luacontroller) [u] | Very active (5.18.0, 2026-10-29) | Via Craftium |
| Craftium ([repo](https://github.com/mikelma/craftium)) | GitHub: NOASSERTION (Luanti fork) | C++/Lua/Python | Gymnasium + PettingZoo (pixels + actions) | Yes | **Multi-agent**, sync for slow LLM agents | As Luanti | Lua env authoring | Moderate (last push 2026-02) | Designed for LLM/VLM agents |
| SS14 ([repo](https://github.com/space-wizards/space-station-14)) | MIT code (RT: MIT post-2019), CC-BY-SA / some NC assets | C# | Build (server-side systems) | Yes [u] | Native multiplayer (dozens of players) [u] | Very high emergent systems [u] | Not confirmed | Very active | None found |
| Veloren ([repo](https://github.com/veloren/veloren)) | GPL-3.0 | Rust | Build | Yes [u] | Native MMO-style server [u] | Medium (RPG, crafting) [u] | No [u] | Active | None found |
| KeeperRL ([repo](https://github.com/miki151/keeperrl)) | GPL-2.0 | C++ | Build | No [u] | Single-player [u] | High (DF-like) | No | Slowing (last commit 2025-10) | None |
| Ingnomia ([repo](https://github.com/rschurade/Ingnomia)) | AGPL-3.0 | C++ | Build | No [u] | Single-player [u] | Medium-high (colony) | No | Low (2026-09) | None |
| DCSS ([repo](https://github.com/crawl/crawl)) | NOASSERTION (GPL-2+ [u]) | C++/Lua | **Webtiles websocket JSON** ([dcss-api](https://github.com/EricFecteau/dcss-api/)) | Yes (webtiles server) | Many single-player games on one server; no shared world | Medium (combat roguelike, no crafting) | Lua scripting (bots such as qw) [u] | Very active | dcss-ai-wrapper (research) |
| Brogue CE / Angband / Sil-Q | AGPL-3.0 / none / none | C | None (terminal) | No | Single-player | Medium (no crafting) | No | Active | None |
| NLE / MiniHack ([NLE](https://github.com/NetHack-LE/nle)) | NOASSERTION (NetHack GPL [u]) / Apache-2.0 | C/Python | Gym API, text + glyph obs | Yes (library) | Single-agent | Very high (NetHack) | No | NLE active again; MiniHack archived | BALROG harness |
| Crafter / Craftax | MIT | Python/JAX | Gym API; Craftax has text wrappers (craftaxlm) | Yes | Single-agent | Medium (survival + tech tree) | No | Crafter frozen; Craftax active | BALROG, craftaxlm |
| Neural MMO 2 / NMMO3 | MIT | Python / C+CUDA | PettingZoo-style tensors | Yes | **128+ agents**, single process | Medium (forage, combat, trade [u]) | No | NMMO2 stale; NMMO3 in PufferLib | None found |
| Melting Pot ([repo](https://github.com/google-deepmind/meltingpot)) | Apache-2.0 | Python/Lua (dmlab2d) | dm_env, pixels | Yes | Multi-agent (substrates) | Low-medium (social dilemmas) | No | Active (v2.4.1, 2026-09) | Concordia (same org) [u] |
| Concordia ([repo](https://github.com/google-deepmind/concordia)) | Apache-2.0 | Python | NL actions adjudicated by LLM Game Master | Library | Multi-agent | Whatever the GM imagines (ungrounded) | N/A | Very active | Native (LLM-based) |
| Generative Agents / AI Town | Apache-2.0 / MIT | Python / TS | Custom | Server (AI Town) | Multi-agent (25 in Smallville [u]) | Low (social only) | No | GA stale; AI Town moderate | Native |
| Evennia ([repo](https://github.com/evennia/evennia)) | BSD-3 | Python | Text (telnet/websocket); Python API server-side | Yes | Native multi-user, network | Whatever you build | **In-game Python contrib** (unsandboxed) | Active | LLM contrib; LLMUD |
| mooR / ToastStunt / LambdaMOO | AGPL-3.0 / none / none | Rust / C++ / C | Text (telnet); ToastStunt JSON/HTTP | Yes | Native multi-user, network | Whatever you build | **Yes, core design: in-world verbs** | mooR very active; others maintained | None found |
| Freeciv + CivRealm | GPL-2.0 / GPL-3.0 | C / Python | CivRealm Gym-style API | Yes (server) | Multi-player | Civ-scale strategy | No | Freeciv active; CivRealm stale (2024-09) | CivRealm LLM baselines [u] |

### Inferences
- **Network play for extra home machines:** Evennia, MOOs, Luanti, Mindustry, SS14, Veloren and Freeciv all have native client/server networking. That way "other home computers join as clients running more agents" means each machine runs agent processes that connect as ordinary players, the cleanest topology. CDDA, BN, KeeperRL, Ingnomia and the roguelikes have no such path.
- **Performance with dozens of agents** will almost certainly be limited by LLM inference on the M1 Max, not by any of these servers (all handle dozens of human players [u]). The world should therefore be **turn- or tick-based with asynchronous agent actions** (as Evennia's async LLM contrib and Craftium's slow-agent sync both assume), not real-time like SS14 or Mindustry combat.
- **Build-vs-repurpose:** repurposing an existing game buys depth but costs a structured API layer *and* fighting the game's player abstraction (camera, keyboard, real time). A custom world on Evennia or mooR, or a lightweight custom tick engine, with content seeded from CDDA's CC-BY-SA JSON and in-world scripting from a MOO-style verb system or a sandboxed language, is likely less total work for this specific goal (estimate).

### Gaps
- Several matrix cells (headless capability, multiplayer limits, scripting mods) are background knowledge, not verified this session; they are marked [u].
- I made no hands-on macOS build tests.

---

## Q5. How LLM agents perform in these environments, and what that implies about world difficulty for small local models

### Takeaway
Small local models perform very poorly in raw game environments. On BALROG, Llama-3.1-8B averages **15.1%** progress and Qwen-2.5-7B **7.8%**, and **every model at or below 70B scores ≤0.4% on NetHack**. Even the best 2026 frontier models reach only **~13% on NetHack**, while doing much better on simple grid worlds (BabyAI ~100%) and Crafter (~55–77%). Vision makes things *worse*. For a swarm of 7–32B local models, the world must expose **structured text observations, explicit affordances and high-level actions**, with difficulty that grows gradually. Raw NetHack/CDDA-style keystroke interfaces are out of reach.

### Cited Findings
- BALROG abstract: models "partly succeed on easier games but struggle significantly on harder ones". The most notable weakness is vision, where several models "perform worse when visual representations of the environments are provided". NetHack "may take years to master" for humans. — [arXiv 2411.13543](https://arxiv.org/abs/2411.13543)
- BALROG leaderboard, language-only, average progress % (BabyAI / Crafter / TextWorld / BabaIsAI / MiniHack / NetHack), as listed on the live page (fetched 2026-11-01): — [balrogai.com](https://balrogai.com/)
  - Top (dated Sep 2026 on page): GPT-6-Astra-Max **68.3** (100 / 76.8 / 54.5 / 100 / 65.0 / **13.2**). Claude-Opus-5-Max **63.4** (100 / 68.2 / 71.6 / 95.8 / 37.5 / **7.3**). Gemini-3.1-Pro **56.9** (NetHack 3.0).
  - Mid: Grok-4 43.6 (NetHack 1.8). Claude-Opus-4.5 43.5 (NetHack 2.0). DeepSeek-R1 34.9 (NetHack 1.4). GPT-4o 32.3 (NetHack 0.4).
  - Open/local-sized models: Llama-3.1-70B **27.9** (Crafter 31.2, NetHack 0.3). Llama-3.3-70B 23.0. **DeepSeek-R1-Distill-Qwen-32B 19.5** (Crafter 15.0, NetHack 0.7). Mistral-Nemo-12B 17.6 (Crafter 27.7). Llama-3.2-11B 16.8. Qwen2.5-72B 16.2. **Llama-3.1-8B 15.1** (BabyAI 36, Crafter 25.5, TextWorld 6.1, MiniHack 5.0, **NetHack 0.0**). Phi-4 11.6. Llama-3.2-3B 10.1. **Qwen-2.5-7B 7.8** (Crafter 16.4, NetHack 0.0). Llama-3.2-1B 6.6.
  - Vision-language table: the best (Gemini-2.5-Pro) is only 35.7. Qwen2-VL-7B scores 4.4 and Llama-3.2-11B-vision 8.4, below their text-only scores.
  - Note: the leaderboard contains no 2025–2026 small open models (e.g., Qwen3, Gemma 3), so current small-model performance is likely somewhat higher than these 2024-era entries (inference, not verified).
- Craftax LLM results (craftaxlm wrapper, unreviewed and methodology-varying): early ReAct results put gpt-4o at **29.6%** and gpt-4o-mini at 18.4% on Craftax-Classic, and gpt-4o-mini at **2.9% on Craftax-Full**. A later protocol (5 rollouts, 300-action cap) gives claude-3.5-sonnet 17.8% and o3-mini 12.6% on Classic. — [PyPI craftaxlm](https://pypi.org/project/craftaxlm/0.0.34/); [science.ecosyste.ms entry](https://science.ecosyste.ms/projects/10645)
- Mindcraft community fine-tunes: a developer fine-tuning Qwen2.5, Gemma 2 and Llama 3.2 for Mindcraft says untuned small models are mostly "slow, innaccurate, and not as smart". One note reports a Qwen-based tuned model took **~2 minutes to craft a wooden pickaxe**. The developer warns standard benchmarks don't apply. — [HF Sweaterdog/MindCraft-LLM-tuning](https://huggingface.co/Sweaterdog/MindCraft-LLM-tuning); [HF Andy-3.6-small](https://huggingface.co/Sweaterdog/Andy-3.6-small)
- Project Sid got emergent specialization, rules and culture at 10–1,000+ agents in Minecraft (models not named in the abstract). — [arXiv 2411.00114](https://arxiv.org/abs/2411.00114)
- LLMUD's advice: "define success by world state rather than by an agent's claims". In a text world, the world, not the model, keeps track of what is real. — [GitHub nvillar/llmud](https://github.com/nvillar/llmud)

### Inferences
- **Difficulty target:** small models do reasonably on BabyAI-like tasks (short horizon, clear goals, small action sets) and on Crafter-like tech trees (Llama-3.1-8B about 25% Crafter progress). They fail on NetHack-like depth (huge action space, hidden state, long horizon, domain knowledge). The world should look like **Crafter-depth per step with NetHack/DF-depth reachable only through accumulation**: many simple, legible mechanics whose combinations produce depth, not one opaque, punishing system.
- **Interface design matters more than world choice.** Concretely: (1) text observations listing visible entities, distances, inventory and available actions or recipes; (2) a small, typed tool-call action schema (`move_to`, `pick_up`, `craft(recipe)`, `say(text)`, `use(item, target)`) instead of raw keystrokes; (3) a "what can I do here?" affordance query; (4) persistent memory and notes stored *in the world* (writable signs, books, journals), which also gives a natural on-ramp toward scripting.
- **Avoid vision for small local models.** BALROG shows VLMs score below their text-only counterparts, and VLM inference is costlier on an M1 Max. This argues against Craftium's pixel interface unless a text-observation mod is written.
- **Invention and scripting are the hardest part.** Writing *working* code in a novel in-world language is beyond what small models reliably do without scaffolding. Use a familiar language (a Python or Lua subset, or a MOO-like syntax with docs available in-world), gate it behind in-world discovery (e.g., finding a "manual" object), sandbox it with tick and memory limits, and validate by world-state effects. A hybrid "deterministic rules + LLM Game Master for out-of-rule inventions" (the Concordia pattern) can let agents *propose* inventions that small models could not *implement* as code.
- **Concurrency estimate (not sourced):** on a 32 GB M1 Max, realistic concurrent inference is a handful of parallel streams of a 7–14B quantized model, so "dozens of agents" implies agents act every few seconds to minutes. A tick-based or async world, plus distributing agents to other home machines over the network, is necessary.

### Gaps
- BALROG has no entries for current-generation small open models (Qwen3/3.5, Gemma 3/4, Llama 4, Mistral Small 3.x). No source gave 2025–2026 small-model results on these games.
- I found no controlled study of multi-agent LLM swarms with *local* models in any crafting world, and no study of LLMs learning an in-world scripting language.
- I found no published throughput figures for running many concurrent local-LLM agents on Apple Silicon (out of scope here; likely covered by another researcher).
