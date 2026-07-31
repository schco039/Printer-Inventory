"""LGK Printer — Verbrauchsmaterial-Lager.

M0/M1: Excel-Import mit Diff-Vorschau und Druckerliste.
Kiosk (M3), Material (M2), Wareneingang (M5) folgen — siehe docs/SPEC.md.
"""

from __future__ import annotations

import shutil
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import admin_protection_enabled, require_admin
from app.config import get_settings
from app.db import get_session, get_setting, seed_settings, SessionLocal
from app.importer import (
    ImportError_,
    apply_plan,
    build_plan,
    read_rows,
    sha256_of,
)
from app.models import Consumable, ImportRun, Printer, PrinterModel

BASE_DIR = Path(__file__).resolve().parent
settings = get_settings()

@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings.ensure_dirs()
    with SessionLocal() as session:
        seed_settings(session)
    yield


app = FastAPI(
    title="LGK — Gestion des consommables",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")
templates.env.globals["admin_protected"] = admin_protection_enabled


# ─────────────────────────── Betrieb ─────────────────────────────────


@app.get("/healthz", include_in_schema=False)
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse("/admin", status_code=302)


@app.get("/kiosk", response_class=HTMLResponse, include_in_schema=False)
def kiosk(request: Request) -> HTMLResponse:
    """Platzhalter — der Kiosk kommt in M3 (siehe docs/SPEC.md 6.1)."""
    return templates.TemplateResponse(request, "kiosk_placeholder.html", {})


# ─────────────────────────── Admin ───────────────────────────────────


@app.get("/admin", response_class=HTMLResponse)
def dashboard(
    request: Request,
    session: Session = Depends(get_session),
    _user: str = Depends(require_admin),
) -> HTMLResponse:
    nb_printers = session.scalar(select(func.count()).select_from(Printer).where(Printer.etat == "actif")) or 0
    nb_entrepot = (
        session.scalar(
            select(func.count())
            .select_from(Printer)
            .where(Printer.etat == "actif", Printer.statut == "entrepot")
        )
        or 0
    )
    nb_absent = session.scalar(select(func.count()).select_from(Printer).where(Printer.etat == "absent")) or 0
    nb_consumables = session.scalar(select(func.count()).select_from(Consumable)) or 0

    # Modelle mit aktiven Geräten, aber ohne zugeordnetes Material (SPEC 5.1)
    a_mapper = session.scalars(
        select(PrinterModel)
        .join(Printer, Printer.model_id == PrinterModel.id)
        .where(Printer.etat == "actif", PrinterModel.mapping_ok == 0)
        .group_by(PrinterModel.id)
        .order_by(func.count(Printer.id).desc())
    ).all()

    marques = session.scalars(
        select(PrinterModel.marque)
        .join(Printer, Printer.model_id == PrinterModel.id)
        .where(Printer.etat == "actif")
        .group_by(PrinterModel.marque)
    ).all()

    last_import = session.scalars(select(ImportRun).order_by(ImportRun.id.desc()).limit(1)).first()

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "nb_printers": nb_printers,
            "nb_entrepot": nb_entrepot,
            "nb_absent": nb_absent,
            "nb_consumables": nb_consumables,
            "a_mapper": a_mapper,
            "marques": sorted(marques),
            "last_import": last_import,
        },
    )


@app.get("/admin/imprimantes", response_class=HTMLResponse)
def printers_list(
    request: Request,
    q: str = "",
    statut: str = "",
    modele: str = "",
    etat: str = "actif",
    session: Session = Depends(get_session),
    _user: str = Depends(require_admin),
) -> HTMLResponse:
    stmt = select(Printer).join(PrinterModel).order_by(Printer.nom)
    if etat:
        stmt = stmt.where(Printer.etat == etat)
    if statut:
        stmt = stmt.where(Printer.statut == statut)
    if modele:
        stmt = stmt.where(PrinterModel.slug == modele)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            Printer.nom.ilike(like)
            | Printer.serial.ilike(like)
            | Printer.cgie.ilike(like)
            | Printer.salle.ilike(like)
        )

    printers = session.scalars(stmt).all()
    models = session.scalars(select(PrinterModel).order_by(PrinterModel.marque, PrinterModel.modele)).all()

    return templates.TemplateResponse(
        request,
        "printers.html",
        {
            "printers": printers,
            "models": models,
            "q": q,
            "statut": statut,
            "modele": modele,
            "etat": etat,
        },
    )


# ─────────────────────────── Import ──────────────────────────────────


@app.get("/admin/import", response_class=HTMLResponse)
def import_form(
    request: Request,
    session: Session = Depends(get_session),
    _user: str = Depends(require_admin),
) -> HTMLResponse:
    runs = session.scalars(select(ImportRun).order_by(ImportRun.id.desc()).limit(20)).all()
    return templates.TemplateResponse(
        request,
        "import.html",
        {
            "runs": runs,
            "excluded": get_setting(session, "excluded_category_ids"),
        },
    )


@app.post("/admin/import", response_class=HTMLResponse)
def import_preview(
    request: Request,
    fichier: UploadFile = File(...),
    session: Session = Depends(get_session),
    _user: str = Depends(require_admin),
) -> HTMLResponse:
    original = Path(fichier.filename or "export.xlsx").name
    if not original.lower().endswith((".xlsx", ".xlsm")):
        return _import_error(request, session, "Format attendu : .xlsx")

    token = uuid.uuid4().hex
    target = settings.upload_dir / f"{token}__{original}"
    with target.open("wb") as out:
        shutil.copyfileobj(fichier.file, out)

    try:
        rows = read_rows(target)
        plan = build_plan(session, rows, get_setting(session, "excluded_category_ids"))
    except ImportError_ as exc:
        target.unlink(missing_ok=True)
        return _import_error(request, session, str(exc))

    return templates.TemplateResponse(
        request,
        "import_preview.html",
        {"plan": plan, "token": token, "filename": original},
    )


@app.post("/admin/import/{token}/appliquer")
def import_apply(
    token: str,
    filename: str = Form(...),
    session: Session = Depends(get_session),
    _user: str = Depends(require_admin),
) -> RedirectResponse:
    if not token.isalnum():
        raise HTTPException(status_code=400, detail="Jeton invalide")

    matches = sorted(settings.upload_dir.glob(f"{token}__*"))
    if not matches:
        raise HTTPException(status_code=404, detail="Fichier expiré — veuillez le téléverser à nouveau.")
    path = matches[0]

    rows = read_rows(path)
    plan = build_plan(session, rows, get_setting(session, "excluded_category_ids"))
    run = apply_plan(session, plan, filename=filename, sha256=sha256_of(path))

    return RedirectResponse(f"/admin/import?ok={run.id}", status_code=303)


def _import_error(request: Request, session: Session, message: str) -> HTMLResponse:
    runs = session.scalars(select(ImportRun).order_by(ImportRun.id.desc()).limit(20)).all()
    return templates.TemplateResponse(
        request,
        "import.html",
        {"runs": runs, "erreur": message, "excluded": get_setting(session, "excluded_category_ids")},
        status_code=400,
    )
