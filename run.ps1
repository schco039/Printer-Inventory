<#
.SYNOPSIS
  Startet die Anwendung lokal ohne Docker (nach .\install.ps1 -NoDocker).
#>
param(
  [int]$Port = 8000
)

$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot

if (-not (Test-Path '.venv')) {
  Write-Host 'Virtuelle Umgebung fehlt. Zuerst ausfuehren:  .\install.ps1 -NoDocker' -ForegroundColor Red
  exit 1
}

$env:DATA_DIR = (Resolve-Path '.\data').Path
Write-Host "Server laeuft auf http://localhost:$Port/admin  (Strg+C zum Beenden)" -ForegroundColor Cyan
& .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port $Port
