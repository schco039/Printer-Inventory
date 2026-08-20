#!/usr/bin/env bash
#
# Installation / Update — Linux, macOS, NAS.
#
#   git clone <repo> lgk-printer && cd lgk-printer && ./install.sh
#
# Idempotent: dasselbe Skript aktualisiert eine bestehende Installation
# (git pull && ./install.sh). Vorhandene .env und Daten bleiben unangetastet.

set -euo pipefail

cd "$(dirname "$0")"

BOLD=$'\033[1m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RED=$'\033[31m'; OFF=$'\033[0m'
info() { echo "${BOLD}→${OFF} $*"; }
ok()   { echo "${GREEN}✓${OFF} $*"; }
warn() { echo "${YELLOW}!${OFF} $*"; }
fail() { echo "${RED}✕${OFF} $*" >&2; exit 1; }

# ── 1. Voraussetzungen ───────────────────────────────────────────────

command -v docker >/dev/null 2>&1 || fail "Docker fehlt.
  Debian/Ubuntu/Raspberry Pi OS:  curl -fsSL https://get.docker.com | sh
  Synology/QNAP:                  Container Manager im Paketzentrum installieren
  Danach dieses Skript erneut ausführen."

if docker compose version >/dev/null 2>&1; then
  COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE="docker-compose"
else
  fail "Docker Compose fehlt. Debian/Ubuntu: sudo apt install docker-compose-plugin"
fi

docker info >/dev/null 2>&1 || fail "Docker läuft, ist aber nicht erreichbar.
  Entweder den Docker-Dienst starten (sudo systemctl start docker)
  oder den Benutzer zur Gruppe hinzufügen: sudo usermod -aG docker \$USER
  (danach ab- und wieder anmelden)."

ok "Docker gefunden ($COMPOSE)"

# ── 2. Zufallsgeheimnisse ────────────────────────────────────────────

random_hex() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex "$1"
  elif [ -r /dev/urandom ]; then
    head -c "$1" /dev/urandom | od -An -tx1 | tr -d ' \n'
  else
    fail "Keine Quelle für Zufallszahlen gefunden (openssl oder /dev/urandom)."
  fi
}

# ── 3. .env anlegen ──────────────────────────────────────────────────

NEW_INSTALL=0
if [ ! -f .env ]; then
  NEW_INSTALL=1
  info "Erstelle .env mit zufälligen Geheimnissen…"
  APP_SECRET="$(random_hex 32)"

  sed -e "s|^APP_SECRET=.*|APP_SECRET=${APP_SECRET}|" .env.example > .env
  chmod 600 .env
  ok ".env erstellt"
else
  ok ".env vorhanden — wird nicht überschrieben"
fi

APP_PORT="$(grep -E '^APP_PORT=' .env | cut -d= -f2- || true)"
APP_PORT="${APP_PORT:-8080}"

# ── 4. Port frei? ────────────────────────────────────────────────────
# Auf einem Host mit weiteren Diensten ist das der einzige echte
# Kollisionspunkt. Lieber hier klar melden als später einen rohen Docker-Fehler.

port_belegt() {
  if command -v ss >/dev/null 2>&1; then
    ss -ltnH 2>/dev/null | awk '{print $4}' | grep -qE "[:.]${APP_PORT}$"
  elif command -v netstat >/dev/null 2>&1; then
    netstat -ltn 2>/dev/null | awk '{print $4}' | grep -qE "[:.]${APP_PORT}$"
  else
    return 1   # nicht prüfbar — Docker meldet es notfalls selbst
  fi
}

# 'ps -q' statt 'ps': letzteres druckt auch bei leerem Projekt eine Kopfzeile
# und hätte die Prüfung damit immer übersprungen.
if port_belegt && [ -z "$($COMPOSE ps -q 2>/dev/null)" ]; then
  fail "Port ${APP_PORT} ist auf diesem Host bereits belegt.
  Trage in der Datei .env einen freien Port ein, zum Beispiel:
      APP_PORT=8090
  und starte dieses Skript erneut.
  Läuft auf dem Host bereits ein Reverse Proxy, siehe README,
  Abschnitt \"Betrieb neben anderen Diensten\"."
fi
ok "Port ${APP_PORT} verfügbar"

# ── 5. Datenverzeichnis ──────────────────────────────────────────────

mkdir -p data/uploads data/backups
ok "Datenverzeichnis bereit (./data)"

# ── 6. Bauen und starten ─────────────────────────────────────────────

info "Baue Image und starte Container (beim ersten Mal dauert das ein paar Minuten)…"
$COMPOSE up -d --build

# ── 7. Auf Gesundheit warten ─────────────────────────────────────────

info "Warte auf die Anwendung…"
URL="http://127.0.0.1:${APP_PORT}/healthz"

# Auf einem nackten Server ist weder curl noch wget garantiert vorhanden.
# Letzter Ausweg ist das Python im Container selbst.
health_check() {
  if command -v curl >/dev/null 2>&1; then
    curl -fsS "$URL" >/dev/null 2>&1
  elif command -v wget >/dev/null 2>&1; then
    wget -q -O /dev/null "$URL"
  else
    $COMPOSE exec -T app python -c \
      "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')" \
      >/dev/null 2>&1
  fi
}

for i in $(seq 1 60); do
  if health_check; then
    ok "Anwendung antwortet"
    break
  fi
  if [ "$i" -eq 60 ]; then
    echo
    warn "Keine Antwort nach 60 Sekunden. Logs:"
    $COMPOSE logs --tail 40 app
    fail "Start fehlgeschlagen."
  fi
  sleep 1
done

# ── 8. Zusammenfassung ───────────────────────────────────────────────

HOST_IP="$(hostname -I 2>/dev/null | awk '{print $1}' || echo 'localhost')"

echo
echo "${GREEN}${BOLD}Installation abgeschlossen.${OFF}"
echo
echo "  Admin-Oberfläche   http://${HOST_IP}:${APP_PORT}/admin"
echo "  Kiosk (RPi)        http://${HOST_IP}:${APP_PORT}/kiosk"
echo
if [ "$NEW_INSTALL" -eq 1 ]; then
  echo "  ${BOLD}Erster Schritt: Administrator anlegen${OFF}"
  echo "    http://${HOST_IP}:${APP_PORT}/setup"
  echo "    Dort Name, Anmeldename und Code festlegen. Danach ist die"
  echo "    Einrichtungsseite gesperrt."
  echo
fi
echo "  Danach:            Excel-Export unter /admin/import hochladen"
echo
echo "  Update:            git pull && ./install.sh"
echo "  Logs:              $COMPOSE logs -f app"
echo "  Stoppen:           $COMPOSE down"
echo
