FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DATA_DIR=/data

WORKDIR /srv

# tzdata fehlt im slim-Image. Ohne sie ignoriert die C-Bibliothek TZ und
# alles läuft auf UTC — Buchungszeiten wären im Sommer zwei Stunden zu früh
# und eine Entnahme kurz nach Mitternacht landete im falschen Monat.
RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata \
 && rm -rf /var/lib/apt/lists/*

# Nicht als root laufen lassen
RUN adduser --system --group --home /srv app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY docker/entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh \
 && mkdir -p /data \
 && chown -R app:app /data /srv

USER app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')"

ENTRYPOINT ["/entrypoint.sh"]
