# Join a Swarm World running on another computer in the house (Windows PowerShell).
#   .\join.ps1 --token TOKEN                          # find the world automatically, use the local model server
#   .\join.ps1 --token TOKEN --model qwen3:8b:8       # choose a model (Ollama names work) and how many creatures
#   .\join.ps1 --token TOKEN --server ws://192.168.1.20:7777
# Needs: uv (https://docs.astral.sh/uv/) and a local model server (Ollama, LM Studio or llama-server).
# If discovery finds nothing, set this network to "Private" in Windows settings, or pass --server.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "Please install uv first: powershell -ExecutionPolicy ByPass -c `"irm https://astral.sh/uv/install.ps1 | iex`""
    exit 1
}
$argsList = @($args)
if (-not ($argsList -contains "--server")) { $argsList += "--discover" }
uv run python -m swarmworld.node @argsList
