"""Tests für Badges (M4), Wareneingang (M5), Bestellvorschlag (M6)
und Saisonanalyse (M7)."""

from __future__ import annotations

from datetime import date, datetime

import pytest
from sqlalchemy import select

from app.models import AppUser, Consumable, Delivery, Movement, PrinterModel
from app.security import badge_hash, normalize_uid
from app.services import (
    order_proposals,
    record_movement,
    school_year_label,
    seasonal_factors,
)
from tests.test_web import configure_cmyk, do_import, export  # noqa: F401


# ─────────────────────────── Badges (M4) ─────────────────────────────


def test_uid_normalisierung():
    assert normalize_uid("04:a2:1b") == normalize_uid("04A21B") == "04A21B"
    assert normalize_uid(" 04-a2-1b ") == "04A21B"
    assert normalize_uid("") == ""


def test_badge_hash_ist_stabil_und_kein_klartext():
    h = badge_hash("04:A2:1B")
    assert h == badge_hash("04a21b")            # gleiche Karte, andere Schreibweise
    assert h != badge_hash("04A21C")            # andere Karte
    assert len(h) == 64
    assert "04A21B" not in h                    # UID nicht rekonstruierbar
    assert badge_hash("") == ""


def test_badge_anlernen_speichert_nur_den_hash(client, db):
    client.post("/admin/utilisateurs", data={"user_id": 0, "nom": "Paul Muller"},
                follow_redirects=True)
    user = db.scalar(select(AppUser))

    client.post(f"/admin/utilisateurs/{user.id}/badge",
                data={"type": "mycard", "uid": "04:A2:1B"}, follow_redirects=True)
    db.expire_all()
    user = db.get(AppUser, user.id)

    assert user.mycard_hash == badge_hash("04A21B")
    assert user.salto_hash is None
    # Die rohe UID darf nirgends in der Datenbank stehen
    assert "04A21B" not in str(user.__dict__)


def test_beide_badges_pro_person(client, db):
    client.post("/admin/utilisateurs", data={"user_id": 0, "nom": "Anne Weber"},
                follow_redirects=True)
    user = db.scalar(select(AppUser))
    client.post(f"/admin/utilisateurs/{user.id}/badge",
                data={"type": "mycard", "uid": "AAAA1111"}, follow_redirects=True)
    client.post(f"/admin/utilisateurs/{user.id}/badge",
                data={"type": "salto", "uid": "BBBB2222"}, follow_redirects=True)
    db.expire_all()
    user = db.get(AppUser, user.id)
    assert user.mycard_hash and user.salto_hash
    assert user.mycard_hash != user.salto_hash


def test_badge_kann_nicht_zwei_personen_gehoeren(client, db):
    for nom in ("Paul", "Anne"):
        client.post("/admin/utilisateurs", data={"user_id": 0, "nom": nom}, follow_redirects=True)
    paul, anne = db.scalars(select(AppUser).order_by(AppUser.id)).all()

    client.post(f"/admin/utilisateurs/{paul.id}/badge",
                data={"type": "mycard", "uid": "CAFE1234"}, follow_redirects=True)
    r = client.post(f"/admin/utilisateurs/{anne.id}/badge",
                    data={"type": "mycard", "uid": "CAFE1234"}, follow_redirects=True)

    assert "déjà attribué" in r.text
    db.expire_all()
    assert db.get(AppUser, anne.id).mycard_hash is None


def test_kiosk_bucht_per_badge(client, db, export):
    do_import(client, export)
    configure_cmyk(client, db)
    noir = db.scalar(select(Consumable).where(Consumable.sku == "TN-423BK"))
    client.post("/admin/inventaire",
                data={"date_comptage": "2026-09-01", "consumable_id": [noir.id], "compte": ["5"]},
                follow_redirects=True)
    client.post("/admin/utilisateurs", data={"user_id": 0, "nom": "Paul Muller"},
                follow_redirects=True)
    user = db.scalar(select(AppUser))
    client.post(f"/admin/utilisateurs/{user.id}/badge",
                data={"type": "salto", "uid": "DEAD-BEEF"}, follow_redirects=True)

    r = client.post("/kiosk/retrait",
                    data={"consumable_id": noir.id, "quantite": 1, "badge": "dead:beef"})
    assert r.status_code == 200
    assert "Paul Muller" in r.text

    m = db.scalars(select(Movement).where(Movement.motif == "retrait")).first()
    assert m.user_id == user.id
    assert m.badge_type == "salto"


def test_kiosk_lehnt_unbekannten_badge_ab(client, db, export):
    do_import(client, export)
    configure_cmyk(client, db)
    noir = db.scalar(select(Consumable).where(Consumable.sku == "TN-423BK"))
    client.post("/admin/inventaire",
                data={"date_comptage": "2026-09-01", "consumable_id": [noir.id], "compte": ["5"]},
                follow_redirects=True)
    client.post("/admin/utilisateurs", data={"user_id": 0, "nom": "Paul"}, follow_redirects=True)
    user = db.scalar(select(AppUser))
    client.post(f"/admin/utilisateurs/{user.id}/badge",
                data={"type": "mycard", "uid": "1111"}, follow_redirects=True)

    r = client.post("/kiosk/retrait",
                    data={"consumable_id": noir.id, "quantite": 1, "badge": "9999"})
    assert r.status_code == 403
    assert "Badge inconnu" in r.text
    assert db.scalars(select(Movement).where(Movement.motif == "retrait")).first() is None


def test_ohne_angelernte_badges_bleibt_die_namensliste(client, db, export):
    do_import(client, export)
    configure_cmyk(client, db)
    noir = db.scalar(select(Consumable).where(Consumable.sku == "TN-423BK"))
    client.post("/admin/utilisateurs", data={"user_id": 0, "nom": "Paul"}, follow_redirects=True)

    page = client.get(f"/kiosk/retrait/{noir.id}").text
    assert "Présentez votre badge" not in page
    assert "Paul" in page


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


def test_badge_feld_ist_sichtbar_kein_passwortfeld(client, db):
    """type=password verbarg die Eingabe — man sah nicht, ob der Leser sendet."""
    client.post("/admin/utilisateurs", data={"user_id": 0, "nom": "Anne"},
                follow_redirects=True)
    page = client.get("/admin/utilisateurs").text
    assert 'name="uid"' in page
    assert 'type="password" name="uid"' not in page


def test_leser_diagnoseseite_erreichbar(client):
    page = client.get("/admin/badge-test")
    assert page.status_code == 200
    assert "UID aléatoire" in page.text
