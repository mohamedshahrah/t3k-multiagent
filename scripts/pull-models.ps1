# Pull models into the ollama-models volume (once per machine; they survive `compose down`).
# Reads tags from .env so nothing is hardcoded. Usage:  .\scripts\pull-models.ps1
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

$main     = EnvOr "MODEL_TAG"          "gemma3:12b"
$fallback = EnvOr "MODEL_TAG_FALLBACK" "gemma3:4b"
$embed    = EnvOr "EMBED_MODEL_TAG"    "bge-m3"

Write-Host "Pulling models into the ollama container..." -ForegroundColor Cyan
foreach ($m in @($main, $fallback, $embed)) {
    Write-Host "  -> $m" -ForegroundColor Green
    docker compose exec ollama ollama pull $m
}
Write-Host "`nInstalled models:" -ForegroundColor Cyan
docker compose exec ollama ollama list
