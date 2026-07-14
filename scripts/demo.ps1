# Demo profile: baked image, no source mounts, no debug port.
# Note: we pass ONLY the base + demo files so the dev override is not picked up.
# Usage:  .\scripts\demo.ps1
Set-Location (Split-Path $PSScriptRoot -Parent)
docker compose -f docker-compose.yml -f docker-compose.demo.yml up --build
