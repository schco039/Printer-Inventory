<#
.SYNOPSIS
  Installation / Update unter Windows.

.DESCRIPTION
  Standard: Docker Desktop. Ohne Docker (z. B. zum schnellen Ausprobieren auf
  einem Notebook) startet -NoDocker die Anwendung in einer lokalen
  Python-Umgebung.

.EXAMPLE
  .\install.ps1
  .\install.ps1 -NoDocker
#>
[CmdletBinding()]
param(
  [switch]$NoDocker
)

$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot

function Write-Info { param($m) Write-Host "-> $m" -ForegroundColor Cyan }
function Write-Ok   { param($m) Write-Host "OK  $m" -ForegroundColor Green }
function Write-Warn { param($m) Write-Host "!   $m" -ForegroundColor Yellow }
function Write-Fail { param($m) Write-Host "X   $m" -ForegroundColor Red; exit 1 }

function New-RandomHex {
  param([int]$Bytes = 32)
  $buffer = New-Object byte[] $Bytes
  [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($buffer)
  ($buffer | ForEach-Object { $_.ToString('x2') }) -join ''
}

function New-RandomPassword {
  # Ohne mehrdeutige Zeichen (0/O, 1/l/I) - wird auf Zettel geschrieben.
  $alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789'
  $buffer = New-Object byte[] 16
  [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($buffer)
  -join ($buffer | ForEach-Object { $alphabet[$_ % $alphabet.Length] })
}

# --- .env anlegen ----------------------------------------------------

$newInstall = $false
if (-not (Test-Path '.env')) {
  $newInstall = $true
  Write-Info 'Erstelle .env mit zufaelligen Geheimnissen...'
  $adminPassword = New-RandomPassword
  (Get-Content '.env.example' -Raw) `
    -replace '(?m)^APP_SECRET=.*', "APP_SECRET=$(New-RandomHex 32)" `
    -replace '(?m)^ADMIN_PASSWORD=.*', "ADMIN_PASSWORD=$adminPassword" |
    Set-Content '.env' -Encoding utf8 -NoNewline
  Write-Ok '.env erstellt'
} else {
  Write-Ok '.env vorhanden - wird nicht ueberschrieben'
  $line = Select-String -Path '.env' -Pattern '^ADMIN_PASSWORD=(.*)$'
  if ($line) { $adminPassword = $line.Matches[0].Groups[1].Value }
  if (-not $adminPassword) { Write-Warn 'ADMIN_PASSWORD ist leer - die Admin-Oberflaeche ist ungeschuetzt!' }
}

$portLine = Select-String -Path '.env' -Pattern '^APP_PORT=(.*)$'
$appPort = if ($portLine) { $portLine.Matches[0].Groups[1].Value } else { '8080' }
if (-not $appPort) { $appPort = '8080' }

New-Item -ItemType Directory -Force -Path 'data\uploads', 'data\backups' | Out-Null
Write-Ok 'Datenverzeichnis bereit (.\data)'

# --- Variante ohne Docker -------------------------------------------

if ($NoDocker) {
  Write-Info 'Lokale Installation ohne Docker'

  $python = (Get-Command python -ErrorAction SilentlyContinue)
  if (-not $python) { Write-Fail 'Python 3.12+ nicht gefunden. https://www.python.org/downloads/' }

  if (-not (Test-Path '.venv')) {
    Write-Info 'Erstelle virtuelle Umgebung...'
    & python -m venv .venv
  }
  Write-Info 'Installiere Abhaengigkeiten...'
  & .\.venv\Scripts\python.exe -m pip install --quiet --upgrade pip
  & .\.venv\Scripts\python.exe -m pip install --quiet -r requirements.txt

  Write-Info 'Wende Migrationen an...'
  $env:DATA_DIR = (Resolve-Path '.\data').Path
  & .\.venv\Scripts\alembic.exe upgrade head

  Write-Host ''
  Write-Host 'Installation abgeschlossen.' -ForegroundColor Green
  Write-Host ''
  Write-Host "  Start:   .\run.ps1"
  Write-Host "  Adresse: http://localhost:8000/admin"
  if ($newInstall) {
    Write-Host "  Benutzer admin / Passwort $adminPassword" -ForegroundColor Yellow
  }
  Write-Host ''
  exit 0
}

# --- Docker ----------------------------------------------------------

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
  Write-Fail @'
Docker Desktop nicht gefunden.
  Installieren:  https://www.docker.com/products/docker-desktop/
  Oder ohne Docker starten:  .\install.ps1 -NoDocker
'@
}

& docker info *> $null
if ($LASTEXITCODE -ne 0) {
  Write-Fail 'Docker ist installiert, laeuft aber nicht. Docker Desktop starten und erneut versuchen.'
}
Write-Ok 'Docker gefunden'

Write-Info 'Baue Image und starte Container (beim ersten Mal dauert das ein paar Minuten)...'
& docker compose up -d --build
if ($LASTEXITCODE -ne 0) { Write-Fail 'docker compose ist fehlgeschlagen.' }

Write-Info 'Warte auf die Anwendung...'
$healthy = $false
foreach ($i in 1..60) {
  try {
    Invoke-WebRequest -Uri "http://127.0.0.1:$appPort/healthz" -UseBasicParsing -TimeoutSec 2 | Out-Null
    $healthy = $true
    break
  } catch {
    Start-Sleep -Seconds 1
  }
}
if (-not $healthy) {
  & docker compose logs --tail 40 app
  Write-Fail 'Keine Antwort nach 60 Sekunden.'
}
Write-Ok 'Anwendung antwortet'

Write-Host ''
Write-Host 'Installation abgeschlossen.' -ForegroundColor Green
Write-Host ''
Write-Host "  Admin-Oberflaeche   http://localhost:$appPort/admin"
Write-Host "  Kiosk (RPi)         http://localhost:$appPort/kiosk"
Write-Host ''
if ($newInstall) {
  Write-Host "  Benutzer            admin"
  Write-Host "  Passwort            $adminPassword" -ForegroundColor Yellow
  Write-Host ''
  Write-Host '  Dieses Passwort steht in der Datei .env und wird hier nur einmal angezeigt.' -ForegroundColor Yellow
  Write-Host ''
}
Write-Host '  Naechster Schritt:  Excel-Export unter /admin/import hochladen'
Write-Host ''
Write-Host '  Update:             git pull; .\install.ps1'
Write-Host '  Logs:               docker compose logs -f app'
Write-Host '  Stoppen:            docker compose down'
Write-Host ''
