"""Ende-zu-Ende-Tests der Weboberfläche: Import, Material, Inventur, Kiosk."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import AppUser, Consumable, ModelConsumable, Movement, PrinterModel
from tests.test_importer import make_xlsx, row


@pytest.fixture
def export(tmp_path):
    return make_xlsx(
        tmp_path / "export.xlsx",
        [
            row(1, "26P10093", "SN-1", "26P10093", "Brother", "HL-L8260CDW", 58,
                "Imprimante A4 couleur", "A-DIRECTION", "Office", "10.0.0.1"),
            row(2, "26P10094", "SN-2", None, "Brother", "HL-L8260CDW", 58,
                "Imprimante A4 couleur", "Entrepôt", "Warehouse"),
            row(3, "22P10079", "SN-3", "X", "Brother", "HL-L5100DN", 39,
                "Imprimante A4 monochrome", "A-GEO", "Office"),
            row(5, "3d", "SN-5", "Z", "Ultimaker", "Ultimaker 3", 10246,
                "Imprimante 3D", "B-CRE8", "EducationalWorkshop"),
        ],
    )


def do_import(client, export) -> None:
    with export.open("rb") as fh:
        preview = client.post("/admin/import", files={"fichier": ("export.xlsx", fh)})
    token = preview.text.split('action="/admin/import/')[1].split("/appliquer")[0]
    client.post(f"/admin/import/{token}/appliquer",
                data={"filename": "export.xlsx"}, follow_redirects=True)


def configure_cmyk(client, db, slug="brother-hl-l8260cdw", prefix="TN-423") -> PrinterModel:
    model = db.scalar(select(PrinterModel).where(PrinterModel.slug == slug))
    client.post(
        f"/admin/compatibilites/{model.id}/assistant",
        data={
            "sku": [f"{prefix}BK", f"{prefix}C", f"{prefix}M", f"{prefix}Y", "DR-421CL"],
            "designation": ["", "", "", "", ""],
            "type": ["toner", "toner", "toner", "toner", "tambour"],
            "couleur": ["BK", "C", "M", "Y", ""],
            "seuil": [6, 6, 6, 6, 3],
        },
        follow_redirects=True,
    )
    db.expire_all()
    return model


# ─────────────────────────── Basis ───────────────────────────────────


def test_healthz(client):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_dashboard_ohne_daten(client):
    r = client.get("/admin")
    assert r.status_code == 200
    assert "Tableau de bord" in r.text


# ─────────────────────────── Import ──────────────────────────────────


def test_import_zeigt_vorschau_ohne_zu_schreiben(client, export):
    with export.open("rb") as fh:
        r = client.post("/admin/import", files={"fichier": ("export.xlsx", fh)})
    assert r.status_code == 200
    assert "Aperçu de l'import" in r.text
    assert "Imprimante 3D" in r.text
    assert "Aucune imprimante" in client.get("/admin/imprimantes").text


def test_import_anwenden(client, export):
    do_import(client, export)
    liste = client.get("/admin/imprimantes").text
    assert "26P10093" in liste
    assert "Ultimaker" not in liste
    assert "sans consommables" in client.get("/admin").text


def test_falsches_dateiformat_wird_abgelehnt(client):
    r = client.post("/admin/import", files={"fichier": ("liste.csv", b"a;b;c")})
    assert r.status_code == 400
    assert "xlsx" in r.text


# ─────────────────────────── M2: Assistent ───────────────────────────


def test_assistent_legt_kompletten_satz_an(client, db, export):
    do_import(client, export)
    model = configure_cmyk(client, db)

    consumables = db.scalars(select(Consumable).order_by(Consumable.sku)).all()
    assert [c.sku for c in consumables] == ["DR-421CL", "TN-423BK", "TN-423C", "TN-423M", "TN-423Y"]

    # Designation wird automatisch erzeugt
    noir = next(c for c in consumables if c.sku == "TN-423BK")
    assert "Toner" in noir.designation and "Brother" in noir.designation
    assert noir.couleur == "BK"
    assert noir.seuil_alerte == 6

    # alle mit dem Modell verknüpft, Modell gilt als konfiguriert
    links = db.scalars(
        select(ModelConsumable).where(ModelConsumable.model_id == model.id)
    ).all()
    assert len(links) == 5
    assert db.get(PrinterModel, model.id).mapping_ok == 1

    # Das konfigurierte Modell verschwindet aus der Aufgabenliste,
    # das zweite (HL-L5100DN) bleibt offen.
    dashboard = client.get("/admin").text
    assert "1 modèle sans consommables" in dashboard
    assert "Brother HL-L5100DN" in dashboard


def test_assistent_ueberspringt_leere_zeilen(client, db, export):
    do_import(client, export)
    model = db.scalar(select(PrinterModel).where(PrinterModel.slug == "brother-hl-l5100dn"))
    client.post(
        f"/admin/compatibilites/{model.id}/assistant",
        data={
            "sku": ["TN-3480", "  "],
            "designation": ["", ""],
            "type": ["toner", "tambour"],
            "couleur": ["BK", ""],
            "seuil": [2, 1],
        },
        follow_redirects=True,
    )
    assert db.scalar(select(Consumable).where(Consumable.sku == "TN-3480")) is not None
    assert len(db.scalars(select(Consumable)).all()) == 1


def test_bekannte_referenz_wird_verknuepft_statt_dupliziert(client, db, export):
    """TN-3480 passt in mehrere Modelle — ein Datensatz, zwei Verknüpfungen."""
    do_import(client, export)
    m1 = db.scalar(select(PrinterModel).where(PrinterModel.slug == "brother-hl-l5100dn"))
    m2 = db.scalar(select(PrinterModel).where(PrinterModel.slug == "brother-hl-l8260cdw"))

    for model in (m1, m2):
        client.post(
            f"/admin/compatibilites/{model.id}/assistant",
            data={"sku": ["TN-3480"], "designation": [""], "type": ["toner"],
                  "couleur": ["BK"], "seuil": [2]},
            follow_redirects=True,
        )

    consumables = db.scalars(select(Consumable)).all()
    assert len(consumables) == 1
    assert len(db.scalars(select(ModelConsumable)).all()) == 2


def test_copier_depuis_un_autre_modele(client, db, export):
    do_import(client, export)
    source = configure_cmyk(client, db)
    cible = db.scalar(select(PrinterModel).where(PrinterModel.slug == "brother-hl-l5100dn"))

    client.post(f"/admin/compatibilites/{cible.id}/copier",
                data={"source_id": source.id}, follow_redirects=True)

    assert len(db.scalars(select(Consumable)).all()) == 5      # nichts dupliziert
    assert len(db.scalars(
        select(ModelConsumable).where(ModelConsumable.model_id == cible.id)
    ).all()) == 5


def test_seuil_vorschlag_folgt_geraetezahl(client, db, export):
    do_import(client, export)
    model = db.scalar(select(PrinterModel).where(PrinterModel.slug == "brother-hl-l8260cdw"))
    page = client.get(f"/admin/compatibilites/{model.id}?jeu=cmyk").text
    # 2 Geräte ÷ Reservefaktor 10 → aufgerundet 1
    assert "2 appareils ÷ 10 = 1" in page


def test_delier_setzt_modell_zurueck(client, db, export):
    do_import(client, export)
    model = configure_cmyk(client, db)
    for link in db.scalars(select(ModelConsumable).where(ModelConsumable.model_id == model.id)).all():
        client.post(f"/admin/compatibilites/{model.id}/delier",
                    data={"consumable_id": link.consumable_id}, follow_redirects=True)
    db.expire_all()
    assert db.get(PrinterModel, model.id).mapping_ok == 0


# ─────────────────────────── M2: Inventur ────────────────────────────


def test_eroeffnungsinventur_bucht_bestand(client, db, export):
    do_import(client, export)
    configure_cmyk(client, db)
    ids = [c.id for c in db.scalars(select(Consumable).order_by(Consumable.sku)).all()]

    client.post(
        "/admin/inventaire",
        data={"date_comptage": "2026-09-01", "consumable_id": ids,
              "compte": ["2", "12", "4", "", "3"], "note": "ouverture"},
        follow_redirects=True,
    )

    movements = db.scalars(select(Movement)).all()
    assert len(movements) == 4                       # leere Zeile nicht gebucht
    assert all(m.motif == "inventaire" for m in movements)
    assert {m.annee_scolaire for m in movements} == {"2026/27"}
    assert {m.mois for m in movements} == {"2026-09"}


def test_zweite_zaehlung_bucht_nur_die_differenz(client, db, export):
    do_import(client, export)
    configure_cmyk(client, db)
    noir = db.scalar(select(Consumable).where(Consumable.sku == "TN-423BK"))

    client.post("/admin/inventaire",
                data={"date_comptage": "2026-09-01", "consumable_id": [noir.id], "compte": ["10"]},
                follow_redirects=True)
    client.post("/admin/inventaire",
                data={"date_comptage": "2027-06-30", "consumable_id": [noir.id], "compte": ["7"]},
                follow_redirects=True)

    deltas = [m.delta for m in db.scalars(
        select(Movement).where(Movement.consumable_id == noir.id).order_by(Movement.id)
    ).all()]
    assert deltas == [10, -3]
    assert sum(deltas) == 7


def test_korrekturbuchung(client, db, export):
    do_import(client, export)
    configure_cmyk(client, db)
    noir = db.scalar(select(Consumable).where(Consumable.sku == "TN-423BK"))

    client.post("/admin/mouvements/correction",
                data={"consumable_id": noir.id, "delta": -2, "note": "cartouche défectueuse"},
                follow_redirects=True)

    m = db.scalars(select(Movement)).first()
    assert m.delta == -2 and m.motif == "correction"
    assert "défectueuse" in client.get("/admin/mouvements").text


# ─────────────────────────── Kiosk ───────────────────────────────────


def test_kiosk_verlangt_anmeldung(anon, export):
    """Ohne Anmeldung führt jede Kiosk-Seite zur Namensauswahl."""
    r = anon.get("/kiosk/catalogue", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/kiosk"

    seite = anon.get("/kiosk").text
    assert "Qui êtes-vous" in seite
    assert "Paul Muller" in seite


def test_kiosk_anmeldung_mit_pin(anon, db):
    from tests.conftest import USER_PIN
    user = db.scalar(select(AppUser).where(AppUser.username == "pmuller"))

    r = anon.post(f"/kiosk/code/{user.id}", data={"pin": USER_PIN},
                  follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/kiosk/catalogue"


def test_kiosk_falscher_pin(anon, db):
    user = db.scalar(select(AppUser).where(AppUser.username == "pmuller"))
    r = anon.post(f"/kiosk/code/{user.id}", data={"pin": "0000"})
    assert r.status_code == 401
    assert "Code incorrect" in r.text
    assert anon.get("/kiosk/catalogue", follow_redirects=False).status_code == 303


def test_kiosk_ohne_material_zeigt_modelle_ausgegraut(client, kiosk, export):
    """Modelle ohne Material bleiben sichtbar, aber gesperrt und beschriftet."""
    do_import(client, export)
    page = kiosk.get("/kiosk/catalogue").text
    assert "à configurer" in page
    assert "HL-L8260CDW" in page
    assert "is-off" in page                  # Kachel ist nicht anwählbar
    assert "/kiosk/modele/brother-hl-l8260cdw" not in page


def test_kiosk_zeigt_farben_und_bestand(client, kiosk, db, export):
    do_import(client, export)
    model = configure_cmyk(client, db)
    ids = [c.id for c in db.scalars(select(Consumable).order_by(Consumable.sku)).all()]
    client.post("/admin/inventaire",
                data={"date_comptage": "2026-09-01", "consumable_id": ids,
                      "compte": ["3", "12", "0", "5", "5"]},
                follow_redirects=True)

    page = kiosk.get(f"/kiosk/modele/{model.slug}").text
    assert "NOIR" in page and "CYAN" in page
    assert "RUPTURE" in page
    assert "TN-423BK" in page


def test_kiosk_bucht_auf_die_angemeldete_person(client, kiosk, db, export):
    do_import(client, export)
    configure_cmyk(client, db)
    noir = db.scalar(select(Consumable).where(Consumable.sku == "TN-423BK"))
    client.post("/admin/inventaire",
                data={"date_comptage": "2026-09-01", "consumable_id": [noir.id],
                      "compte": ["5"]}, follow_redirects=True)

    r = kiosk.post("/kiosk/retrait", data={"consumable_id": noir.id, "quantite": 2})
    assert r.status_code == 200
    assert "Paul Muller" in r.text

    paul = db.scalar(select(AppUser).where(AppUser.username == "pmuller"))
    m = db.scalars(select(Movement).where(Movement.motif == "retrait")).first()
    assert m.delta == -2
    assert m.user_id == paul.id


def test_kiosk_blockiert_negativen_bestand(client, kiosk, db, export):
    do_import(client, export)
    configure_cmyk(client, db)
    noir = db.scalar(select(Consumable).where(Consumable.sku == "TN-423BK"))
    client.post("/admin/inventaire",
                data={"date_comptage": "2026-09-01", "consumable_id": [noir.id],
                      "compte": ["1"]}, follow_redirects=True)

    r = kiosk.post("/kiosk/retrait", data={"consumable_id": noir.id, "quantite": 3})
    assert r.status_code == 400
    assert "Stock insuffisant" in r.text
    assert db.scalars(select(Movement).where(Movement.motif == "retrait")).first() is None


def test_kiosk_retour_bucht_positiv(client, kiosk, db, export):
    do_import(client, export)
    configure_cmyk(client, db)
    noir = db.scalar(select(Consumable).where(Consumable.sku == "TN-423BK"))

    kiosk.post("/kiosk/retrait",
               data={"consumable_id": noir.id, "quantite": 1, "sens": "retour"})
    m = db.scalars(select(Movement).where(Movement.motif == "retour")).first()
    assert m.delta == 1


def test_kiosk_abmelden(kiosk):
    kiosk.get("/kiosk/fin", follow_redirects=False)
    assert kiosk.get("/kiosk/catalogue", follow_redirects=False).status_code == 303
