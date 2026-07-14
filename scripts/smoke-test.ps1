# Sanity test via the sidecar container: the model server answers text + vision.
# Usage:  .\scripts\smoke-test.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent

Write-Host "== Sidecar health ==" -ForegroundColor Cyan
try { (Invoke-RestMethod http://127.0.0.1:8756/health) | ConvertTo-Json }
catch { Write-Host "sidecar not reachable on :8756 (is `docker compose up` running?)" -ForegroundColor Red; exit 1 }

function EnvOr($key, $default) {
    $line = Get-Content "$root\.env" -ErrorAction SilentlyContinue | Where-Object { $_ -match "^\s*$key\s*=" } | Select-Object -First 1
    if ($line) { return ($line -split "=", 2)[1].Trim() } else { return $default }
}
$model = EnvOr "MODEL_TAG" "gemma3:12b"

Write-Host "`n== Text prompt ($model) ==" -ForegroundColor Cyan
$body = @{ model = $model; prompt = "Tek cümleyle kendini tanit."; stream = $false } | ConvertTo-Json
(Invoke-RestMethod -Method Post -Uri http://127.0.0.1:11434/api/generate -Body $body -ContentType "application/json").response

Write-Host "`n== Vision prompt ($model) ==" -ForegroundColor Cyan
# 1x1 red PNG, base64 -- just proves the vision path accepts an image.
$png = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR4nGNgYGAAAAAEAAH2FzhVAAAAAElFTkSuQmCC"
$vbody = @{ model = $model; prompt = "Bu goruntude ne var? Kisaca."; images = @($png); stream = $false } | ConvertTo-Json
(Invoke-RestMethod -Method Post -Uri http://127.0.0.1:11434/api/generate -Body $vbody -ContentType "application/json").response

Write-Host "`nSmoke test done." -ForegroundColor Green
