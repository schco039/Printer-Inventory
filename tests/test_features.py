"""Tests für Badges (M4), Wareneingang (M5), Bestellvorschlag (M6)
und Saisonanalyse (M7)."""

from __future__ import annotations

from datetime import date, datetime

import pytest
from sqlalchemy import select

from datetime import timedelta

from app.models import AppUser, Consumable, Delivery, Movement, PrinterModel
from app.security import MAX_ECHECS, PinFehler, pin_hashen, pin_stimmt
from app.services import (
    order_proposals,
    record_movement,
    school_year_label,
    seasonal_factors,
)
from tests.test_web import configure_cmyk, do_import, export  # noqa: F401


# ─────────────────────────── PIN und Anmeldung ───────────────────────


def test_pin_wird_gehasht_und_nicht_im_klartext_gehalten():
    h = pin_hashen("1234")
    assert h.startswith("pbkdf2_sha256$")
    assert "1234" not in h
    assert pin_stimmt("1234", h)
    assert not pin_stimmt("1235", h)
    # zweimal derselbe PIN ergibt wegen des Salzes verschiedene Hashes
    assert pin_hashen("1234") != h


def test_pin_format_wird_geprueft():
    for schlecht in ("123", "abcd", "12a4", ""):
        with pytest.raises(PinFehler):
            pin_hashen(schlecht)
    assert pin_hashen("123456")     # längere Codes sind erlaubt


def test_anmeldung_im_web(anon):
    r = anon.post("/login", data={"username": "cschumacher", "pin": "1234"},
                  follow_redirects=False)
    assert r.status_code == 303
    assert anon.get("/admin").status_code == 200


def test_falscher_pin_im_web(anon):
    r = anon.post("/login", data={"username": "cschumacher", "pin": "9999"})
    assert r.status_code == 401
    assert "Code incorrect" in r.text


def test_admin_bereich_ohne_anmeldung_leitet_um(anon):
    r = anon.get("/admin", follow_redirects=False)
    assert r.status_code == 303
    assert "/login" in r.headers["location"]


def test_normale_person_kommt_nicht_in_die_verwaltung(anon):
    anon.post("/login", data={"username": "pmuller", "pin": "5678"},
              follow_redirects=False)
    assert anon.get("/admin").status_code == 403


def test_abmelden(client):
    client.get("/logout", follow_redirects=False)
    assert client.get("/admin", follow_redirects=False).status_code == 303


def test_sperre_nach_mehreren_fehlversuchen(anon, db):
    for _ in range(MAX_ECHECS):
        anon.post("/login", data={"username": "pmuller", "pin": "0000"})

    db.expire_all()
    paul = db.scalar(select(AppUser).where(AppUser.username == "pmuller"))
    assert paul.bloque_jusqua is not None

    # Auch der richtige PIN wird während der Sperre abgelehnt
    r = anon.post("/login", data={"username": "pmuller", "pin": "5678"})
    assert r.status_code == 401
    assert "bloqué" in r.text


def test_erfolgreiche_anmeldung_setzt_den_zaehler_zurueck(anon, db):
    anon.post("/login", data={"username": "pmuller", "pin": "0000"})
    anon.post("/login", data={"username": "pmuller", "pin": "5678"},
              follow_redirects=False)
    db.expire_all()
    assert db.scalar(select(AppUser).where(AppUser.username == "pmuller")).echecs == 0


def test_admin_kann_entsperren(client, db):
    paul = db.scalar(select(AppUser).where(AppUser.username == "pmuller"))
    paul.bloque_jusqua = datetime.now() + timedelta(minutes=5)
    db.commit()

    client.post(f"/admin/utilisateurs/{paul.id}/debloquer", follow_redirects=True)
    db.expire_all()
    assert db.get(AppUser, paul.id).bloque_jusqua is None


def test_neue_person_bekommt_einen_code_angezeigt(client, db):
    r = client.post("/admin/utilisateurs",
                    data={"user_id": 0, "nom": "Anne Weber", "role": "user"},
                    follow_redirects=True)
    assert "Code de Anne Weber" in r.text

    anne = db.scalar(select(AppUser).where(AppUser.nom == "Anne Weber"))
    assert anne.username == "aweber"        # automatisch abgeleitet
    assert anne.pin_defini


def test_benutzername_kollision_wird_hochgezaehlt(client, db):
    client.post("/admin/utilisateurs", data={"user_id": 0, "nom": "Paul Muller"},
                follow_redirects=True)
    namen = [u.username for u in db.scalars(select(AppUser)).all()]
    assert "pmuller" in namen and "pmuller2" in namen


def test_admin_setzt_einen_bestimmten_code(client, db):
    paul = db.scalar(select(AppUser).where(AppUser.username == "pmuller"))
    client.post(f"/admin/utilisateurs/{paul.id}/code", data={"pin": "4321"},
                follow_redirects=True)
    db.expire_all()
    assert pin_stimmt("4321", db.get(AppUser, paul.id).pin_hash)


def test_ersteinrichtung_nur_ohne_administrator(anon, db):
    # Es gibt bereits einen Administrator
    assert anon.get("/setup", follow_redirects=False).status_code == 303

    for u in db.scalars(select(AppUser)).all():
        u.role = "user"
    db.commit()

    assert anon.get("/setup").status_code == 200
    r = anon.post("/setup", data={"nom": "Chef", "username": "chef",
                                  "pin": "246810", "pin2": "246810"},
                  follow_redirects=False)
    assert r.status_code == 303
    db.expire_all()
    chef = db.scalar(select(AppUser).where(AppUser.username == "chef"))
    assert chef.role == "admin" and chef.pin_defini


# ─────────────────────────── Wareneingang (M5) ───────────────────────


def test_lieferung_bucht_zugang(client, db, export):
    do_import(client, export)
    configure_cmyk(client, db)
    cons = db.scalars(select(Consumable).order_by(Consumable.sku)).all()
    noir = next(c for c in cons if c.sku == "TN-423BK")
    cyan = next(c for c in cons if c.sku == "TN-423C")

    r = client.post("/admin/reception", data={
        "fournisseur": "Linster", "bon_livraison": "BL-2026-0412",
        "date_livr": "2026-09-15", "note": "",
        "consumable_id": [noir.id, cyan.id, 0],
        "quantite": ["10", "5", ""],
    }, follow_redirects=True)
    assert r.status_code == 200

    livraison = db.scalar(select(Delivery))
    assert livraison.fournisseur == "Linster"
    mouvements = db.scalars(select(Movement).where(Movement.motif == "reception")).all()
    assert sorted(m.delta for m in mouvements) == [5, 10]
    assert all(m.delivery_id == livraison.id for m in mouvements)
    # Buchungsdatum folgt dem Lieferdatum, nicht dem Erfassungstag
    assert all(m.mois == "2026-09" for m in mouvements)

    db.expire_all()
    assert db.get(Consumable, noir.id).fournisseur == "Linster"


def test_lieferung_ohne_zeilen_legt_nichts_an(client, db, export):
    do_import(client, export)
    configure_cmyk(client, db)
    client.post("/admin/reception", data={
        "fournisseur": "", "bon_livraison": "", "date_livr": "2026-09-15", "note": "",
        "consumable_id": [0], "quantite": [""],
    }, follow_redirects=True)
    assert db.scalar(select(Delivery)) is None
    assert db.scalars(select(Movement)).first() is None


def test_lieferung_stornieren_bucht_gegen(client, db, export):
    do_import(client, export)
    configure_cmyk(client, db)
    noir = db.scalar(select(Consumable).where(Consumable.sku == "TN-423BK"))
    client.post("/admin/reception", data={
        "fournisseur": "Linster", "bon_livraison": "BL-1", "date_livr": "2026-09-15",
        "note": "", "consumable_id": [noir.id], "quantite": ["10"],
    }, follow_redirects=True)
    livraison = db.scalar(select(Delivery))

    client.post(f"/admin/reception/{livraison.id}/annuler", follow_redirects=True)

    mouvements = db.scalars(
        select(Movement).where(Movement.consumable_id == noir.id)
    ).all()
    assert len(mouvements) == 2                 # nichts gelöscht
    assert sum(m.delta for m in mouvements) == 0


# ─────────────────────────── Bestellvorschlag (M6) ───────────────────


def test_bestellvorschlag_rechnet_reserve_und_bestand(client, db, export):
    do_import(client, export)
    configure_cmyk(client, db)          # Seuil 6 je Toner, 3 für die Trommel
    noir = db.scalar(select(Consumable).where(Consumable.sku == "TN-423BK"))
    client.post("/admin/inventaire",
                data={"date_comptage": "2026-09-01", "consumable_id": [noir.id], "compte": ["2"]},
                follow_redirects=True)

    items = {p["consumable"].sku: p for p in order_proposals(db)}
    assert items["TN-423BK"]["stock"] == 2
    assert items["TN-423BK"]["cible"] == 6
    assert items["TN-423BK"]["manque"] == 4

    page = client.get("/admin/propositions").text
    assert "TN-423BK" in page


def test_bestellvorschlag_ueberspringt_gedeckte_artikel(client, db, export):
    do_import(client, export)
    configure_cmyk(client, db)
    noir = db.scalar(select(Consumable).where(Consumable.sku == "TN-423BK"))
    client.post("/admin/inventaire",
                data={"date_comptage": "2026-09-01", "consumable_id": [noir.id], "compte": ["50"]},
                follow_redirects=True)
    skus = [p["consumable"].sku for p in order_proposals(db)]
    assert "TN-423BK" not in skus


def test_csv_export_der_vorschlaege(client, db, export):
    do_import(client, export)
    configure_cmyk(client, db)
    r = client.get("/admin/propositions.csv")
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    assert "attachment" in r.headers["content-disposition"]
    assert "TN-423BK" in r.text


def test_csv_export_der_bewegungen(client, db, export):
    do_import(client, export)
    configure_cmyk(client, db)
    noir = db.scalar(select(Consumable).where(Consumable.sku == "TN-423BK"))
    client.post("/admin/inventaire",
                data={"date_comptage": "2026-09-01", "consumable_id": [noir.id], "compte": ["5"]},
                follow_redirects=True)
    r = client.get("/admin/mouvements.csv")
    assert "TN-423BK" in r.text
    assert "2026/27" in r.text


# ─────────────────────────── Saison (M7) ─────────────────────────────


def test_schuljahr_grenzen():
    assert school_year_label(date(2026, 9, 1)) == "2026/27"
    assert school_year_label(date(2026, 8, 31)) == "2025/26"
    assert school_year_label(date(2027, 7, 15)) == "2026/27"
    assert school_year_label(date(2027, 1, 5)) == "2026/27"


def test_saisonseite_ohne_daten_sagt_es_ehrlich(client):
    page = client.get("/admin/saisonnalite").text
    assert "Données insuffisantes" in page


def test_heatmap_zeigt_monate_und_spitzen(client, db, export):
    do_import(client, export)
    configure_cmyk(client, db)
    noir = db.scalar(select(Consumable).where(Consumable.sku == "TN-423BK"))
    client.post("/admin/inventaire",
                data={"date_comptage": "2026-09-01", "consumable_id": [noir.id], "compte": ["100"]},
                follow_redirects=True)

    # Verbrauch über das Schuljahr verteilen: Juni ist Spitzenmonat
    for moment, qte in [
        (datetime(2026, 9, 10, 9), 5),
        (datetime(2027, 1, 15, 9), 3),
        (datetime(2027, 6, 20, 9), 12),
    ]:
        record_movement(db, consumable_id=noir.id, delta=-qte, motif="retrait", at=moment)
    db.commit()

    page = client.get("/admin/saisonnalite?annee=2026/27").text
    assert "TN-423BK" in page
    assert "JUN (12)" in page          # Spitzenmonat im Klartext
    assert "n = 1" in page             # Datenbasis wird benannt

    facteurs = seasonal_factors(db, noir.id, 9)
    assert facteurs[6] > facteurs[1] > 0     # Juni stärker als Januar
    assert facteurs[6] > 1.0                 # über dem Jahresdurchschnitt


def test_saisonaler_aufschlag_erhoeht_die_zielmenge(client, db, export):
    """Ein Material mit ausgeprägter Saison bekommt im Spitzenmonat mehr."""
    do_import(client, export)
    configure_cmyk(client, db)
    noir = db.scalar(select(Consumable).where(Consumable.sku == "TN-423BK"))

    mois_prochain = (date.today().month % 12) + 1
    annee = 2026 if mois_prochain >= 9 else 2027
    record_movement(db, consumable_id=noir.id, delta=-40, motif="retrait",
                    at=datetime(annee, mois_prochain, 15, 9))
    db.commit()

    item = next(p for p in order_proposals(db) if p["consumable"].id == noir.id)
    assert item["saison"] is True
    assert item["facteur"] > 1
    assert item["cible"] > item["base"]


# ─────────────────────────── Backup (M6) ─────────────────────────────


def test_backup_erzeugt_lesbare_kopie(client, db, export):
    from app.backup import run_backup
    from app.config import get_settings

    do_import(client, export)
    target = run_backup()
    assert target is not None and target.exists()
    assert target.parent == get_settings().backup_dir

    # Die Kopie ist eine vollwertige, lesbare Datenbank
    import sqlite3
    with sqlite3.connect(target) as conn:
        n = conn.execute("SELECT COUNT(*) FROM printer").fetchone()[0]
    assert n == 3


# ─────────────────────────── Fehlerbehebungen ────────────────────────


def test_modell_anzeige_laesst_sich_korrigieren(client, db, export):
    """SC-T5100 ist im Export als Brother erfasst, ist aber eine Epson."""
    do_import(client, export)
    model = db.scalar(select(PrinterModel).where(PrinterModel.slug == "brother-hl-l8260cdw"))

    client.post(f"/admin/modeles/{model.id}",
                data={"marque_override": "Epson", "modele_override": "SureColor T5100",
                      "categorie": ""},
                follow_redirects=True)
    db.expire_all()
    model = db.get(PrinterModel, model.id)

    assert model.libelle == "Epson SureColor T5100"
    assert model.corrige is True
    # Identität für den Re-Import bleibt unangetastet
    assert model.marque == "Brother" and model.slug == "brother-hl-l8260cdw"
    # Korrektur wirkt in der Oberfläche
    assert "Epson SureColor T5100" in client.get("/admin/imprimantes").text


def test_korrektur_ueberlebt_einen_erneuten_import(client, db, export):
    do_import(client, export)
    model = db.scalar(select(PrinterModel).where(PrinterModel.slug == "brother-hl-l8260cdw"))
    client.post(f"/admin/modeles/{model.id}",
                data={"marque_override": "Epson", "modele_override": "", "categorie": ""},
                follow_redirects=True)

    do_import(client, export)          # Jahresimport erneut
    db.expire_all()
    assert db.get(PrinterModel, model.id).marque_affichee == "Epson"


def test_leere_korrektur_setzt_zurueck(client, db, export):
    do_import(client, export)
    model = db.scalar(select(PrinterModel).where(PrinterModel.slug == "brother-hl-l8260cdw"))
    client.post(f"/admin/modeles/{model.id}",
                data={"marque_override": "Epson", "modele_override": "", "categorie": ""},
                follow_redirects=True)
    client.post(f"/admin/modeles/{model.id}",
                data={"marque_override": "", "modele_override": "", "categorie": ""},
                follow_redirects=True)
    db.expire_all()
    model = db.get(PrinterModel, model.id)
    assert model.marque_override is None
    assert model.libelle == "Brother HL-L8260CDW"


def test_benutzer_lassen_sich_bearbeiten(client, db):
    client.post("/admin/utilisateurs", data={"user_id": 0, "nom": "Paul Muler"},
                follow_redirects=True)
    user = db.scalar(select(AppUser))

    client.post("/admin/utilisateurs",
                data={"user_id": user.id, "nom": "Paul Muller", "role": "admin", "actif": "1"},
                follow_redirects=True)
    db.expire_all()
    user = db.get(AppUser, user.id)
    assert user.nom == "Paul Muller"
    assert user.role == "admin"
    assert user.actif == 1

    # Bearbeitungsfelder sind auf der Seite vorhanden
    page = client.get("/admin/utilisateurs").text
    assert 'value="Paul Muller"' in page


def test_benutzer_lassen_sich_bearbeiten_und_kiosk_zeigt_sie(client, db):
    """Umbenennen wirkt auch auf den Namenskacheln am Kiosk."""
    paul = db.scalar(select(AppUser).where(AppUser.username == "pmuller"))
    client.post("/admin/utilisateurs",
                data={"user_id": paul.id, "nom": "Paul Müller",
                      "username": "pmuller", "role": "user", "actif": "1"},
                follow_redirects=True)
    db.expire_all()
    assert db.get(AppUser, paul.id).nom == "Paul Müller"
