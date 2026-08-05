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

random_password() {
  # Ohne mehrdeutige Zeichen (0/O, 1/l/I) — wird auf Zettel geschrieben.
  #
  # Achtung: 'tr < /dev/urandom | head -c 16' sieht naheliegend aus, bricht
  # aber unter 'set -o pipefail' ab — head beendet sich zuerst, tr bekommt
  # SIGPIPE und die Pipeline meldet 141. Deshalb erst eine feste Menge lesen
  # und danach in der Shell kürzen.
  local raw=""
  while [ ${#raw} -lt 16 ]; do
    raw="${raw}$(head -c 256 /dev/urandom | LC_ALL=C tr -dc 'A-HJ-NP-Za-km-z2-9' || true)"
  done
  printf '%s' "${raw:0:16}"
}

# ── 3. .env anlegen ──────────────────────────────────────────────────

NEW_INSTALL=0
if [ ! -f .env ]; then
  NEW_INSTALL=1
  info "Erstelle .env mit zufälligen Geheimnissen…"
  APP_SECRET="$(random_hex 32)"
  ADMIN_PASSWORD="$(random_password)"

  sed -e "s|^APP_SECRET=.*|APP_SECRET=${APP_SECRET}|" \
      -e "s|^ADMIN_PASSWORD=.*|ADMIN_PASSWORD=${ADMIN_PASSWORD}|" \
      .env.example > .env
  chmod 600 .env
  ok ".env erstellt"
else
  ok ".env vorhanden — wird nicht überschrieben"
  # '|| true': fehlt die Zeile, liefert grep 1 und pipefail würde abbrechen
  ADMIN_PASSWORD="$(grep -E '^ADMIN_PASSWORD=' .env | cut -d= -f2- || true)"
  [ -n "${ADMIN_PASSWORD}" ] || warn "ADMIN_PASSWORD ist leer — die Admin-Oberfläche ist ungeschützt!"
fi

APP_PORT="$(grep -E '^APP_PORT=' .env | cut -d= -f2- || true)"
APP_PORT="${APP_PORT:-8080}"

# ── 4. Datenverzeichnis ──────────────────────────────────────────────

mkdir -p data/uploads data/backups
ok "Datenverzeichnis bereit (./data)"

# ── 5. Bauen und starten ─────────────────────────────────────────────

info "Baue Image und starte Container (beim ersten Mal dauert das ein paar Minuten)…"
$COMPOSE up -d --build

# ── 6. Auf Gesundheit warten ─────────────────────────────────────────

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

# ── 7. Zusammenfassung ───────────────────────────────────────────────

HOST_IP="$(hostname -I 2>/dev/null | awk '{print $1}' || echo 'localhost')"

echo
echo "${GREEN}${BOLD}Installation abgeschlossen.${OFF}"
echo
echo "  Admin-Oberfläche   http://${HOST_IP}:${APP_PORT}/admin"
echo "  Kiosk (RPi)        http://${HOST_IP}:${APP_PORT}/kiosk"
echo
if [ "$NEW_INSTALL" -eq 1 ]; then
  echo "  Benutzer           admin"
  echo "  Passwort           ${BOLD}${ADMIN_PASSWORD}${OFF}"
  echo
  echo "  ${YELLOW}Dieses Passwort steht in der Datei .env und wird hier nur einmal angezeigt.${OFF}"
  echo
fi
echo "  Nächster Schritt:  Excel-Export unter /admin/import hochladen"
echo
echo "  Update:            git pull && ./install.sh"
echo "  Logs:              $COMPOSE logs -f app"
echo "  Stoppen:           $COMPOSE down"
echo
