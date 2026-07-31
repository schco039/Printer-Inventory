#!/bin/sh
# Migrationen anwenden, dann den Server starten.
# Idempotent: bei bereits aktuellem Schema passiert nichts.
set -e

echo "→ Migrations…"
alembic upgrade head

echo "→ Serveur sur le port 8000"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers
