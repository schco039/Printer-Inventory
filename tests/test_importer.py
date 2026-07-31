"""Tests für den Excel-Import.

Die Testdatei wird synthetisch erzeugt und bildet die Eigenheiten des echten
Exports nach: zweizeiliger Kopf, Feldname bei 'ID article'/'Nom' nur in Zeile 1,
französische Spaltennamen, boolesche Flags.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import Workbook
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.importer import ImportError_, apply_plan, build_plan, model_slug, read_rows
from app.models import Base, Printer, PrinterModel

GROUP_ROW = ["ID article", "Nom", "Données d'inventaire", None, "Type d'article", None, None,
             "Catégorisation", None, "Emplacement", None, None, "Flags (calculés)", None, None, None]
NAME_ROW = [None, None, "S/N", "Numéro CGIE", "Marque", "Modèle", "Groupe de catégories",
            "ID catégorie d'articles", "Catégorie d'articles", "Salle", "Type de salle",
            "Adresse IP", "Actif", "Remplacé", "Volé", "Hors service"]


def row(item_id, nom, sn, cgie, marque, modele, cat_id, cat, salle, salle_type,
        ip=None, remplace=False, vole=False, hs=False, groupe="Printer"):
    return [item_id, nom, sn, cgie, marque, modele, groupe, cat_id, cat, salle,
            salle_type, ip, True, remplace, vole, hs]


def make_xlsx(path: Path, rows: list[list]) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.append(GROUP_ROW)
    ws.append(NAME_ROW)
    for r in rows:
        ws.append(r)
    wb.save(path)
    return path


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, expire_on_commit=False)
    with maker() as s:
        yield s


@pytest.fixture
def sample(tmp_path):
    return make_xlsx(
        tmp_path / "export.xlsx",
        [
            row(1, "26P10093", "SN-1", "26P10093", "Brother", "HL-L8260CDW", 58,
                "Imprimante A4 couleur", "A-DIRECTION", "Office", "10.0.0.1"),
            row(2, "26P10094", "SN-2", None, "Brother", "HL-L8260CDW", 58,
                "Imprimante A4 couleur", "Entrepôt", "Warehouse"),
            row(3, "vieux", "SN-3", "X", "Lexmark", "MS312dn", 39,
                "Imprimante A4 monochrome", "A-GEO", "Office", remplace=True),
            row(4, "vole", "SN-4", "Y", "Brother", "HL-L5100DN", 39,
                "Imprimante A4 monochrome", "A-GEO", "Office", vole=True),
            row(5, "3d", "SN-5", "Z", "Ultimaker", "Ultimaker 3", 10246,
                "Imprimante 3D", "B-CRE8", "EducationalWorkshop"),
            row(6, "carte", "SN-6", "W", "Evolis", "Zenius", 132,
                "Imprimante à cartes myCard", "A-LOGE", "Office"),
            row(7, "pc", "SN-7", "V", "Dell", "Optiplex", 1, "PC", "A-GEO",
                "Office", groupe="Computer"),
        ],
    )


EXCLUDED = [10246, 132]


def test_liest_kopfzeile_ueber_zwei_zeilen(sample):
    rows = read_rows(sample)
    assert len(rows) == 7
    # 'ID article' und 'Nom' stehen nur in der Gruppenzeile
    assert rows[0]["ID article"] == 1
    assert rows[0]["Nom"] == "26P10093"
    assert rows[0]["Modèle"] == "HL-L8260CDW"


def test_fehlende_pflichtspalte_bricht_mit_klartext_ab(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.append(["ID article", "Nom"])
    ws.append([None, None])
    ws.append([1, "x"])
    path = tmp_path / "kaputt.xlsx"
    wb.save(path)

    with pytest.raises(ImportError_) as exc:
        read_rows(path)
    assert "Modèle" in str(exc.value)


def test_filter_zustand_kategorie_und_gruppe(session, sample):
    plan = build_plan(session, read_rows(sample), EXCLUDED)

    assert plan.rows_kept == 2                 # nur die beiden Brother
    assert plan.rows_state_filtered == 2       # remplacé + volé
    assert plan.rows_category_filtered == 2    # 3D + myCard
    assert plan.category_filtered_detail == {
        "Imprimante 3D": 1,
        "Imprimante à cartes myCard": 1,
    }
    assert len(plan.created) == 2


def test_warehouse_wird_zu_entrepot(session, sample):
    plan = build_plan(session, read_rows(sample), EXCLUDED)
    statuts = {r.nom: r.statut for r in plan.created}
    assert statuts["26P10093"] == "installe"
    assert statuts["26P10094"] == "entrepot"


def test_neue_marken_und_modelle_werden_gemeldet(session, sample):
    plan = build_plan(session, read_rows(sample), EXCLUDED)
    assert plan.new_models == ["Brother HL-L8260CDW"]
    assert plan.new_brands == ["Brother"]


def test_apply_legt_modelle_und_drucker_an(session, sample):
    plan = build_plan(session, read_rows(sample), EXCLUDED)
    run = apply_plan(session, plan, filename="export.xlsx", sha256="abc")

    assert run.nb_created == 2
    assert session.scalar(select(PrinterModel).where(PrinterModel.slug == "brother-hl-l8260cdw"))
    printers = session.scalars(select(Printer)).all()
    assert {p.source_item_id for p in printers} == {1, 2}
    assert all(p.etat == "actif" for p in printers)
    # neues Modell hat noch kein Material
    model = session.scalar(select(PrinterModel))
    assert model.mapping_ok == 0


def test_zweiter_lauf_derselben_datei_aendert_nichts(session, sample):
    plan = build_plan(session, read_rows(sample), EXCLUDED)
    apply_plan(session, plan, filename="export.xlsx", sha256="abc")

    plan2 = build_plan(session, read_rows(sample), EXCLUDED)
    assert plan2.created == []
    assert plan2.updated == []
    assert plan2.absent == []
    assert plan2.has_changes is False


def test_verschwundenes_geraet_wird_absent_nicht_geloescht(session, sample, tmp_path):
    apply_plan(session, build_plan(session, read_rows(sample), EXCLUDED),
               filename="export.xlsx", sha256="abc")

    kleiner = make_xlsx(tmp_path / "export2.xlsx", [
        row(1, "26P10093", "SN-1", "26P10093", "Brother", "HL-L8260CDW", 58,
            "Imprimante A4 couleur", "A-DIRECTION", "Office", "10.0.0.1"),
    ])
    plan = build_plan(session, read_rows(kleiner), EXCLUDED)
    assert plan.absent == ["26P10094"]

    apply_plan(session, plan, filename="export2.xlsx", sha256="def")
    printers = {p.source_item_id: p for p in session.scalars(select(Printer)).all()}
    assert len(printers) == 2          # nichts gelöscht
    assert printers[2].etat == "absent"


def test_geraet_kehrt_zurueck_und_wird_wieder_aktiv(session, sample, tmp_path):
    apply_plan(session, build_plan(session, read_rows(sample), EXCLUDED),
               filename="1.xlsx", sha256="a")
    kleiner = make_xlsx(tmp_path / "e2.xlsx", [
        row(1, "26P10093", "SN-1", "26P10093", "Brother", "HL-L8260CDW", 58,
            "Imprimante A4 couleur", "A-DIRECTION", "Office", "10.0.0.1"),
    ])
    apply_plan(session, build_plan(session, read_rows(kleiner), EXCLUDED),
               filename="2.xlsx", sha256="b")

    plan = build_plan(session, read_rows(sample), EXCLUDED)
    assert plan.absent == []
    assert len(plan.updated) == 1
    apply_plan(session, plan, filename="3.xlsx", sha256="c")
    printer = session.scalar(select(Printer).where(Printer.source_item_id == 2))
    assert printer.etat == "actif"


def test_umzug_wird_als_aenderung_erkannt(session, sample, tmp_path):
    apply_plan(session, build_plan(session, read_rows(sample), EXCLUDED),
               filename="1.xlsx", sha256="a")

    umzug = make_xlsx(tmp_path / "e3.xlsx", [
        row(1, "26P10093", "SN-1", "26P10093", "Brother", "HL-L8260CDW", 58,
            "Imprimante A4 couleur", "A-SEPAS", "Office", "10.0.0.1"),
        row(2, "26P10094", "SN-2", None, "Brother", "HL-L8260CDW", 58,
            "Imprimante A4 couleur", "Entrepôt", "Warehouse"),
    ])
    plan = build_plan(session, read_rows(umzug), EXCLUDED)
    assert len(plan.updated) == 1
    champs = {c.champ for c in plan.updated[0][1]}
    assert "Salle" in champs


def test_kategorieausschluss_ist_konfigurierbar(session, sample):
    """Ohne Ausschlussliste kommen 3D-Drucker und Kartendrucker mit."""
    plan = build_plan(session, read_rows(sample), [])
    assert plan.rows_kept == 4
    assert plan.rows_category_filtered == 0


def test_slug_faengt_gross_kleinschreibung_ab():
    assert model_slug("Brother", "HL-L5210dn") == model_slug("Brother", "HL-L5210DN")
    assert model_slug("Brother", "HL-L8260CDW") == "brother-hl-l8260cdw"
