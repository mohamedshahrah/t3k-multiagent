# Dev: bring the backend up (hot reload + debugpy) and launch the Wails desktop app.
# Usage:  .\scripts\dev.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

Write-Host "Starting backend (docker compose up -d --build)..." -ForegroundColor Cyan
docker compose up -d --build

Write-Host "Waiting for sidecar health..." -ForegroundColor Cyan
for ($i = 0; $i -lt 30; $i++) {
    try { Invoke-RestMethod http://127.0.0.1:8756/health -TimeoutSec 2 | Out-Null; Write-Host "sidecar healthy" -ForegroundColor Green; break }
    catch { Start-Sleep -Seconds 2 }
}

if (Get-Command wails -ErrorAction SilentlyContinue) {
    Write-Host "Launching Wails desktop app (wails dev)..." -ForegroundColor Cyan
    wails dev
} else {
    Write-Host "Wails not installed -- backend is up on http://127.0.0.1:8756." -ForegroundColor Yellow
    Write-Host "Install Go + `go install github.com/wailsapp/wails/v2/cmd/wails@latest` to run the desktop shell." -ForegroundColor Yellow
}
