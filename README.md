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

Das Skript erzeugt beim ersten Lauf eine `.env` mit zufälligem `APP_SECRET`,
legt `./data` an, baut das Image und startet den Container. Den ersten
Administrator legst du danach im Browser unter `/setup` an.

Danach erreichbar unter:

| | |
|---|---|
| Admin | `http://<host>:8080/admin` |
| Kiosk | `http://<host>:8080/kiosk` |
| Erste Einrichtung | `http://<host>:8080/setup` |
| Health | `http://<host>:8080/healthz` |

### Update

```bash
git pull && ./install.sh
```

Dasselbe Skript. `.env` und `./data` bleiben unangetastet, Migrationen laufen
beim Start automatisch.

---

## Erste Schritte

0. **Administrator anlegen** — beim ersten Aufruf leitet die Anwendung auf `/setup`
1. **Import** — `/admin/import`, Excel-Export hochladen, Diff-Vorschau prüfen,
   *Confirmer et appliquer*
2. **Konfigurieren** — `/admin/compatibilites`, je Modell auf *Configurer*.
   Der Assistent legt einen kompletten Satz (BK/C/M/Y + Trommel) in einem
   Schritt an; du tippst nur die Bestellnummern. Teilen sich zwei Modelle
   dieselben Kartuschen: *Copier depuis un autre modèle*
3. **Personen** — `/admin/utilisateurs`, Person anlegen. Der Code wird erzeugt
   und einmalig angezeigt — notieren und weitergeben
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
- Anmeldung ▸ Modell ▸ Farbe ▸ Menge ▸ Buchung, Rückgabe ebenso
- Markenebene erscheint automatisch ab der zweiten Marke
- Modelle ohne Material ausgegraut, Bestand 0 gesperrt

**M4 — Anmeldung mit Code**
- Ein Code je Person, gültig am Kiosk (Name + Code) und im Web (Anmeldename + Code)
- Kiosk: Namenskacheln, Zifferntastatur, Sitzung mit Zeitablauf
- PBKDF2-Hash, Sperre nach fünf Fehlversuchen, Entsperren durch Administrator
- Ersteinrichtung über `/setup`, danach gesperrt

**M5 — Wareneingang**
- Lieferung mit Lieferant, Lieferschein-Nr., Datum und Zeilen
- Bucht mit dem Lieferdatum, nicht dem Erfassungstag
- Storno per Gegenbuchung, nie durch Löschen

**M6 — Bestellung und Betrieb**
- Bestellvorschlag je Lieferant: Ziel = max(Mindestbestand, 1 Satz je N Geräte),
  saisonal angepasst
- CSV-Export für Vorschläge und Bewegungen (Excel-tauglich, mit BOM)
- Tägliche SQLite-Sicherung nach `data/backups`, 14 Tage

**M7 — Saisonanalyse**
- Heatmap Monat × Material je Schuljahr (Sept–Aug), Intensität je Zeile normiert
- Spitzenmonate im Klartext, Jahresvergleich ab dem zweiten Schuljahr
- Ohne Historie wird ausdrücklich *keine* Prognose gezeigt, sondern `n/d`

---

## Aufbau

```
app/
  main.py         App-Zusammenbau
  models.py       Datenmodell (SPEC 4)
  importer.py     Excel-Import (SPEC 5)
  services.py     Bestand, Buchungen, Schuljahr, Saison, Vorschläge
  security.py     PIN-Hashing und Sperrlogik
  auth.py         Anmeldung, Sitzungen (Web und Kiosk)
  backup.py       tägliche SQLite-Sicherung
  db.py           Session + Einstellungen
  routers/        auth_routes · printers · imports · consumables · stock ·
                  deliveries · reports · users · kiosk
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

## Anmeldung

Jede Person hat **einen Code** — dieselbe Zahl für beide Wege:

| Wo | Wie |
|---|---|
| **Kiosk** (Touchscreen) | Namenskachel antippen, Code auf der Zifferntastatur eingeben |
| **Verwaltung** (Browser) | Anmeldename + Code |

Nach der Anmeldung am Kiosk kann man mehrere Sachen hintereinander entnehmen;
nach zwei Minuten ohne Bedienung meldet der Kiosk von selbst ab, weil das Gerät
öffentlich steht. Die Dauer steht in den Einstellungen (`kiosk_session_seconds`).

### Ersteinrichtung

Beim ersten Aufruf führt die Anwendung auf **`/setup`** und legt dort den ersten
Administrator an. Danach ist diese Seite gesperrt. Alle weiteren Personen legt
man unter `Utilisateurs` an; der Code wird dabei zufällig erzeugt und
**einmalig angezeigt** — notieren und weitergeben.

### Zur Sicherheit vierstelliger Codes

Vier Ziffern sind 10 000 Möglichkeiten. Dagegen hilft kein Hashverfahren,
sondern die Sperre: **nach fünf Fehlversuchen ist das Konto fünf Minuten
gesperrt**, ein Administrator kann sofort entsperren. Gespeichert wird der Code
nur als PBKDF2-Hash, nie im Klartext.

Für Administratorkonten empfiehlt sich ein **längerer Code** — erlaubt sind vier
bis zwölf Ziffern. Am Kiosk reichen vier; dort wird die Eingabe nach der vierten
Ziffer automatisch abgeschickt, längere Codes bestätigt man mit *OK*.

### Code vergessen

Ein Administrator vergibt unter `Utilisateurs` einen neuen. Gibt es keinen
erreichbaren Administrator mehr, hilft nur der Weg über die Datenbank:

```bash
docker compose exec app python -c "from app.db import SessionLocal; from app.models import AppUser; from app.security import pin_hashen; s=SessionLocal(); u=s.query(AppUser).filter_by(username='cschumacher').first(); u.pin_hash=pin_hashen('123456'); u.bloque_jusqua=None; s.commit(); print('ok')"
```

---

## Betrieb neben anderen Diensten

Die Anwendung ist als Mitbewohner auf einem Docker-Host gedacht, auf dem schon
anderes läuft. Sie braucht keinen Datenbankserver, keinen Cache und keinen
Message Broker — ein Python-Prozess und eine SQLite-Datei.

| | |
|---|---|
| Arbeitsspeicher | rund 100 MB im Betrieb |
| Ablage | `./data` im Projektverzeichnis, sonst nichts |
| Netzwerk | eigenes Compose-Netz, keine Verbindung zu anderen Containern |
| Datenbank | SQLite in der Ablage — kein zusätzlicher Dienst |

### Der einzige echte Kollisionspunkt: der Port

Standard ist **8080**. Ist der auf dem Host belegt, bricht `install.sh` mit
einer klaren Meldung ab, statt einen rohen Docker-Fehler zu zeigen. Dann in
`.env` einen freien Port eintragen und das Skript erneut starten:

```bash
APP_PORT=8090
```

Heißt auf dem Host bereits ein Container `lgk-printer`, lässt sich der Name in
`.env` über `CONTAINER_NAME` ändern.

### Hinter einem vorhandenen Reverse Proxy

Läuft auf dem Host schon Traefik, Nginx Proxy Manager oder Caddy, ist es
sauberer, gar keinen Port zu veröffentlichen:

1. In `docker-compose.yml` den `ports:`-Block auskommentieren
2. Den Container ins Netz des Proxys hängen (Beispiel steht als Kommentar
   unten in derselben Datei)
3. Im Proxy auf `http://lgk-printer:8000` weiterleiten

Die Anwendung wertet `X-Forwarded-*` aus (`uvicorn --proxy-headers`), Links und
Weiterleitungen bleiben also korrekt. Für den Kiosk auf dem Raspberry Pi dann
die Adresse des Proxys eintragen statt `host:8080`.

### Was die Anwendung *nicht* tut

- Sie ändert nichts an anderen Containern, Netzen oder Volumes
- Sie braucht keine Docker-Socket-Einbindung
- Sie schreibt ausschließlich in `./data`

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
- `APP_SECRET` signiert die Sitzungscookies. Wird er geändert, muss sich jeder
  neu anmelden — die Codes selbst bleiben gültig
- Der Dienst gehört ins interne Netz, nicht ins offene Internet
- `*.xlsx` ist ebenfalls in `.gitignore`, damit keine Inventardaten
  versehentlich im Repository landen
