# Start Swarm World on this Windows PC: the world, a local brain node, and the viewer (Windows PowerShell).
#   .\start-world.ps1                    # resumes the saved world; minds from the local Ollama
#   .\start-world.ps1 --lan              # also let other machines in the house join (prints a join token)
#   .\start-world.ps1 --fresh            # brand-new world (the old save is kept as worlds\default.<time>.bak)
#   .\start-world.ps1 --no-inspiration   # no hunches: purely unassisted discovery
#   (flags combine, e.g. .\start-world.ps1 --fresh --lan)
# Settings are environment variables, e.g.  $env:MODEL = "gpt-oss:20b"; $env:CREATURES = "12"; .\start-world.ps1
#   MODEL, CREATURES   the model and how many creatures it drives (no MODEL: the first model on the server)
#   MODEL2             a second model as "NAME:N" (a model may name its own server: "NAME:N@http://host:11434/v1")
#   MODEL_SERVER       OpenAI-compatible URL (default: this PC's Ollama, http://127.0.0.1:11434/v1)
#   SLOTS, SEED, TICK, PORT, WORLD, TOKEN, ADOPT, HARNESS, HARNESS_ALL, NO_OPEN   (same meaning as in start-world.sh)
# Needs: uv (https://docs.astral.sh/uv/) and Ollama (https://ollama.com) or another OpenAI-compatible model server.
# Stop with Ctrl+C: the world saves itself first (and an Ollama this script started stops too).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Setting($name, $default) {
    $v = [Environment]::GetEnvironmentVariable($name)
    if ($v) { return $v } else { return $default }
}

$Model       = Setting "MODEL" ""
$Creatures   = Setting "CREATURES" "12"
$Model2      = Setting "MODEL2" ""
$Slots       = Setting "SLOTS" "8"
$Seed        = Setting "SEED" "7"
$Tick        = Setting "TICK" "1.0"
$Port        = Setting "PORT" "7777"
$World       = Setting "WORLD" "worlds/default.json"
$Token       = Setting "TOKEN" ""
$ModelServer = (Setting "MODEL_SERVER" "http://127.0.0.1:11434/v1").TrimEnd("/")

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "Please install uv first: powershell -ExecutionPolicy ByPass -c `"irm https://astral.sh/uv/install.ps1 | iex`""
    exit 1
}
New-Item -ItemType Directory -Force -Path runs | Out-Null

# Never run two worlds at once: they would fight over the port and the save file.
$listening = Get-NetTCPConnection -LocalPort ([int]$Port) -State Listen -ErrorAction SilentlyContinue
$running = Get-CimInstance Win32_Process -Filter "Name like 'python%'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match "swarmworld\.server" }
if ($listening -or $running) {
    Write-Host "A Swarm World is already running (port $Port or a swarmworld.server process). Stop it first."
    exit 1
}

function ServerAnswers($url) {
    try { Invoke-RestMethod -Uri "$url/models" -TimeoutSec 5 | Out-Null; return $true } catch { return $false }
}

# The model server: start Ollama ourselves if it isn't running, with settings the creatures need.
$startedOllama = $null
if (-not (ServerAnswers $ModelServer)) {
    $isLocalOllama = $ModelServer -match "^http://(127\.0\.0\.1|localhost):11434"
    if ($isLocalOllama -and (Get-Command ollama -ErrorAction SilentlyContinue)) {
        if (-not $env:OLLAMA_CONTEXT_LENGTH) { $env:OLLAMA_CONTEXT_LENGTH = "8192" }  # prompts run 3-5k tokens
        if (-not $env:OLLAMA_NUM_PARALLEL) { $env:OLLAMA_NUM_PARALLEL = "8" }        # creatures think at the same time
        if (-not $env:OLLAMA_KEEP_ALIVE) { $env:OLLAMA_KEEP_ALIVE = "24h" }
        Write-Host "Starting Ollama (ollama serve)..."
        $startedOllama = Start-Process ollama -ArgumentList "serve" -NoNewWindow -PassThru `
            -RedirectStandardError "runs\ollama.log" -RedirectStandardOutput "runs\ollama.out.log"
        for ($i = 0; $i -lt 60 -and -not (ServerAnswers $ModelServer); $i++) { Start-Sleep -Seconds 1 }
    }
    if (-not (ServerAnswers $ModelServer)) {
        Write-Host "No model server answering at $ModelServer. Install Ollama and pull a model (e.g. ollama pull qwen3.5:9b),"
        Write-Host "or set `$env:MODEL_SERVER to another OpenAI-compatible server."
        exit 1
    }
} elseif (Get-Process -Name "ollama app" -ErrorAction SilentlyContinue) {
    Write-Host "Note: Ollama's tray app is serving. It ignores OLLAMA_* settings (context length 8192 matters here);"
    Write-Host "      for best results quit it from the tray and run this script again, which starts 'ollama serve' itself."
}

$worldArgs = @("run", "python", "-m", "swarmworld.server", "--seed", $Seed, "--tick", $Tick, "--port", $Port, "--world", $World)
$nodeArgs = @("run", "python", "-m", "swarmworld.node", "--server", "ws://127.0.0.1:$Port", "--slots", $Slots,
              "--model-server", $ModelServer)
if ($Model) { $nodeArgs += @("--model", "${Model}:$Creatures") }
if ($Model2) { $nodeArgs += @("--model", $Model2) }
foreach ($a in ((Setting "ADOPT" "") -split "\s+" | Where-Object { $_ })) { $nodeArgs += @("--adopt", $a) }
if (Setting "HARNESS" "") { $worldArgs += @("--harness", (Setting "HARNESS" "")) }
if (Setting "HARNESS_ALL" "") { $worldArgs += @("--harness-all", (Setting "HARNESS_ALL" "")) }

foreach ($flag in $args) {
    switch ($flag) {
        "--lan" {
            if (-not $Token) { $Token = -join ((1..8) | ForEach-Object { "{0:x}" -f (Get-Random -Maximum 16) }) }
            $worldArgs += "--lan"
        }
        "--fresh" { $worldArgs += "--fresh" }
        "--no-inspiration" { $worldArgs += "--no-inspiration" }
        default { Write-Host "unknown option: $flag"; exit 1 }
    }
}
if ($Token) {
    $worldArgs += @("--token", $Token)
    $nodeArgs += @("--token", $Token)
}

function Quote($list) { ($list | ForEach-Object { '"' + ($_ -replace '"', '\"') + '"' }) -join " " }

function Stop-Tree($proc) {
    # Stop a process and everything it started (uv runs python as a child).
    if (-not $proc) { return }
    Get-CimInstance Win32_Process -Filter "ParentProcessId = $($proc.Id)" -ErrorAction SilentlyContinue |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
}

$worldProc = Start-Process uv -ArgumentList (Quote $worldArgs) -NoNewWindow -PassThru
$nodeProc = $null
try {
    for ($i = 0; $i -lt 60; $i++) {
        try { Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/metrics" -TimeoutSec 2 | Out-Null; break } catch { Start-Sleep -Milliseconds 500 }
    }
    $nodeProc = Start-Process uv -ArgumentList (Quote $nodeArgs) -NoNewWindow -PassThru
    if ($Token) { Write-Host "Join token: $Token   (other machines: .\join.ps1 --token $Token  or  ./join.sh --token $Token)" }
    if (-not (Setting "NO_OPEN" "")) { Start-Process "http://127.0.0.1:$Port/" }
    Write-Host "Swarm World is running on http://127.0.0.1:$Port/  (Ctrl+C to stop; it saves first)"

    # Watchdog for long unattended runs: if the Ollama we started stops answering, bring it back.
    $misses = 0
    while (-not $worldProc.HasExited) {
        Wait-Process -Id $worldProc.Id -Timeout 60 -ErrorAction SilentlyContinue
        if ($worldProc.HasExited -or -not $startedOllama) { continue }
        if (ServerAnswers $ModelServer) { $misses = 0; continue }
        $misses++
        if ($misses -ge 3) {
            Write-Host "$(Get-Date): Ollama is not answering; restarting it"
            Stop-Tree $startedOllama
            Start-Sleep -Seconds 5
            $startedOllama = Start-Process ollama -ArgumentList "serve" -NoNewWindow -PassThru `
                -RedirectStandardError "runs\ollama.log" -RedirectStandardOutput "runs\ollama.out.log"
            $misses = 0
        }
    }
}
finally {
    # Ctrl+C reaches the world too (same console), and it saves on the way out; give it time before cleaning up.
    if ($worldProc -and -not $worldProc.HasExited) { Wait-Process -Id $worldProc.Id -Timeout 15 -ErrorAction SilentlyContinue }
    Stop-Tree $nodeProc
    Stop-Tree $worldProc
}
