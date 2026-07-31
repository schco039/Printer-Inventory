"""Ende-zu-Ende-Test der Weboberfläche über den ganzen Importfluss."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.test_importer import GROUP_ROW, NAME_ROW, make_xlsx, row  # noqa: F401


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ADMIN_PASSWORD", "")

    # Module neu laden, damit Engine und Settings auf das Testverzeichnis zeigen
    import importlib

    from app import config, db

    config.get_settings.cache_clear()
    importlib.reload(db)
    from app import auth, main

    importlib.reload(auth)
    importlib.reload(main)

    db.create_all()
    with TestClient(main.app) as c:
        yield c


@pytest.fixture
def export(tmp_path):
    return make_xlsx(
        tmp_path / "export.xlsx",
        [
            row(1, "26P10093", "SN-1", "26P10093", "Brother", "HL-L8260CDW", 58,
                "Imprimante A4 couleur", "A-DIRECTION", "Office", "10.0.0.1"),
            row(2, "26P10094", "SN-2", None, "Brother", "HL-L8260CDW", 58,
                "Imprimante A4 couleur", "Entrepôt", "Warehouse"),
            row(5, "3d", "SN-5", "Z", "Ultimaker", "Ultimaker 3", 10246,
                "Imprimante 3D", "B-CRE8", "EducationalWorkshop"),
        ],
    )


def test_healthz(client):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_dashboard_ohne_daten(client):
    r = client.get("/admin")
    assert r.status_code == 200
    assert "Tableau de bord" in r.text


def test_import_zeigt_vorschau_ohne_zu_schreiben(client, export):
    with export.open("rb") as fh:
        r = client.post("/admin/import", files={"fichier": ("export.xlsx", fh)})
    assert r.status_code == 200
    assert "Aperçu de l'import" in r.text
    assert "Imprimante 3D" in r.text  # Ausschluss wird ausgewiesen

    # noch nichts geschrieben
    assert "Aucune imprimante" in client.get("/admin/imprimantes").text


def test_import_anwenden_schreibt_und_zeigt_liste(client, export):
    with export.open("rb") as fh:
        preview = client.post("/admin/import", files={"fichier": ("export.xlsx", fh)})
    token = preview.text.split('action="/admin/import/')[1].split("/appliquer")[0]

    r = client.post(f"/admin/import/{token}/appliquer",
                    data={"filename": "export.xlsx"}, follow_redirects=True)
    assert r.status_code == 200

    liste = client.get("/admin/imprimantes").text
    assert "26P10093" in liste
    assert "Ultimaker" not in liste          # ausgeschlossene Kategorie
    assert "entrepôt" in liste               # Statuskennzeichnung

    dash = client.get("/admin").text
    assert "sans consommables" in dash       # Aufgabe nach neuem Modell


def test_falsches_dateiformat_wird_abgelehnt(client):
    r = client.post("/admin/import", files={"fichier": ("liste.csv", b"a;b;c")})
    assert r.status_code == 400
    assert "xlsx" in r.text


def test_kaputte_datei_zeigt_klartextfehler(client, tmp_path):
    from openpyxl import Workbook

    wb = Workbook()
    wb.active.append(["ID article", "Nom"])
    path = tmp_path / "kaputt.xlsx"
    wb.save(path)

    with path.open("rb") as fh:
        r = client.post("/admin/import", files={"fichier": ("kaputt.xlsx", fh)})
    assert r.status_code == 400
    assert "aucune ligne de données" in r.text or "Colonnes obligatoires" in r.text


def test_filter_nach_statut(client, export):
    with export.open("rb") as fh:
        preview = client.post("/admin/import", files={"fichier": ("export.xlsx", fh)})
    token = preview.text.split('action="/admin/import/')[1].split("/appliquer")[0]
    client.post(f"/admin/import/{token}/appliquer", data={"filename": "export.xlsx"},
                follow_redirects=True)

    entrepot = client.get("/admin/imprimantes?statut=entrepot").text
    assert "26P10094" in entrepot
    assert "26P10093" not in entrepot


def test_kiosk_platzhalter_erreichbar(client):
    r = client.get("/kiosk")
    assert r.status_code == 200
    assert "M3" in r.text
