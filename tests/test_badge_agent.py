"""Tests für den Weg PC/SC-Leser → Server → Browser."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.badge_bus import einloesen, leeren
from app.models import AppUser, Consumable, Movement
from app.security import badge_hash
from tests.test_web import configure_cmyk, do_import, export  # noqa: F401

TOKEN = "test-agent-token"
UID = "04A0AC92CF1E90"      # 7-Byte-UID, wie vom Gemalto Prox-SU gelesen


@pytest.fixture(autouse=True)
def bus_leeren(monkeypatch):
    leeren()
    from app.config import get_settings
    get_settings.cache_clear()
    monkeypatch.setenv("BADGE_AGENT_TOKEN", TOKEN)
    yield
    leeren()
    get_settings.cache_clear()


def scan(client, uid=UID, station="default", token=TOKEN):
    return client.post(
        "/api/badge/scan",
        data={"uid": uid, "station": station},
        headers={"X-Badge-Token": token},
    )


def test_lesedienst_meldet_und_seite_holt_ab(client):
    assert scan(client).status_code == 200

    r = client.get("/api/badge/pending").json()
    assert r["ready"] is True
    assert r["ticket"]
    assert r["connu"] is False           # noch niemandem zugeordnet


def test_ticket_gilt_nur_einmal(client):
    scan(client)
    ticket = client.get("/api/badge/pending").json()["ticket"]

    assert einloesen(ticket) == badge_hash(UID)
    assert einloesen(ticket) is None      # zweiter Versuch scheitert


def test_lesung_wird_nur_einmal_ausgeliefert(client):
    scan(client)
    assert client.get("/api/badge/pending").json()["ready"] is True
    assert client.get("/api/badge/pending").json()["ready"] is False


def test_falscher_token_wird_abgelehnt(client):
    r = scan(client, token="falsch")
    assert r.status_code == 403
    assert client.get("/api/badge/pending").json()["ready"] is False


def test_stationen_sind_getrennt(client):
    scan(client, station="kiosk")
    assert client.get("/api/badge/pending?station=bureau").json()["ready"] is False
    assert client.get("/api/badge/pending?station=kiosk").json()["ready"] is True


def test_rohe_uid_wird_nicht_zurueckgegeben(client):
    scan(client)
    text = client.get("/api/badge/pending").text
    assert UID not in text
    assert badge_hash(UID) not in text     # auch der Hash bleibt auf dem Server


def test_badge_anlernen_ueber_den_lesedienst(client, db):
    client.post("/admin/utilisateurs", data={"user_id": 0, "nom": "Paul Muller"},
                follow_redirects=True)
    user = db.scalar(select(AppUser))

    scan(client)
    ticket = client.get("/api/badge/pending").json()["ticket"]
    client.post(f"/admin/utilisateurs/{user.id}/badge",
                data={"type": "mycard", "ticket": ticket, "uid": ""},
                follow_redirects=True)

    db.expire_all()
    assert db.get(AppUser, user.id).mycard_hash == badge_hash(UID)


def test_bekannte_karte_liefert_den_namen(client, db):
    client.post("/admin/utilisateurs", data={"user_id": 0, "nom": "Anne Weber"},
                follow_redirects=True)
    user = db.scalar(select(AppUser))
    scan(client)
    ticket = client.get("/api/badge/pending").json()["ticket"]
    client.post(f"/admin/utilisateurs/{user.id}/badge",
                data={"type": "salto", "ticket": ticket, "uid": ""},
                follow_redirects=True)

    scan(client)
    r = client.get("/api/badge/pending").json()
    assert r["connu"] is True
    assert r["nom"] == "Anne Weber"


def test_kiosk_bucht_ueber_ticket(client, db, export):
    do_import(client, export)
    configure_cmyk(client, db)
    noir = db.scalar(select(Consumable).where(Consumable.sku == "TN-423BK"))
    client.post("/admin/inventaire",
                data={"date_comptage": "2026-09-01", "consumable_id": [noir.id], "compte": ["5"]},
                follow_redirects=True)
    client.post("/admin/utilisateurs", data={"user_id": 0, "nom": "Paul Muller"},
                follow_redirects=True)
    user = db.scalar(select(AppUser))

    scan(client)
    ticket = client.get("/api/badge/pending").json()["ticket"]
    client.post(f"/admin/utilisateurs/{user.id}/badge",
                data={"type": "mycard", "ticket": ticket, "uid": ""}, follow_redirects=True)

    # Entnahme am Kiosk, Person kommt über den Leser
    scan(client)
    ticket = client.get("/api/badge/pending").json()["ticket"]
    r = client.post("/kiosk/retrait",
                    data={"consumable_id": noir.id, "quantite": 2, "ticket": ticket})
    assert r.status_code == 200
    assert "Paul Muller" in r.text

    m = db.scalars(select(Movement).where(Movement.motif == "retrait")).first()
    assert m.delta == -2
    assert m.user_id == user.id
    assert m.badge_type == "mycard"


def test_abgelaufenes_ticket_wird_abgelehnt(client, db, export):
    do_import(client, export)
    configure_cmyk(client, db)
    noir = db.scalar(select(Consumable).where(Consumable.sku == "TN-423BK"))
    client.post("/admin/utilisateurs", data={"user_id": 0, "nom": "Paul"}, follow_redirects=True)
    user = db.scalar(select(AppUser))
    scan(client)
    t = client.get("/api/badge/pending").json()["ticket"]
    client.post(f"/admin/utilisateurs/{user.id}/badge",
                data={"type": "mycard", "ticket": t, "uid": ""}, follow_redirects=True)

    r = client.post("/kiosk/retrait",
                    data={"consumable_id": noir.id, "quantite": 1, "ticket": "erfunden"})
    assert r.status_code == 400
    assert "badge" in r.text.lower()
