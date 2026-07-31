# LGK Printer — Verbrauchsmaterial-Lager

Tonerlager für die Schule: Entnahme am Touchscreen, Wareneingang am PC,
Druckerbestand aus dem jährlichen Excel-Export des Hauptlagerprogramms.

Vollständige Spezifikation: **[docs/SPEC.md](docs/SPEC.md)**

---

## Installation

### Linux, macOS, NAS, Raspberry Pi

```bash
git clone <REPO-URL> lgk-printer
cd lgk-printer
./install.sh
```

### Windows (Docker Desktop)

```powershell
git clone <REPO-URL> lgk-printer
cd lgk-printer
.\install.ps1
```

### Windows ohne Docker — zum schnellen Ausprobieren

```powershell
.\install.ps1 -NoDocker
.\run.ps1
```

Das Skript erzeugt beim ersten Lauf eine `.env` mit zufälligem `APP_SECRET`
und einem zufälligen Admin-Passwort, legt `./data` an, baut das Image und
startet den Container. Das Passwort wird **einmalig** am Ende angezeigt und
steht danach in `.env`.

Danach erreichbar unter:

| | |
|---|---|
| Admin | `http://<host>:8080/admin` |
| Kiosk | `http://<host>:8080/kiosk` |
| Health | `http://<host>:8080/healthz` |

### Update

```bash
git pull && ./install.sh
```

Dasselbe Skript. `.env` und `./data` bleiben unangetastet, Migrationen laufen
beim Start automatisch.

---

## Erste Schritte

1. `/admin/import` öffnen und den Excel-Export hochladen
2. Diff-Vorschau prüfen → **Confirmer et appliquer**
3. `/admin/imprimantes` zeigt den importierten Bestand

Der Import schreibt erst nach Bestätigung, ist idempotent (dieselbe Datei
zweimal ⇒ keine Änderung) und löscht nie einen Drucker — verschwundene Geräte
werden als `absent` markiert.

---

## Was funktioniert (Stand M0/M1)

- Excel-Import mit Diff-Vorschau, Filtern und Historie
- Druckerliste mit Filtern (Modell, Statut, Suche)
- Dashboard mit Aufgabenliste „Modelle ohne Verbrauchsmaterial"
- Datenbank-Schema für alle späteren Meilensteine

**Noch nicht:** Verbrauchsmaterial-Verwaltung (M2), Kiosk (M3), Badges (M4),
Wareneingang (M5), Auswertungen (M6/M7).

---

## Aufbau

```
app/
  main.py         Routen
  models.py       Datenmodell (SPEC 4)
  importer.py     Excel-Import (SPEC 5)
  db.py           Session + Einstellungen
  auth.py         Basic-Auth für /admin (bis M4)
  templates/      Jinja2, Oberfläche auf Französisch
  static/app.css  CSS ohne Framework — läuft auch auf altem Chromium
alembic/          Migrationen
tests/            pytest
docker/           Container-Entrypoint
docs/SPEC.md      Spezifikation
```

Daten liegen ausschließlich in `./data` (SQLite, Uploads, Backups).
Container und Code sind wegwerfbar, `./data` gehört ins Backup.

---

## Entwicklung

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt pytest httpx   # Windows
.venv/Scripts/python -m pytest tests -q
.venv/Scripts/python -m uvicorn app.main:app --reload
```

Nach Änderungen am Datenmodell:

```bash
.venv/Scripts/alembic revision --autogenerate -m "beschreibung"
.venv/Scripts/alembic upgrade head
```

---

## Kiosk auf dem Raspberry Pi

Der Pi ist reiner Client — keine Daten, keine Anwendung. Chromium im
Kiosk-Modus auf die Server-URL zeigen lassen:

```bash
chromium-browser --kiosk --noerrdialogs --disable-infobars \
  --disable-pinch --overscroll-history-navigation=0 \
  http://<server>:8080/kiosk
```

Dazu `xset s off -dpms` gegen den Bildschirmschoner und `unclutter` zum
Ausblenden des Mauszeigers.

---

## Sicherheit

- `.env` und `./data` sind in `.gitignore` — **niemals einchecken**
- `APP_SECRET` nach dem Anlernen von Badges nicht mehr ändern: die
  Badge-Hashes hängen davon ab und müssten sonst neu angelernt werden
- Der Dienst gehört ins interne Netz, nicht ins offene Internet
- `*.xlsx` ist ebenfalls in `.gitignore`, damit keine Inventardaten
  versehentlich im Repository landen
