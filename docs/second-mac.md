# A second Mac as a brain node (e.g. the MacBook Air)

For whoever sets up another Mac in the house: the user, or a Claude Code session running on it.

**Why:** the MacBook Pro (192.168.50.95) hosts the live world and thinks for most creatures; its GPU is the
bottleneck. Another Apple-silicon Mac can think for a few creatures of its own with a small local model, joining
the world over the home network. Nothing else about the world changes; the Pro keeps the world and the save.

## 1. Report the hardware

```bash
system_profiler SPHardwareDataType | grep -E "Chip|Memory|Model Name"
sw_vers -productVersion
ipconfig getifaddr en0
```

## 2. Install the tools and a model

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh          # uv (Python tooling)
git clone ssh://git@192.168.50.249/kalcode/swarm-of-clawsin.git ~/code/swarm-of-clawsin   # or the https URL
# oMLX, the model server, with grammar-constrained output:
uv tool install --python 3.13 "omlx[grammar] @ https://github.com/jundot/omlx/releases/download/v0.7.3/omlx-0.7.3-cp313-cp313-macosx_15_0_universal2.whl"
# A small model. 8 GB of memory: Qwen 3.5 4B. 16 GB or more: Qwen 3.5 9B is also fine.
uvx --from huggingface_hub hf download mlx-community/Qwen3.5-4B-MLX-4bit --local-dir ~/models/Qwen3.5-4B-MLX-4bit
```

## 3. Start the model server

```bash
omlx serve --model-dir ~/models --max-concurrent-requests 8 --memory-guard-gb 5   # 8 GB Mac; use 10 on 16 GB
curl -s http://127.0.0.1:8000/v1/models    # should list the model
```

## 4. Join the world

Ask the user (or the Mac session `swarm-of-clawsin-d2`) for the world's join token, then:

```bash
cd ~/code/swarm-of-clawsin
./join.sh --token <token> --server ws://192.168.50.95:7777 --name macbook-air --slots 6 --model Qwen3.5-4B-MLX-4bit:6
```

It prints "Joined! Your creatures: ...": six new creatures arrive in the meadow thinking on this Mac. Leave the
terminal running; if the world restarts, the node reconnects on its own. Ctrl-C puts its creatures to sleep (they keep
everything and wake when it rejoins).

## Report back

To the user, or by message to `swarm-of-clawsin-d2` if Remote Control is on in both: chip and memory, the model,
and the "Joined!" line.

## Do not

- Start a world on this Mac (`start-world.sh`): there is one world, on the MacBook Pro.
- Commit the join token, `.env`, or anything under `inbox/` or `web/assets/limezu/` (licensed art).
