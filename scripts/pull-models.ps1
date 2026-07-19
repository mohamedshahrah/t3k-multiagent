# Pull models so the sidecar can use them. Works whether or not Docker is running —
# Docker is optional here (see the native-Ollama escape hatch in setup.ps1).
#
# Mode is auto-detected, Docker first:
#   1. Docker `ollama` container running -> pull into the ollama-models volume
#      (docker compose exec ollama ollama pull)   <- what the sidecar reads by default
#   2. else a native Ollama on the host          -> pull into the host Ollama store
#      (ollama pull)                               <- pair with OLLAMA_URL=http://host.docker.internal:11434
#   3. else: nothing to pull into -> explain and exit.
#
# Order matters: a machine can have BOTH a native `ollama` binary and the Docker stack.
# The Docker container is the correct target when it's up, so we test that first —
# pulling into the host store while the sidecar reads the volume is a silent no-op.
# Tags are read from .env so nothing is hardcoded. Usage:  .\scripts\pull-models.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

function EnvOr($key, $default) {
    if (Test-Path "$root\.env") {
        $line = Get-Content "$root\.env" | Where-Object { $_ -match "^\s*$key\s*=" } | Select-Object -First 1
        if ($line) { return ($line -split "=", 2)[1].Trim() }
    }
    return $default
}

# Is the Docker `ollama` service actually running? Docker may be absent or stopped — that
# is the whole point of "Docker optional" — so its absence must be a branch, not a crash.
function DockerOllamaRunning {
    try {
        $id = docker compose ps -q ollama 2>$null
        return ($LASTEXITCODE -eq 0 -and "$id".Trim())
    } catch {
        return $false
    }
}

$main     = EnvOr "MODEL_TAG"          "gemma3:12b"
$fallback = EnvOr "MODEL_TAG_FALLBACK" "gemma3:4b"
$embed    = EnvOr "EMBED_MODEL_TAG"    "bge-m3"
$models   = @($main, $fallback, $embed) | Select-Object -Unique   # main==fallback on 8GB boxes

if (DockerOllamaRunning) {
    Write-Host "Pulling via the Docker ollama container (ollama-models volume)..." -ForegroundColor Cyan
    foreach ($m in $models) {
        Write-Host "  -> $m" -ForegroundColor Green
        docker compose exec ollama ollama pull $m
    }
    Write-Host "`nInstalled models:" -ForegroundColor Cyan
    docker compose exec ollama ollama list
}
elseif (Get-Command ollama -ErrorAction SilentlyContinue) {
    Write-Host "Docker ollama not running -- pulling via native Ollama on the host..." -ForegroundColor Cyan
    # `ollama pull` talks to a running server; make sure one is up before we start.
    try {
        Invoke-RestMethod "http://127.0.0.1:11434/api/tags" -TimeoutSec 3 | Out-Null
    } catch {
        Write-Host "Native 'ollama' found but no server answered on 127.0.0.1:11434." -ForegroundColor Yellow
        Write-Host "Start it first ('ollama serve', or open the Ollama app), then re-run this." -ForegroundColor Yellow
        exit 1
    }
    foreach ($m in $models) {
        Write-Host "  -> $m" -ForegroundColor Green
        ollama pull $m
    }
    Write-Host "`nInstalled models:" -ForegroundColor Cyan
    ollama list
}
else {
    Write-Host "No model backend found." -ForegroundColor Red
    Write-Host "Either start the Docker stack ('docker compose up -d') or install Ollama" -ForegroundColor Yellow
    Write-Host "natively (https://ollama.com/download), run 'ollama serve', then re-run this." -ForegroundColor Yellow
    exit 1
}
