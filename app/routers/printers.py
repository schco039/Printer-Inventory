"""Dashboard und Druckerliste."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.db import get_session
from app.deps import templates
from app.models import Consumable, ImportRun, Printer, PrinterModel
from app.services import printer_counts, stock_map

router = APIRouter(dependencies=[Depends(require_admin)])


@router.get("/admin", response_class=HTMLResponse)
def dashboard(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    nb_printers = session.scalar(
        select(func.count()).select_from(Printer).where(Printer.etat == "actif")
    ) or 0
    nb_entrepot = session.scalar(
        select(func.count())
        .select_from(Printer)
        .where(Printer.etat == "actif", Printer.statut == "entrepot")
    ) or 0
    nb_absent = session.scalar(
        select(func.count()).select_from(Printer).where(Printer.etat == "absent")
    ) or 0

    consumables = list(session.scalars(select(Consumable).where(Consumable.actif == 1)).all())
    stock = stock_map(session)

    ruptures = [c for c in consumables if stock.get(c.id, 0) <= 0]
    sous_seuil = [
        c for c in consumables if 0 < stock.get(c.id, 0) < c.seuil_alerte
    ]

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
            "nb_consumables": len(consumables),
            "ruptures": ruptures,
            "sous_seuil": sous_seuil,
            "stock": stock,
            "a_mapper": a_mapper,
            "marques": sorted(marques),
            "last_import": last_import,
        },
    )


@router.get("/admin/imprimantes", response_class=HTMLResponse)
def printers_list(
    request: Request,
    q: str = "",
    statut: str = "",
    modele: str = "",
    etat: str = "actif",
    session: Session = Depends(get_session),
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
    models = session.scalars(
        select(PrinterModel).order_by(PrinterModel.marque, PrinterModel.modele)
    ).all()

    return templates.TemplateResponse(
        request,
        "printers.html",
        {
            "printers": printers,
            "models": models,
            "counts": printer_counts(session),
            "q": q,
            "statut": statut,
            "modele": modele,
            "etat": etat,
        },
    )


# ─────────────────────────── Modelle korrigieren ─────────────────────


@router.get("/admin/modeles", response_class=HTMLResponse)
def models_list(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    models = list(
        session.scalars(select(PrinterModel).order_by(PrinterModel.marque, PrinterModel.modele)).all()
    )
    return templates.TemplateResponse(
        request,
        "models.html",
        {"models": models, "counts": printer_counts(session)},
    )


@router.get("/admin/modeles/{model_id}", response_class=HTMLResponse)
def model_form(
    model_id: int, request: Request, session: Session = Depends(get_session)
) -> HTMLResponse:
    model = session.get(PrinterModel, model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="Modèle introuvable")

    printers = list(
        session.scalars(
            select(Printer).where(Printer.model_id == model_id).order_by(Printer.nom)
        ).all()
    )
    return templates.TemplateResponse(
        request,
        "model_form.html",
        {"model": model, "printers": printers},
    )


@router.post("/admin/modeles/{model_id}")
def model_save(
    model_id: int,
    session: Session = Depends(get_session),
    marque_override: str = Form(""),
    modele_override: str = Form(""),
    categorie: str = Form(""),
) -> RedirectResponse:
    """Anzeigekorrektur speichern.

    Marke und Modell aus der Excel bleiben unangetastet — sie bilden die
    Identität für den Re-Import. Korrigiert wird nur, was angezeigt wird.
    """
    model = session.get(PrinterModel, model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="Modèle introuvable")

    marque = marque_override.strip()
    modele = modele_override.strip()
    model.marque_override = marque if marque and marque != model.marque else None
    model.modele_override = modele if modele and modele != model.modele else None
    if categorie.strip():
        model.categorie = categorie.strip()
    session.commit()
    return RedirectResponse(f"/admin/modeles/{model_id}?ok=1", status_code=303)
