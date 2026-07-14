# Tail the sidecar logs. Usage:  .\scripts\logs.ps1
Set-Location (Split-Path $PSScriptRoot -Parent)
docker compose logs -f sidecar
