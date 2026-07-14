# Preflight: verify every member's machine can run the identical stack.
# Usage:  .\scripts\setup.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

function Check($name, $cmd) {
    $ok = Get-Command $cmd -ErrorAction SilentlyContinue
    if ($ok) { Write-Host "[ok]   $name -> $($ok.Source)" -ForegroundColor Green }
    else     { Write-Host "[MISS] $name ($cmd not found)" -ForegroundColor Yellow }
    return [bool]$ok
}

Write-Host "== Evrak Asistani setup ==" -ForegroundColor Cyan
Check "Docker"        docker | Out-Null
Check "Docker Compose (docker compose)" docker | Out-Null
$hasGo   = Check "Go (desktop shell only)"   go
$hasNode = Check "Node"                        node
$hasWails= Check "Wails v2 (desktop shell)"    wails

# GPU passthrough test (non-fatal: there is a documented native-Ollama escape hatch).
Write-Host "`n-- GPU-in-Docker check --" -ForegroundColor Cyan
try {
    docker run --rm --gpus=all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi | Select-String "NVIDIA"
    Write-Host "[ok]   GPU passthrough works" -ForegroundColor Green
} catch {
    Write-Host "[warn] GPU-in-Docker failed. Fallback: run Ollama natively and set" -ForegroundColor Yellow
    Write-Host "       OLLAMA_URL=http://host.docker.internal:11434 in .env" -ForegroundColor Yellow
}

# Seed .env from the example on first run.
if (-not (Test-Path "$root\.env")) {
    Copy-Item "$root\.env.example" "$root\.env"
    Write-Host "`nCreated .env from .env.example (edit MODEL_TAG if needed)." -ForegroundColor Green
}

Write-Host "`nNext:" -ForegroundColor Cyan
Write-Host "  docker compose up -d --build   # start the backend"
Write-Host "  .\scripts\pull-models.ps1      # pull models into the ollama volume (one-time)"
Write-Host "  .\scripts\smoke-test.ps1       # verify text + vision work"
if (-not ($hasGo -and $hasWails)) {
    Write-Host "  (desktop shell needs Go + Wails v2 -- backend runs without them)" -ForegroundColor Yellow
}
