# LGK Printer — Verbrauchsmaterial-Lager

Tonerlager für die Schule: Entnahme am Touchscreen, Wareneingang am PC,
Druckerbestand aus dem jährlichen Excel-Export des Hauptlagerprogramms.

Vollständige Spezifikation: **[docs/SPEC.md](docs/SPEC.md)**

---

## Einmalig: privates Repository anlegen

Das Projekt ist bereits ein Git-Repository mit einem ersten Commit. Es fehlt
nur die Gegenstelle. Mit GitHub CLI:

```bash
gh repo create lgk-printer --private --source=. --remote=origin --push
```

Oder von Hand — leeres **privates** Repository bei GitHub/GitLab anlegen, dann:

```bash
git remote add origin <REPO-URL>
git push -u origin main
```

Danach lässt es sich auf jedem Rechner in der Schule klonen und installieren.

> **Privat lassen.** Im Repository stehen keine Passwörter (`.env` und `data/`
> sind ausgeschlossen), aber Raumnamen, Seriennummern und die Inventarstruktur
> der Schule gehören nicht in ein öffentliches Repository.

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

1. **Import** — `/admin/import`, Excel-Export hochladen, Diff-Vorschau prüfen,
   *Confirmer et appliquer*
2. **Konfigurieren** — `/admin/compatibilites`, je Modell auf *Configurer*.
   Der Assistent legt einen kompletten Satz (BK/C/M/Y + Trommel) in einem
   Schritt an; du tippst nur die Bestellnummern. Teilen sich zwei Modelle
   dieselben Kartuschen: *Copier depuis un autre modèle*
3. **Personen** — `/admin/utilisateurs`, wer Material entnehmen darf
4. **Inventur** — `/admin/inventaire`, Lager zählen und als Anfangsbestand buchen
5. **Kiosk** — `/kiosk` auf dem Touchscreen, ab jetzt wird gebucht

Der Import schreibt erst nach Bestätigung, ist idempotent (dieselbe Datei
zweimal ⇒ keine Änderung) und löscht nie einen Drucker — verschwundene Geräte
werden als `absent` markiert.

---

## Was funktioniert

**M0/M1 — Grundlage**
- Excel-Import mit Diff-Vorschau, Filtern (Zustand + Kategorie) und Historie
- Druckerliste mit Filtern, Dashboard mit offenen Aufgaben

**M2 — Verbrauchsmaterial**
- Katalog mit Bestand, Mindestbestand, Lagerplatz, EAN
- Kompatibilitätsmatrix Modell ↔ Material, Assistent und „Copier depuis"
- Inventur (Eröffnung und Jahreszählung, bucht nur die Differenz)
- Bewegungshistorie mit Filtern, manuelle Korrekturbuchung
- Benutzerliste

**M3 — Kiosk**
- Modell ▸ Farbe ▸ Menge ▸ Person ▸ Buchung, Rückgabe ebenso
- Markenebene erscheint automatisch ab der zweiten Marke
- Modelle ohne Material ausgegraut, Bestand 0 gesperrt, Auto-Reset nach 45 s

**Noch nicht:** RFID-Badges (M4), Wareneingang (M5), Bestellvorschlag (M6),
Saisonauswertung (M7). Bis dahin ersetzt die manuelle Korrekturbuchung unter
`/admin/mouvements` den Wareneingang.

> Die Personenauswahl am Kiosk ist die Übergangslösung bis M4. Die Buchung
> selbst ist bereits die endgültige — der Badge ersetzt später nur das
> Antippen des Namens.

---

## Aufbau

```
app/
  main.py         App-Zusammenbau
  models.py       Datenmodell (SPEC 4)
  importer.py     Excel-Import (SPEC 5)
  services.py     Bestand, Buchungen, Schuljahr, Vorschläge
  db.py           Session + Einstellungen
  auth.py         Basic-Auth für /admin (bis M4)
  routers/        printers · imports · consumables · stock · users · kiosk
  templates/      Jinja2, Oberfläche auf Französisch
  static/app.css  Admin-CSS
  static/kiosk.css Kiosk-CSS — Touch-Flächen ≥ 64 px, altes Chromium-tauglich
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
