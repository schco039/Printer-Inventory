#!/bin/sh
# Migrationen anwenden, dann den Server starten.
# Idempotent: bei bereits aktuellem Schema passiert nichts.
set -e

DATA_DIR="${DATA_DIR:-/data}"

# Erster Durchlauf als root: Rechte auf dem gemounteten Datenverzeichnis
# richten und danach die Privilegien abgeben. Ohne das kann der Benutzer 'app'
# im Bind-Mount ./data keine Datenbank anlegen — das Verzeichnis gehört dem
# Host-Benutzer, und der Mount überschreibt die Rechte aus dem Image.
if [ "$(id -u)" = "0" ]; then
  mkdir -p "$DATA_DIR/uploads" "$DATA_DIR/backups"
  chown -R app:app "$DATA_DIR" 2>/dev/null || \
    echo "! Rechte auf $DATA_DIR konnten nicht gesetzt werden — läuft weiter"
  exec gosu app "$0" "$@"
fi

echo "→ Migrations…"
alembic upgrade head

echo "→ Serveur sur le port 8000"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers
