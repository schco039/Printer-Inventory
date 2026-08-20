# LGK Printer — Verbrauchsmaterial-Lager

**Projekt-Spezifikation** · Stand 2026-07-31 · Produktivstart geplant zum 01.09.2026

Ablösung des alten WordPress-Plugins durch eine eigenständige Web-Anwendung.
Touch-Kiosk am Lager (RPi), Admin-Oberfläche am PC, Datenbasis aus dem
jährlichen Excel-Export des Hauptlagerprogramms.

---

## 1. Ziel und Umfang

### In Scope

- Bestand an Verbrauchsmaterial (Toner, Trommeln, ggf. Tinte) führen
- Entnahme am Touchscreen: **anmelden → Modell → Farbe → entnehmen**
- Lückenlose Historie: wer hat wann was entnommen oder zurückgelegt
- Wareneingang: gelieferte Ware am PC einpflegen
- Jährlicher Excel-Import des Druckerbestands (keine API vorhanden)
- Auswertungen: Bestand, Mindestbestand, Bestellvorschlag, Verbrauch
- **Saisonanalyse**: in welchen Monaten des Schuljahres welches Material
  gefragt ist, mit Jahresvergleich (Abschnitt 6.4)

### Out of Scope (bewusst)

- Kein Bestellprozess Richtung Lieferant (kein E-Mail-Versand, keine EDI)
- Keine Druckerzählerstände / SNMP-Abfrage
- Keine Schreibrichtung ins Hauptlagerprogramm — der Import ist einseitig
- **3D-Drucker (Ultimaker, MeCreator) und Kartendrucker (Evolis Zenius)**
  werden nicht verwaltet — deren Material läuft nicht über dieses Lager

### Begriff

Das System heißt intern **„Consommables"**, nicht „Toner": es verwaltet neben
Toner auch Trommeln (`DR-…`) und ggf. Plottertinte. Der Materialtyp ist ein
Feld, kein fest verdrahtetes Konzept — sollte später doch Filament dazukommen,
ist das ein Datensatz und keine Änderung am Modell.

---

## 2. Datenlage (Analyse des Exports vom 31.07.2026)

Datei: `ItemsExcelExport_20260731-190230.xlsx`, 1 Blatt, 49 Spalten,
**zweizeiliger Kopf** (Zeile 1 = Gruppe, Zeile 2 = Feldname), Daten ab Zeile 3.

### Mengengerüst

| | |
|---|---:|
| Zeilen gesamt | 127 |
| davon `Groupe de catégories = Printer` | 127 (100 %) |
| nach Zustandsfilter (`Remplacé`/`Volé`/`Hors service` = False) | 96 |
| nach Kategoriefilter (ohne 3D und Kartendrucker) | **90** |
| davon `Type de salle = Warehouse` (nicht installiert) | 20 |
| verschiedene Modelle | **8** |

### Ausgeschlossene Kategorien

Ausschluss über **`ID catégorie d'articles`**, nicht über den Kategorietext —
ID ist stabil, der Text kann im Quellsystem umbenannt werden.

| Kategorie-ID | Bezeichnung | Geräte | Grund |
|---:|---|---:|---|
| 10246 | Imprimante 3D | 4 | Filament wird nicht über dieses Lager geführt |
| 132 | Imprimante à cartes myCard | 2 | Farbbänder werden nicht über dieses Lager geführt |

Die Liste ist **konfigurierbar** (`settings.excluded_category_ids`), nicht
hart codiert. Kommt nächstes Jahr eine weitere Gerätegattung dazu, ist das ein
Häkchen im Admin und kein Code-Deploy.

### Aktive Modelle nach beiden Filtern

| Marke | Modell | Stück | im Entrepôt | Material |
|---|---|---:|---:|---|
| Brother | HL-L8260CDW | 51 | 10 | Toner CMYK + Trommel |
| Brother | MFC-L3770CDW | 19 | 6 | Toner CMYK + Trommel |
| Brother | HL-L5100DN | 12 | 1 | Toner BK + Trommel |
| Brother | HL-L6250DN | 3 | 0 | Toner BK + Trommel |
| Brother | MFC-L8390CDW | 2 | 1 | Toner CMYK + Trommel |
| Brother | HL-L5210dn | 1 | 1 | Toner BK + Trommel |
| Brother | MFC-9140CDN | 1 | 1 | Toner CMYK + Trommel |
| Brother | SC-T5100 | 1 | 0 | Tinte (Plotter) — s. Abschnitt 9 |

**Heute ist alles Brother — das bleibt nicht so.** Jedes Jahr kommen neue
Geräte dazu, nächstes Jahr möglicherweise eine neue Marke. Der Kiosk ist
deshalb **nicht** auf eine Marke fest verdrahtet, sondern passt sich an
(Abschnitt 6.1), und der Import behandelt neue Marken und Modelle als
regulären Vorgang, nicht als Fehler (Abschnitt 5.1).

Epson TM-T88V (6×), HP M602, Lexmark CX410de, Lexmark MS312dn,
Konica Minolta C35P, Brother HL-1670N, HL-5380DN, HL-L8250CDN, MFC-9340CDW,
MFC-L8650CDW sind vollständig `Remplacé = True` und fallen heraus. Deren
Material wird im Kiosk automatisch nicht mehr angeboten — genau der Nutzen
des Jahres-Imports.

### Schlüsselwahl (wichtig)

| Kandidat | Füllgrad | Eindeutig | Urteil |
|---|---:|---|---|
| `ID article` | 127/127 | ja | **Primärschlüssel für Upsert** |
| `S/N` | 127/127 | ja | Sekundär, für Suche/Barcode |
| `Numéro CGIE` | 114/127 | ja (der gefüllten) | **nicht als Schlüssel geeignet** — 13 leer |
| `Numéro d'inventaire` | 0/127 | — | leer, ignorieren |

### Datenqualität — bekannte Fallen

- **`Type d'article` ist verschmutzt** (`BrotherHL-L8250CDN` ohne Leerzeichen,
  `HP M602` vs. Modell `M602(d)n`, `HL 1670N` ohne Marke). → Modellidentität
  wird ausschließlich aus **`Marque` + `Modèle`** gebildet, normalisiert
  (trim, Mehrfach-Leerzeichen, Groß-/Kleinschreibung: `HL-L5210dn` vs. `HL-L5210DN`).
- „Nicht installiert" wird über **`Type de salle = 'Warehouse'`** erkannt, nicht
  über den Text `Salle = 'Entrepôt'` (Textvergleich mit Akzent ist fragil).
- `Adresse IP` nur in 42/96 gefüllt, `Nom annexe` in 22/127 — beides optional.
- `Utilisateur dédié` in 1/127 gefüllt — für uns irrelevant.
- Alle `Propriétés personnalisées` (Spalten 34–43) sind leer.

### Verwendete Spalten beim Import

| Spalte | Ziel | Pflicht |
|---|---|---|
| `ID article` | `printer.source_item_id` | ja |
| `Nom` | `printer.nom` | ja |
| `S/N` | `printer.serial` | ja |
| `Numéro CGIE` | `printer.cgie` | nein |
| `Marque`, `Modèle` | → `printer_model` | ja |
| `Catégorie d'articles` | `printer_model.categorie` | ja |
| `Groupe de catégories` | Importfilter (`= 'Printer'`) | ja |
| `Code entité`, `Nom annexe`, `Salle`, `Type de salle` | Standort | ja/nein |
| `Adresse IP`, `Adresse MAC` | Info | nein |
| `Remplacé`, `Volé`, `Hors service`, `Actif` | Importfilter | ja |
| `Mise en service` | `printer.date_mise_en_service` | nein |
| `Fournisseur` | Info, Vorschlag beim Wareneingang | nein |

Alle übrigen Spalten werden ignoriert, aber die Rohzeile wird pro Import
als JSON mitgeschrieben (Nachvollziehbarkeit, s. `import_run`).

---

## 3. Architektur

```
┌──────────────────────────┐
│  RPi + Touchscreen       │
│  Chromium --kiosk        │
│  Anmeldung: Name + Code  │      LAN / HTTP
│  Barcode optional (HID)  │ ─────────────────┐
└──────────────────────────┘                  │
                                              ▼
┌──────────────────────────┐        ┌──────────────────────┐
│  Büro-PC, Browser        │ ─────▶ │  Docker-Host (NAS /  │
│  /admin, /reception      │        │  kleiner Server)     │
└──────────────────────────┘        │  ┌────────────────┐  │
                                    │  │ caddy (TLS)    │  │
                                    │  ├────────────────┤  │
                                    │  │ app (FastAPI)  │  │
                                    │  ├────────────────┤  │
                                    │  │ volume: db+    │  │
                                    │  │ uploads+backup │  │
                                    │  └────────────────┘  │
                                    └──────────────────────┘
```

**Der RPi ist reiner Client.** Er hält keine Daten. Stirbt die SD-Karte,
kostet das ein Neu-Flashen und keine Datenbank. Das ist der Grund für die
Trennung — nicht Performance.

### Technologie

| Schicht | Wahl | Begründung |
|---|---|---|
| Backend | Python 3.12, **FastAPI** | Import-Logik in Python (openpyxl), ein Stack für alles |
| Templates | **Jinja2 + HTMX** | serverseitig gerendert; alter Pi mit alter Chromium-Version verträgt keine schwere SPA. Kein Build-Step, kein npm |
| CSS | handgeschrieben, ~300 Zeilen | Touch-Targets ≥ 64 px, keine Framework-Abhängigkeit |
| DB | **SQLite** (WAL) | 96 Drucker, ~30 Materialien, 2–3 gleichzeitige Nutzer. Backup = eine Datei. Migration auf Postgres bleibt über SQLAlchemy jederzeit möglich |
| ORM / Migration | SQLAlchemy 2 + Alembic | |
| Excel | openpyxl | bereits verifiziert an der echten Datei |
| Reverse Proxy | Caddy | automatisch TLS im LAN oder plain HTTP |
| Container | Docker Compose | ein `docker compose up -d` |

**Kein React, kein Node.** Begründung: der Kiosk-Client ist alte Hardware,
und das Projekt soll in 5 Jahren noch wartbar sein — genau das Problem, an dem
das WordPress-Plugin gestorben ist.

---

## 4. Datenmodell

```sql
-- ─── Drucker (aus Excel, read-only für Benutzer) ────────────────────

CREATE TABLE printer_model (
  id            INTEGER PRIMARY KEY,
  marque        TEXT NOT NULL,          -- 'Brother'
  modele        TEXT NOT NULL,          -- 'HL-L8260CDW'
  slug          TEXT NOT NULL UNIQUE,   -- 'brother-hl-l8260cdw' (normalisiert)
  categorie     TEXT,                   -- 'Imprimante A4 couleur'
  mapping_ok    INTEGER NOT NULL DEFAULT 0,  -- 0 = noch kein Material zugeordnet
  UNIQUE (marque, modele)
);

CREATE TABLE printer (
  id                  INTEGER PRIMARY KEY,
  source_item_id      INTEGER NOT NULL UNIQUE,   -- 'ID article' aus Excel
  nom                 TEXT NOT NULL,
  serial              TEXT,
  cgie                TEXT,
  model_id            INTEGER NOT NULL REFERENCES printer_model(id),
  code_entite         TEXT,
  annexe              TEXT,
  salle               TEXT,
  salle_type          TEXT,             -- 'Warehouse', 'Office', ...
  statut              TEXT NOT NULL,    -- 'installe' | 'entrepot'
  etat                TEXT NOT NULL,    -- 'actif' | 'absent'  (absent = im letzten Import weg)
  ip                  TEXT,
  mac                 TEXT,
  date_mise_service   DATE,
  fournisseur         TEXT,
  first_seen_import   INTEGER REFERENCES import_run(id),
  last_seen_import    INTEGER REFERENCES import_run(id)
);
CREATE INDEX ix_printer_model ON printer(model_id);

-- ─── Verbrauchsmaterial ─────────────────────────────────────────────

CREATE TABLE consumable (
  id            INTEGER PRIMARY KEY,
  sku           TEXT NOT NULL UNIQUE,   -- 'TN-423BK'
  designation   TEXT NOT NULL,          -- 'Toner Brother TN-423 Noir'
  type          TEXT NOT NULL,          -- 'toner'|'tambour'|'encre'  (erweiterbar)
  couleur       TEXT,                   -- 'BK'|'C'|'M'|'Y'|NULL
  marque        TEXT,
  ean           TEXT,                   -- Barcode auf der Verpackung
  emplacement   TEXT,                   -- Regal/Fach im Lager, z. B. 'A3'
  seuil_alerte  INTEGER NOT NULL DEFAULT 0,   -- Mindestbestand
  actif         INTEGER NOT NULL DEFAULT 1
);

-- Kompatibilitätsmatrix — das Herzstück, wird von Hand gepflegt
CREATE TABLE model_consumable (
  model_id       INTEGER NOT NULL REFERENCES printer_model(id),
  consumable_id  INTEGER NOT NULL REFERENCES consumable(id),
  PRIMARY KEY (model_id, consumable_id)
);

-- ─── Benutzer und Badges ────────────────────────────────────────────

CREATE TABLE app_user (
  id           INTEGER PRIMARY KEY,
  nom          TEXT NOT NULL,
  role         TEXT NOT NULL DEFAULT 'user',   -- 'user' | 'admin'
  mycard_hash  TEXT UNIQUE,   -- HMAC-SHA256(UID, secret) — nie im Klartext
  salto_hash   TEXT UNIQUE,   -- dito
  pin_hash     TEXT,          -- Fallback, wenn kein Badge liest
  actif        INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX ix_user_mycard ON app_user(mycard_hash);
CREATE INDEX ix_user_salto  ON app_user(salto_hash);

-- Badge-Auflösung im Kiosk:
--   SELECT * FROM app_user
--   WHERE actif = 1 AND (mycard_hash = :h OR salto_hash = :h);
-- Welcher der beiden Badges verwendet wurde, wird in movement.badge_type
-- protokolliert.

-- ─── Bestand als Hauptbuch ──────────────────────────────────────────

CREATE TABLE movement (
  id             INTEGER PRIMARY KEY,
  consumable_id  INTEGER NOT NULL REFERENCES consumable(id),
  delta          INTEGER NOT NULL,     -- -1 Entnahme, +5 Lieferung, ±n Korrektur
  motif          TEXT NOT NULL,        -- 'retrait'|'reception'|'retour'|'inventaire'|'rebut'
  user_id        INTEGER REFERENCES app_user(id),
  badge_type     TEXT,                 -- 'mycard'|'salto'|'pin'|NULL (Admin-Buchung)
  printer_id     INTEGER REFERENCES printer(id),   -- optional: für welchen Drucker
  delivery_id    INTEGER REFERENCES delivery(id),
  note           TEXT,
  created_at     TEXT NOT NULL,
  -- denormalisiert beim Insert, damit Saison-Auswertungen ohne
  -- Datumsarithmetik über Millionen Zeilen laufen:
  mois           TEXT NOT NULL,        -- '2026-09'
  annee_scolaire TEXT NOT NULL         -- '2026/27'  (Sept–Aug, s. Abschnitt 6.4)
);
CREATE INDEX ix_mov_consumable ON movement(consumable_id);
CREATE INDEX ix_mov_created    ON movement(created_at);
CREATE INDEX ix_mov_saison     ON movement(annee_scolaire, mois);

CREATE VIEW stock AS
  SELECT c.id AS consumable_id, COALESCE(SUM(m.delta), 0) AS qte
  FROM consumable c LEFT JOIN movement m ON m.consumable_id = c.id
  GROUP BY c.id;

-- Monatsverbrauch je Material — Basis aller Saison-Auswertungen
CREATE VIEW conso_mensuelle AS
  SELECT consumable_id, annee_scolaire, mois,
         CAST(strftime('%m', created_at) AS INTEGER) AS mois_num,
         SUM(-delta) AS sorties
  FROM movement
  WHERE motif = 'retrait'
  GROUP BY consumable_id, annee_scolaire, mois;

-- ─── Wareneingang ───────────────────────────────────────────────────

CREATE TABLE delivery (
  id           INTEGER PRIMARY KEY,
  fournisseur  TEXT,
  bon_livraison TEXT,                  -- Lieferscheinnummer
  date_livr    DATE NOT NULL,
  created_by   INTEGER REFERENCES app_user(id),
  created_at   TEXT NOT NULL,
  note         TEXT
);

CREATE TABLE delivery_line (
  id             INTEGER PRIMARY KEY,
  delivery_id    INTEGER NOT NULL REFERENCES delivery(id),
  consumable_id  INTEGER NOT NULL REFERENCES consumable(id),
  quantite       INTEGER NOT NULL CHECK (quantite > 0)
);

-- ─── Import-Historie ────────────────────────────────────────────────

CREATE TABLE import_run (
  id           INTEGER PRIMARY KEY,
  filename     TEXT NOT NULL,
  sha256       TEXT NOT NULL,
  imported_at  TEXT NOT NULL,
  user_id      INTEGER REFERENCES app_user(id),
  rows_total   INTEGER,
  rows_kept    INTEGER,
  nb_created   INTEGER,
  nb_updated   INTEGER,
  nb_absent    INTEGER,
  raw_json     TEXT      -- gefilterte Rohzeilen, für spätere Rekonstruktion
);
```

**Warum ein Hauptbuch statt eines Bestandsfeldes:** „Wer hat wann was entnommen"
ist damit keine zusätzliche Log-Tabelle, sondern *die* Datenquelle. Bestand ist
immer `SUM(delta)` und kann nicht von der Historie abweichen. Bei den zu
erwartenden Mengen (< 5000 Bewegungen/Jahr) ist das performancemäßig irrelevant.

---

## 5. Excel-Import

### Ablauf

1. **Upload** unter `/admin/import` (Datei bleibt in `/data/uploads` erhalten)
2. **Header-Validierung**: Zeile 2 muss die erwarteten Feldnamen enthalten.
   Fehlt eine Pflichtspalte → Abbruch mit Klartextmeldung
   („Colonne « Modèle » introuvable"). Kein stilles Raten.
3. **Filter**, in dieser Reihenfolge:
   - `Groupe de catégories = 'Printer'`
   - `Remplacé = False` UND `Volé = False` UND `Hors service = False`
   - `ID catégorie d'articles` **nicht** in `settings.excluded_category_ids`
     (Startwert: `{10246, 132}` → 3D-Drucker und myCard-Kartendrucker)

   Ausgeschlossene Zeilen werden nicht verworfen, sondern in der Diff-Vorschau
   getrennt ausgewiesen. Nimmst du später eine Kategorie wieder auf, tauchen
   deren Geräte beim nächsten Import automatisch auf.
4. **Normalisierung** von `Marque`/`Modèle` → Modell anlegen falls neu
   (neue Modelle bekommen `mapping_ok = 0` und erscheinen als Aufgabe)
5. **Upsert** per `ID article`
6. **Statut**: `Type de salle = 'Warehouse'` → `entrepot`, sonst `installe`
7. **Verschwundene Geräte**: alles mit `last_seen_import < aktueller Lauf`
   wird auf `etat = 'absent'` gesetzt — **niemals gelöscht**
8. **Diff-Vorschau vor dem Commit**:
   ```
   127 lignes lues
    90 retenues
    31 ignorées — remplacé / volé / hors service
     6 ignorées — catégorie exclue (4 × Imprimante 3D, 2 × myCard)
   ─────────────────────────────────────────────────────────────
   ✚ 12 nouvelles imprimantes
   ✎  8 modifiées (7 changements de salle, 1 changement d'IP)
   ⊘  4 absentes de cet export → marquées « absent »
   ⚠  1 nouveau modèle sans consommable associé : Brother HL-L5210DN
   ```
   Erst nach „Confirmer" wird in einer Transaktion geschrieben.

### Bewusste Entscheidungen

- Der Import verändert **nie** Bestände oder Bewegungen. Er berührt nur
  `printer` und `printer_model`.
- Ein Import ist idempotent: dieselbe Datei zweimal → zweiter Lauf zeigt
  0 Änderungen.
- Modelle ohne aktive Drucker verschwinden aus dem Kiosk, bleiben aber in der
  DB (die Historie muss lesbar bleiben).

### 5.1 Jährlicher Zuwachs: neue Geräte, Modelle, Marken

Jedes Jahr kommen Drucker dazu. Das ist der **Normalfall**, auf den der Import
ausgelegt ist — nicht ein Sonderfall, der Code-Änderungen braucht.

| Fall | Verhalten |
|---|---|
| Neues Gerät, bekanntes Modell | still angelegt, Material passt automatisch. Null Aufwand |
| **Neues Modell**, bekannte Marke | angelegt mit `mapping_ok = 0`, in der Diff-Vorschau als ⚠ ausgewiesen, im Admin ganz oben in `Compatibilités` |
| **Neue Marke** | wie oben, zusätzlich Hinweis, dass der Kiosk ab jetzt die Markenebene zeigt |
| Modell fällt weg (alle Geräte ersetzt) | verschwindet aus dem Kiosk, bleibt in DB und Historie |

**Nach jedem Import gibt es genau eine offene Aufgabe:** den neuen Modellen
ihr Verbrauchsmaterial zuordnen. Das Dashboard zeigt sie als Aufgabenliste
(*« 2 modèles sans consommables »*), bis sie erledigt ist. Häufig ist das
ein Zweizeiler, weil das neue Modell dieselben Kartuschen nutzt wie ein
vorhandenes — dafür gibt es in `Compatibilités` die Funktion
**« Copier depuis un autre modèle »**.

Das ist der einzige wiederkehrende Handgriff im Jahresrhythmus. Alles andere
am Import läuft ohne Zutun.

---

## 6. Oberflächen — Sprache Französisch

### 6.1 Kiosk (`/kiosk`) — RPi, Touch

Jede Fläche mindestens 64 px hoch, kein Scrollen wo vermeidbar.

**Die Markenebene ist adaptiv.** Solange nur eine Marke aktiv ist, wäre ein
Bildschirm mit einer einzigen Schaltfläche „Brother" reine Zeitverschwendung —
der Kiosk startet dann direkt auf der Modell-Liste. Sobald der Import eine
zweite Marke einbringt, schaltet sich die Markenebene automatisch davor.

Einstellung `kiosk.brand_level`: `auto` (Standard) · `always` · `never`.
Damit kannst du die Markenebene auch dauerhaft erzwingen, falls dir der
automatische Wechsel im Betrieb unangenehm ist.

> **Kein Überraschungseffekt:** taucht im Import eine neue Marke auf, weist die
> Diff-Vorschau ausdrücklich darauf hin: *« Nouvelle marque : Kyocera —
> le kiosque affichera désormais l'écran « Marque » »*. Die Oberfläche ändert
> nie unangekündigt ihre Form.

```
┌──────────────────────────────────────────────┐
│  Consommables — LGK              14:32       │
├──────────────────────────────────────────────┤
│   Brother HL-L8260CDW      51 appareils  ›   │
│   Brother MFC-L3770CDW     19 appareils  ›   │
│   Brother HL-L5100DN       12 appareils  ›   │
│   Brother HL-L6250DN        3 appareils  ›   │
│   Brother MFC-L8390CDW      2 appareils  ›   │
│   Brother HL-L5210DN        1 appareil   ›   │
│   Brother MFC-9140CDN       1 appareil   ›   │
│   Brother SC-T5100          1 appareil   ›   │
├──────────────────────────────────────────────┤
│              [ 🔍 Scanner code-barres ]      │
└──────────────────────────────────────────────┘

  ── ab der zweiten Marke schaltet sich davor: ──

┌──────────────────────────────────────────────┐
│  Consommables — LGK              14:32       │
├──────────────────────────────────────────────┤
│   ┌────────────────┐  ┌────────────────┐     │
│   │    Brother     │  │    Kyocera     │     │
│   │  90 appareils  │  │  12 appareils  │     │
│   └────────────────┘  └────────────────┘     │
└──────────────────────────────────────────────┘
                      ↓ HL-L8260CDW
┌──────────────────────────────────────────────┐
│  ‹ Retour     Brother HL-L8260CDW            │
├──────────────────────────────────────────────┤
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ │
│  │ NOIR   │ │ CYAN   │ │MAGENTA │ │ JAUNE  │ │
│  │TN-423BK│ │TN-423C │ │TN-423M │ │TN-423Y │ │
│  │   4    │ │   2    │ │   0    │ │   3    │ │
│  │ ▬▬▬▬   │ │ ▬▬     │ │ RUPTURE│ │ ▬▬▬    │ │
│  └────────┘ └────────┘ └────────┘ └────────┘ │
│  ┌────────────────────┐                      │
│  │ TAMBOUR  DR-421CL  │  1                   │
│  └────────────────────┘                      │
└──────────────────────────────────────────────┘
                      ↓ NOIR antippen
┌──────────────────────────────────────────────┐
│           Retirer 1 × TN-423BK               │
│                                              │
│              ┌─────────┐                     │
│              │   📇    │                     │
│              └─────────┘                     │
│      Présentez votre badge sur le lecteur    │
│                                              │
│   [ Annuler ]              [ Quantité: 1 + ] │
└──────────────────────────────────────────────┘
                      ↓ Badge
┌──────────────────────────────────────────────┐
│              ✓  Enregistré                   │
│         TN-423BK  −1   ·   Stock : 3         │
│                Paul Muller                   │
│           (retour à l'accueil dans 3 s)      │
└──────────────────────────────────────────────┘
```

Details:
- **Nur Modelle mit aktiven Druckern** werden angezeigt (`etat='actif'`,
  Kategorie nicht ausgeschlossen). Die ausgemusterten Lexmark/HP/Epson sowie
  3D-Drucker und Evolis tauchen nie auf.
- Sortierung nach Gerätezahl absteigend — die 51 HL-L8260CDW stehen oben,
  weil sie die häufigste Entnahme sind. Das spart im Alltag das meiste Suchen.
- **Neues Modell ohne hinterlegtes Material** wird angezeigt, aber ausgegraut
  mit `⚠ consommables non configurés`. Es stillschweigend zu verstecken wäre
  schlechter: der Kollege sucht dann vergeblich und meldet nichts. So sieht er
  den Grund und kann es weitergeben.
- Bestand 0 → Kachel rot, `RUPTURE`, Entnahme gesperrt (Admin kann es erlauben,
  dann entsteht ein negativer Bestand als sichtbares Warnsignal).
- Bestand unter `seuil_alerte` → orange.
- **Auto-Reset** nach 45 s Inaktivität zurück zum Startbildschirm.
- Zweiter Modus `+ Retour` (Material zurücklegen), erreichbar über eine
  kleine Schaltfläche — gleicher Ablauf, `delta = +1`, `motif = 'retour'`.
- **Barcode-Abkürzung**: Scanner tippt S/N oder CGIE eines Druckers → springt
  direkt auf die Farbauswahl des passenden Modells. Scannt er einen EAN eines
  Verbrauchsmaterials → direkt auf dessen Entnahme-Dialog.

### 6.2 Wareneingang (`/reception`) — Büro-PC

```
Réception d'une livraison
─────────────────────────────────────────────
Fournisseur  [ Linster Business Services ▾ ]
Bon n°       [ BL-2026-0412            ]
Date         [ 31.07.2026              ]

Article                       Quantité
[ TN-423BK  Toner noir    ]   [ 10 ]   ✕
[ TN-423C   Toner cyan    ]   [  5 ]   ✕
[ DR-421CL  Tambour       ]   [  2 ]   ✕
[ + Ajouter une ligne / scanner            ]

                     [ Annuler ]  [ Enregistrer ]
```

- Artikel-Feld mit Typeahead über SKU **und** Bezeichnung, oder Barcode scannen.
- „Enregistrer" schreibt alle Zeilen als `movement` mit `motif='reception'`
  und `delivery_id` — eine Lieferung ist damit als Ganzes nachvollziehbar
  und stornierbar (Storno = Gegenbuchungen, keine Löschung).
- Unbekannter Barcode → Dialog „Neues Material anlegen" direkt im Fluss.

### 6.3 Admin (`/admin`)

| Seite | Inhalt |
|---|---|
| `Tableau de bord` | Bestand aller Materialien, Unterdeckungen oben, Rupturen rot |
| `Consommables` | CRUD, Mindestbestand, Lagerplatz, EAN |
| `Compatibilités` | Matrix Modell ↔ Material. Modelle ohne Zuordnung oben mit ⚠ |
| `Imprimantes` | Liste aus dem Import, Filter Salle/Modell/Statut, read-only |
| `Import` | Upload + Diff-Vorschau + Historie der Läufe |
| `Utilisateurs` | Personen, Rollen, Badges anlernen |
| `Mouvements` | Filterbare Historie (Person, Material, Zeitraum), CSV-Export |
| `Propositions` | Bestellvorschlag (s. u.), als CSV/PDF |
| `Saisonnalité` | Heatmap Monat × Material, Jahresvergleich, Spitzenmonate (Abschnitt 6.4) |
| `Inventaire` | Zählliste für Eröffnungs- und Jahresinventur (Abschnitt 10) |
| `Paramètres` | Ausgeschlossene Kategorien, Schuljahresbeginn, Reserve-Faktor N, Lieferzeiten, `kiosk.brand_level` |

**Bestellvorschlag**: Sollbestand pro Material = `max(seuil_alerte, ⌈Anzahl aktiver Drucker des Modells / N⌉)`,
N konfigurierbar (Vorschlag N = 10, also 1 Reservesatz je 10 Geräte),
**zuzüglich des saisonalen Aufschlags** aus Abschnitt 6.4.
Vorschlag = Sollbestand − Istbestand, gruppiert nach Lieferant.

### 6.4 Saisonalität — „wann wird welcher Toner gebraucht"

Der Schuljahresrhythmus wiederholt sich. Rentrée, Prüfungsphasen, Bulletins,
Schuljahresende — der Verbrauch folgt jedes Jahr demselben Muster. Das System
soll dieses Muster sichtbar machen und in die Bestellung einrechnen.

**Bezugszeitraum ist das Schuljahr, nicht das Kalenderjahr.** Ein Kalenderjahr
schneidet den Zyklus mitten durch und macht jeden Jahresvergleich unbrauchbar.
Definition: **1. September – 31. August**, Bezeichnung `2026/27`. Der
Umschaltmonat ist konfigurierbar (`settings.school_year_start_month = 9`).

#### Heatmap (Hauptansicht)

```
Consommation par mois — année scolaire 2026/27      [◂ 2025/26] [2026/27 ▸]

              SEP  OCT  NOV  DÉC  JAN  FÉV  MAR  AVR  MAI  JUN  JUL  AOÛ
TN-423BK       18   11    9    6   14    7   10    8   16   21    4    0
                ▓▓   ▒▒   ▒    ░   ▓▓    ▒   ▒▒    ▒   ▓▓   ██    ░
TN-423C         7    4    3    2    6    3    4    3    6    9    1    0
                ▓▓   ▒    ▒    ░   ▒▒    ▒    ▒    ▒   ▒▒   ██    ░
DR-421CL        2    0    1    0    2    1    0    1    1    3    0    0
                ▓    ░    ▒    ░    ▓    ▒    ░    ▒    ▒   ██    ░

  ░ faible    ▒ moyen    ▓ élevé    █ pic
```

Farbskala je Zeile normiert (jedes Material hat seine eigene Größenordnung —
eine gemeinsame Skala würde die Trommeln unsichtbar machen).

#### Weitere Ansichten auf derselben Datenbasis

| Ansicht | Nutzen |
|---|---|
| **Jahresvergleich** — Linien pro Schuljahr übereinander | zeigt, ob ein Peak wiederkehrt oder ein Ausreißer war |
| **Top-Monate je Material** — „TN-423BK: Spitzen in Juni (21), September (18), Januar (14)" | die Klartext-Antwort auf deine Frage |
| **Bestellkalender** — „Ende Mai bestellen: Juni ist historisch Spitzenmonat, Ø 21 Stück" | handlungsfähig statt nur informativ |
| **Verbrauch nach Salle/Modell** | zeigt, welcher Standort auffällig viel zieht |

#### Saisonaler Aufschlag im Bestellvorschlag

```
saison_faktor(material, monat) = Ø Verbrauch in diesem Monat
                                 ─────────────────────────────
                                 Ø Verbrauch über alle Monate

Empfehlung = Grundbedarf × saison_faktor(nächster Monat) × Vorlauf
```
Vorlauf = Lieferzeit in Wochen (pro Lieferant hinterlegt, Standard 2).
Auf der Bestellvorschlagsseite als Hinweis: *« Juin est historiquement un pic
(×1,9). Commander avant fin mai. »*

#### Datenbasis — der ehrliche Teil

**Es wird bei null begonnen** (Abschnitt 10) — es gibt also keine Altdaten und
im ersten Betriebsjahr folglich auch keine Saisonaussage. Der erste vollständige
Zyklus ist **2026/27**, brauchbare Muster gibt es ab September 2027, wirklich
belastbare ab dem dritten Jahr.

Konsequenz für die Oberfläche: die Saisonseite zeigt im ersten Jahr keine
Prognose, sondern den laufenden Verbrauch plus den Hinweis
*« données insuffisantes — au moins une année scolaire nécessaire »*.
Lieber ehrlich leer als eine Scheingenauigkeit aus vier Monaten.

Die UI zeigt bei jeder Saisonaussage, auf wie vielen Schuljahren sie beruht
(`n = 1` bis `n = 3+`). Eine Prognose aus einem einzigen Jahr wird als solche
gekennzeichnet und nicht als Empfehlung verkauft.

Genau deshalb ist es wichtig, **ab dem ersten Tag lückenlos zu buchen** — jede
Entnahme, die am Kiosk vorbei passiert, fehlt später im Muster. Das ist das
stärkste Argument dafür, den Kiosk vor der Rentrée betriebsbereit zu haben.

---

## 7. Anmeldung mit Zahlencode

RFID wurde nach dem ersten Praxistest verworfen und durch einen Zahlencode
ersetzt. Ausschlaggebend war nicht die Technik — die Karten lieferten stabile
UIDs —, sondern der Betrieb: ein Code braucht keinen Leser, keinen zusätzlichen
Dienst auf dem Pi und funktioniert am Kiosk wie im Browser gleichermaßen.

### Ein Code, zwei Wege

| Ort | Ablauf |
|---|---|
| **Kiosk** | Namenskachel antippen, Code auf der Zifferntastatur, danach entnehmen |
| **Verwaltung** | Anmeldename + derselbe Code |

Am Kiosk wird **zuerst angemeldet**, dann entnommen. Damit sind mehrere
Entnahmen hintereinander ohne erneute Eingabe möglich. Nach zwei Minuten ohne
Bedienung meldet der Kiosk selbsttätig ab — das Gerät steht öffentlich.

```
┌──────────────────────────────────────────────┐
│  Qui êtes-vous ?                     14:32   │
├──────────────────────────────────────────────┤
│   ┌────────────────┐  ┌────────────────┐     │
│   │  Anne Weber    │  │ Conny Schu…    │     │
│   └────────────────┘  └────────────────┘     │
│   ┌────────────────┐                         │
│   │  Paul Muller   │                         │
│   └────────────────┘                         │
└──────────────────────────────────────────────┘
                      ↓
┌──────────────────────────────────────────────┐
│  ‹ Retour     Paul Muller                    │
├──────────────────────────────────────────────┤
│              Entrez votre code               │
│                ● ● ○ ○                       │
│            ┌───┬───┬───┐                     │
│            │ 1 │ 2 │ 3 │                     │
│            │ 4 │ 5 │ 6 │                     │
│            │ 7 │ 8 │ 9 │                     │
│            │ ← │ 0 │OK │                     │
│            └───┴───┴───┘                     │
└──────────────────────────────────────────────┘
```

Vier Ziffern werden automatisch abgeschickt; längere Codes bestätigt man mit
*OK*. Ein angeschlossener Ziffernblock funktioniert ebenfalls.

### Sicherheit — ehrlich betrachtet

Vier Ziffern sind 10 000 Möglichkeiten. **Kein Hashverfahren macht das gegen
automatisiertes Durchprobieren sicher.** Der eigentliche Schutz ist die Sperre:

- Gespeichert wird PBKDF2-SHA256 mit 200 000 Iterationen und Salz je Person
- **Nach fünf Fehlversuchen fünf Minuten gesperrt**, danach von vorn
- Ein Administrator kann sofort entsperren
- Erlaubt sind vier bis zwölf Ziffern; für Administratorkonten ist ein längerer
  Code empfohlen und in der Oberfläche auch so benannt

Für einen Materialschrank im internen Schulnetz ist das angemessen. Für einen
aus dem Internet erreichbaren Dienst wäre es das nicht — die Anwendung gehört
weiterhin ins LAN.

### Ersteinrichtung und Aussperrung

Solange kein Administrator mit Code existiert, führt jeder Aufruf von `/admin`
auf `/setup`, wo der erste angelegt wird. Danach ist diese Seite gesperrt.

Gibt es keinen erreichbaren Administrator mehr, hilft der dokumentierte Weg über
die Datenbank (`docker compose exec`, siehe README). Bewusst kein Hintertür-Konto
und kein festes Notfallpasswort in der `.env`.

### Sitzungen

Signiertes Cookie (`APP_SECRET`), zwei Arten im selben Cookie: `web` mit acht
Stunden, `kiosk` mit zwei Minuten gleitendem Fenster. Wird `APP_SECRET`
geändert, sind alle Sitzungen ungültig — die Codes bleiben gültig.

---

## 8. Deployment

```yaml
# docker-compose.yml
services:
  app:
    build: .
    restart: unless-stopped
    environment:
      - TZ=Europe/Luxembourg
      - APP_SECRET=${APP_SECRET}          # aus .env, für Badge-HMAC + Sessions
      - DEFAULT_LOCALE=fr
    volumes:
      - ./data:/data                       # sqlite, uploads, backups
    expose: ["8000"]

  caddy:
    image: caddy:2-alpine
    restart: unless-stopped
    ports: ["80:80", "443:443"]
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile
      - caddy_data:/data
```

**Backup**: täglicher `VACUUM INTO /data/backups/db-YYYY-MM-DD.sqlite`,
14 Tage Aufbewahrung, per APScheduler im App-Container. Zusätzlich sollte
`./data` in das bestehende Server-Backup aufgenommen werden.

**Kiosk-Autostart auf dem RPi** (kein Docker):

```bash
chromium-browser --kiosk --noerrdialogs --disable-infobars \
  --disable-pinch --overscroll-history-navigation=0 \
  --check-for-update-interval=31536000 \
  http://lager.lgk.lan/kiosk
```
plus `xset s off -dpms` gegen den Bildschirmschoner und `unclutter` zum
Ausblenden des Mauszeigers.

---

## 9. Materialzuordnung — Startdatensatz

**Zu verifizieren, bevor er eingepflegt wird.** Diese Zuordnung ist die
einzige echte Handarbeit im Projekt; bei 11 Modellen ist das ein Nachmittag.
Bitte an den tatsächlich im Lager liegenden Kartons gegenprüfen.

| Modell | Toner | Trommel | Sicherheit |
|---|---|---|---|
| Brother HL-L8260CDW | TN-421 / TN-423 / TN-426 (BK,C,M,Y) | DR-421CL | hoch |
| Brother MFC-L3770CDW | TN-243 / TN-247 (BK,C,M,Y) | DR-243CL | hoch |
| Brother HL-L5100DN | TN-3430 / TN-3480 (BK) | DR-3400 | hoch |
| Brother HL-L6250DN | TN-3430 / TN-3480 (BK) | DR-3400 | mittel |
| Brother HL-L5210DN | TN-3600er Serie (BK) | DR-3600 | mittel |
| Brother MFC-L8390CDW | TN-821er Serie (BK,C,M,Y) | DR-821CL | **niedrig — prüfen** |
| Brother MFC-9140CDN | TN-241 / TN-245 (BK,C,M,Y) | DR-241CL | mittel |

3D-Filament (Ultimaker, MeCreator) und Evolis-Farbbänder entfallen — die
Geräte sind per Kategoriefilter ausgeschlossen.

### Plotter SC-T5100 — bitte am Gerät prüfen

Der Plotter wird mitverwaltet. Zwei Punkte, die vorher zu klären sind:

1. **Die Marke in der Excel ist vermutlich falsch.** „SC-T5100" ist die
   Typenbezeichnung einer **Epson SureColor**-Serie, im Export steht aber
   `Marque = Brother`. Wenn das ein Erfassungsfehler im Hauptlagerprogramm ist,
   sollte er dort korrigiert werden — sonst erscheint das Gerät im Kiosk unter
   der falschen Marke, und beim nächsten Import kommt der Fehler zurück.
   Falls sich das nicht korrigieren lässt, kann die App eine
   Korrektur-Zuordnung halten (`printer_model.marque_override`).
2. **Tintenpatronen-Serie am Gerät ablesen.** Ich gebe hier bewusst keine
   Nummern an — bei einem Einzelgerät mit ungeklärter Marke wäre jede Angabe
   von mir geraten. Bitte den Aufdruck einer eingesetzten Patrone notieren,
   dann sind es vier Datensätze (BK/C/M/Y).

Zusätzlich überlegenswert: bei einem Plotter ist **Rollenpapier** meist der
häufiger verbrauchte Artikel als Tinte. Das Datenmodell trägt das ohne
Änderung (`consumable.type = 'papier'`, `couleur = NULL`) — sag Bescheid, ob
das Papier mit ins Lager soll.

**Umfang der Handarbeit:** 7 Toner-Modelle (4× CMYK + Trommel, 3× BK + Trommel)
plus Plotter → rund **24 Materialstammsätze**. Ein Nachmittag, danach nur noch
Pflege bei neuen Modellen.

Die Verpackungen tragen alle einen EAN — beim ersten Wareneingang einmal
scannen, dann läuft künftig alles über den Barcode.

---

## 10. Start zum Schuljahr 2026/27

Das System startet **bei null zum neuen Schuljahr**. Kein Altdatenimport, keine
geschätzten Anfangsbestände — der erste Datenpunkt ist eine echte Zählung.

### Stichtag

| | |
|---|---|
| **Schuljahresbeginn** | 1. September 2026 |
| **Zeit bis dahin** | rund 4 Wochen (Stand 31.07.2026) |
| **Erstes vollständiges Saisonjahr** | 2026/27 |
| **Saisonauswertung belastbar ab** | ca. September 2027 (`n = 1`), gut ab 2028 (`n = 2`) |

### Eröffnungsinventur

Am Stichtag wird der Lagerbestand einmal physisch gezählt und als Bewegungen
mit `motif = 'inventaire'` gebucht — mit Buchungsdatum 1. September 2026,
auch wenn die Erfassung ein paar Tage dauert. Damit beginnt das Hauptbuch mit
einem sauberen, nachvollziehbaren Anfangsbestand statt mit gesetzten Zahlen.

Für die Zählung selbst gibt es eine eigene Ansicht `Inventaire`: Liste aller
Materialien, pro Zeile ein Zahlenfeld, am Ende ein Buchungslauf. Dieselbe
Ansicht dient später der jährlichen Kontrollzählung — dann bucht sie nur die
**Differenz** zum Sollbestand, sichtbar als `motif='inventaire'` mit Notiz.

### Was bis zum 1. September stehen muss

Minimal betriebsfähig ist das System mit **M0–M3 plus Inventur**: Import,
Materialstamm, Kompatibilitätsmatrix, Kiosk-Entnahme. Wareneingang (M5) kann
in den ersten Wochen notfalls über die Admin-Korrekturbuchung erfolgen; die
Saisonauswertung (M7) wird ohnehin erst in einem Jahr gebraucht.

Sollte der Termin nicht zu halten sein, ist das **kein Datenproblem** — die
Inventur wird dann eben später gebucht und das erste Saisonjahr ist unvollständig.
Wichtiger als der Termin ist, dass ab dem ersten Buchungstag lückenlos gebucht wird.

---

## 11. Meilensteine

| # | Inhalt | Ergebnis | Stand |
|---|---|---|---|
| **M0** | Repo, Docker-Skelett, Health-Check, Alembic | `docker compose up` liefert eine Seite | ✅ fertig |
| **M1** | Datenmodell + Excel-Import inkl. Diff-Vorschau + Druckerliste | Die echte Excel ist importiert, 90 Geräte sichtbar | ✅ fertig |
| **M2** | Consommables-CRUD + Kompatibilitätsmatrix + Inventurmaske | Toner-Zuordnung gepflegt | ✅ fertig |
| **M3** | Kiosk-UI + Bewegungen, noch ohne Badge (Person aus Liste) | Am Touchscreen bedienbar | ✅ fertig |
| — | **Eröffnungsinventur, Produktivstart** | Buchungen laufen | **01.09.2026** |
| **M4** | Badges, HMAC, Anlernen, Kiosk-Buchung per Badge | Restaurant-Logik läuft | ✅ fertig |
| **M5** | Wareneingang + Lieferungen | Bestellungen einpflegbar | ✅ fertig |
| **M6** | Bestellvorschlag, Backup-Job, CSV-Export | Voller Funktionsumfang | ✅ fertig |
| **M7** | Saisonanalyse: Heatmap, Jahresvergleich, Spitzenmonate, saisonaler Bestellvorschlag | ab 2. Schuljahr aussagekräftig | ✅ fertig |

**Alle Meilensteine sind umgesetzt.** Der kritische Pfad ist damit nicht mehr
der Code, sondern die **Materialstammdaten**: die rund 24 Datensätze mit den
richtigen Bestellnummern und die Kompatibilitätsmatrix. Das braucht dich,
nicht mich, und ist die Voraussetzung für die Eröffnungsinventur.

M7 ist funktionsfähig, aber naturgemäß erst ab dem zweiten Schuljahr
aussagekräftig — bis dahin zeigt die Oberfläche die reinen Zahlen und
ausdrücklich keine Prognose.

M7 steht bewusst am Ende: die Auswertung braucht Daten, die erst der Betrieb
erzeugt. Die **Datenerfassung dafür ist aber schon ab M3 vollständig**
(`mois`, `annee_scolaire` werden von der ersten Buchung an geschrieben) —
es geht kein einziger Datenpunkt verloren, während die Ansicht noch fehlt.

**Vorgezogen, weil es das Design beeinflusst:** der Hardware-Test aus
Abschnitt 7 (Salto-Random-UID + Tastaturlayout). Der gehört vor M4, idealerweise
schon parallel zu M0.

---

## 12. Offene Punkte

Alles Folgende braucht **dich**, nicht weiteren Code.

1. **Salto-Badge: Random UID?** → Test mit Reader, blockierend für M4.
   Bei DESFire im Privacy-Mode ändert sich die UID bei jeder Lesung; dann
   bleibt für Salto nur die PIN, myCard funktioniert unabhängig davon weiter.
   Das Zwei-Felder-Modell hält diesen Fall problemlos aus — `salto_hash`
   bleibt dann einfach leer.
2. **Reader-Modell** noch zu beschaffen/prüfen — muss HID-Keyboard-Wedge sein
   und MIFARE Classic + DESFire lesen.
3. **RPi-Modell und OS-Version** unbekannt — bestimmt, wie alt die
   Chromium-Version ist und wie konservativ das CSS sein muss.
4. **Docker-Host**: welcher Rechner konkret, welcher Hostname/DNS-Name im LAN.
5. **Wer darf entnehmen?** Alle Kollegen mit Badge, oder nur ein definierter
   Kreis? Bestimmt, ob unbekannte Badges abgelehnt werden oder eine
   „unbekannte Person"-Buchung erzeugen.
6. **Negativer Bestand** erlauben oder blockieren? Vorschlag: blockieren,
   aber Admin-Override mit Notiz.
7. **Leere Toner**: soll die Rückgabe der leeren Kartusche erfasst werden
   (Entsorgung/Rücksendung)? Wäre ein `motif='rebut'` — kostet fast nichts,
   wenn es von Anfang an mitgedacht wird.
8. **Aufbewahrungsdauer der Personendaten** in `movement` — datenschutzseitig
   sollte eine Frist definiert werden. **Achtung, Zielkonflikt:** die
   Saisonanalyse lebt von mehrjähriger Historie. Vorschlag, der beides löst:
   `user_id` nach 24 Monaten auf NULL setzen, die Bewegung selbst
   (Material, Menge, Datum) unbefristet behalten. Die Saisonauswertung braucht
   die Person nicht.
9. **SC-T5100**: Tintenpatronen-Nummern am Gerät ablesen; Marke im
   Hauptlagerprogramm korrigieren (dort als Brother erfasst, ist vermutlich
   eine Epson SureColor); Rollenpapier mit aufnehmen ja/nein? (Abschnitt 9)
10. **Termin 1. September** — reicht die Zeit für M0–M3 plus Stammdatenpflege,
    oder soll der Produktivstart bewusst später gelegt werden? (Abschnitt 10)

*Erledigt: Start bei null zum Schuljahr 2026/27, kein Altdatenimport ·
Ausschluss 3D-Drucker und Evolis · Badge-Modell mit zwei Feldern je Benutzer ·
Plotter bleibt im Umfang · Negativbestand wird blockiert (Punkt 6) ·
Ergiebigkeitsvarianten als getrennte Datensätze, im Kiosk unter der Farbe
gruppiert.*

---

## 13. Datenschutz

- **Badge-UIDs** werden nur als HMAC-SHA256 gespeichert, nie im Klartext, und
  nicht protokolliert. Die Datenbank taugt damit nicht zum Klonen von Karten.
- **`APP_SECRET` nicht mehr ändern**, sobald Badges angelernt sind — sonst
  passen alle Hashes nicht mehr und jede Karte muss neu angelernt werden.
- **Bewegungshistorie**: Es bleibt bei der Empfehlung aus Abschnitt 12,
  Punkt 8 — `movement.user_id` nach 24 Monaten auf NULL setzen, die Bewegung
  selbst behalten. Die Saisonauswertung braucht die Person nicht, nur
  Material, Menge und Datum. Ein automatischer Lauf dafür ist bewusst **nicht**
  eingebaut: die Frist ist eine Entscheidung der Schule, kein technischer
  Standardwert.
- Die Anwendung gehört ins interne Netz. Sie ist nicht für das offene Internet
  gehärtet.
