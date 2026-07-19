# Native-Ollama profile: run ONLY the sidecar in Docker and talk to an Ollama running
# natively on the host. Excludes the Docker ollama service (no :11434 collision) --
# the escape hatch for machines where GPU-in-Docker doesn't work.
# Note: pass ONLY base + native files so the dev override (hot-reload mounts) is not picked up.
# Prereqs: `ollama serve` running on the host + models pulled (.\scripts\pull-models.ps1).
# Usage:  .\scripts\native.ps1
Set-Location (Split-Path $PSScriptRoot -Parent)

if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    Write-Host "Native 'ollama' not found. Install it (https://ollama.com/download) and run 'ollama serve'." -ForegroundColor Yellow
}
try {
    Invoke-RestMethod "http://127.0.0.1:11434/api/tags" -TimeoutSec 3 | Out-Null
} catch {
    Write-Host "No Ollama server answered on 127.0.0.1:11434 -- start it ('ollama serve') before uploads." -ForegroundColor Yellow
}

docker compose -f docker-compose.yml -f docker-compose.native.yml up -d --build
Write-Host "Backend up (sidecar only). Health: http://127.0.0.1:8756/health" -ForegroundColor Green
Write-Host "If /health shows models_present: [] (OCR does nothing), the container can't reach Ollama." -ForegroundColor Yellow
Write-Host "Ollama binds 127.0.0.1 by default -- restart it exposed to the container:" -ForegroundColor Yellow
Write-Host "  `$env:OLLAMA_HOST='0.0.0.0:11434'; ollama serve" -ForegroundColor Yellow
Write-Host "Verify: docker compose -f docker-compose.yml -f docker-compose.native.yml exec sidecar curl -fsS http://host.docker.internal:11434/api/tags" -ForegroundColor Yellow
