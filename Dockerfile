FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DATA_DIR=/data

WORKDIR /srv

# tzdata: ohne sie ignoriert die C-Bibliothek TZ und alles läuft auf UTC —
#   Buchungszeiten wären im Sommer zwei Stunden zu früh und eine Entnahme
#   kurz nach Mitternacht landete im falschen Monat.
# gosu: der Entrypoint richtet als root die Rechte auf dem gemounteten
#   Datenverzeichnis und gibt die Privilegien danach wieder ab.
RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata gosu \
 && rm -rf /var/lib/apt/lists/*

# Nicht als root laufen lassen. Feste UID/GID, damit die Dateien in ./data auf
# dem Host nicht zufällig einem vorhandenen Systemkonto zugeordnet werden —
# ohne das gehört die Datenbank auf Ubuntu z. B. dem Benutzer 'syslog'.
RUN addgroup --system --gid 10001 app \
 && adduser --system --uid 10001 --ingroup app --home /srv app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY docker/entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh \
 && mkdir -p /data \
 && chown -R app:app /data /srv

# Bewusst kein 'USER app': der Entrypoint startet kurz als root, korrigiert die
# Rechte auf dem Bind-Mount und wechselt dann per gosu auf 'app'. Ohne diesen
# Schritt kann der Container die SQLite-Datei im gemounteten ./data nicht
# anlegen — das Verzeichnis gehört dem Host-Benutzer.
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')"

ENTRYPOINT ["/entrypoint.sh"]
