# Gaming PC setup: the GPU for Swarm World's minds

For whoever sets up the Windows gaming PC: the user, or a Claude Code session running on it.

**Why:** the MacBook Pro hosts the live world (192.168.50.95:7777). Running model tests on the same Mac overloads it.
This PC lends its GPU to the home network through Ollama. The Claude session on the Mac (`swarm-of-clawsin-d2`)
then benchmarks candidate models against it remotely and, once a winner is picked, points the live world's minds at it.
Nothing from this repo has to run on the PC, and the PC never joins the live world on its own (see "Do not").

## 1. Report the hardware

```powershell
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv
(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB
(Get-CimInstance Win32_OperatingSystem).Caption
Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -like "192.168.*" } | Select-Object IPAddress, InterfaceAlias
```

## 2. Install Ollama and serve it to the home network

```powershell
winget install Ollama.Ollama
# Settings Ollama reads at start-up (user environment variables):
setx OLLAMA_HOST "0.0.0.0:11434"      # listen on the network, not only localhost
setx OLLAMA_NUM_PARALLEL "8"          # creatures think at the same time; 8 requests share one loaded model
setx OLLAMA_CONTEXT_LENGTH "8192"     # prompts run ~3-5k tokens; the default window would silently cut them
setx OLLAMA_FLASH_ATTENTION "1"
setx OLLAMA_KV_CACHE_TYPE "q8_0"      # halves the memory each parallel request needs
setx OLLAMA_MAX_LOADED_MODELS "2"     # two minds side by side for mixed populations
setx OLLAMA_KEEP_ALIVE "24h"          # don't unload between thoughts
```

Quit Ollama from the system tray and start it again so it picks these up. Then, in an **administrator** PowerShell,
allow other machines in the house (only the local subnet) to reach it:

```powershell
New-NetFirewallRule -DisplayName "Ollama (home network)" -Direction Inbound -Protocol TCP -LocalPort 11434 -RemoteAddress LocalSubnet -Action Allow
```

## 3. Pull the candidate models

The Mac's Gemma 4 E4B fails at basic actions (see [issue 003](../issues/003-replace-gemma.md)). Pull what fits the GPU's
memory. Tag names change; confirm each on [ollama.com/library](https://ollama.com/library) before pulling.

| GPU memory | Pull |
|---|---|
| 24 GB or more | `gpt-oss:20b`, `qwen3.5:9b`, `ministral-3:8b` |
| 16 GB | `gpt-oss:20b`, `qwen3.5:9b` (one loaded at a time) |
| 12 GB | `qwen3.5:9b`, `ministral-3:8b` |
| 8 GB | `qwen3.5:4b` |

Warm each one up and check that it sits fully on the GPU:

```powershell
ollama run gpt-oss:20b "Say hi in five words."
ollama ps        # PROCESSOR should read "100% GPU". If part is on CPU, lower OLLAMA_NUM_PARALLEL to 4 and restart Ollama.
```

## 4. Check the Mac can reach it, then report back

From the Mac (or ask the Mac session to run it): `curl http://<PC-IP>:11434/v1/models`.

Report back to the user, or to the Mac session by message if Remote Control is on in both (`SendMessage` to
`swarm-of-clawsin-d2`): the PC's IP, GPU and memory, models pulled, and the `ollama ps` output.

## What happens next (done from the Mac)

1. Benchmark each candidate against the PC: `uv run python bench/world_bench.py --base-url http://<PC-IP>:11434/v1 --model gpt-oss:20b --episodes 3`.
   The benchmark's little world runs on the Mac's CPU; all model work happens here on the PC.
2. The user picks the winner. The live world's brain node then either points at this PC
   (`--model-server http://<PC-IP>:11434/v1`), or the PC runs its own node:
   `.\join.ps1 --token <token> --server ws://192.168.50.95:7777 --model gpt-oss:20b:12` (needs `git`, `uv` and a clone of this repo).
3. The Mac stops its own oMLX and is free for development.

## Do not

- Run `join.ps1` against the live world without the user saying so: a new model brings *new* creatures into their world.
- Commit the world's join token, or anything under `inbox/` or `web/assets/limezu/` (licensed art).
