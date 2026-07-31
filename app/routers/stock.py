"""Inventur, Bewegungen und Korrekturbuchungen (M2)."""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.db import get_session
from app.deps import templates
from app.models import AppUser, Consumable, Movement, Printer
from app.services import COLOR_LABEL, record_movement, stock_map

router = APIRouter(dependencies=[Depends(require_admin)])

MOTIF_LABEL = {
    "retrait": "Retrait",
    "reception": "Réception",
    "retour": "Retour",
    "inventaire": "Inventaire",
    "rebut": "Rebut",
    "correction": "Correction",
}


# ─────────────────────────── Inventur ────────────────────────────────


@router.get("/admin/inventaire", response_class=HTMLResponse)
def inventory_form(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    consumables = list(
        session.scalars(
            select(Consumable).where(Consumable.actif == 1).order_by(Consumable.type, Consumable.sku)
        ).all()
    )
    return templates.TemplateResponse(
        request,
        "inventory.html",
        {
            "consumables": consumables,
            "stock": stock_map(session),
            # Beim ersten Mal ist es die Eröffnungsinventur (SPEC 10)
            "premier": not session.scalar(select(Movement.id).limit(1)),
            "aujourdhui": date.today().isoformat(),
            "color_label": COLOR_LABEL,
        },
    )


@router.post("/admin/inventaire")
def inventory_apply(
    session: Session = Depends(get_session),
    date_comptage: str = Form(...),
    consumable_id: list[int] = Form([]),
    compte: list[str] = Form([]),
    note: str = Form(""),
) -> RedirectResponse:
    try:
        jour = date.fromisoformat(date_comptage)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Date de comptage invalide") from exc

    moment = datetime.combine(jour, datetime.min.time().replace(hour=12))
    stock = stock_map(session)
    nb = 0

    for i, cid in enumerate(consumable_id):
        brut = (compte[i] if i < len(compte) else "").strip()
        if brut == "":
            continue  # nicht gezählt → nicht anfassen
        try:
            compte_valeur = int(brut)
        except ValueError:
            continue

        ecart = compte_valeur - stock.get(cid, 0)
        if ecart == 0:
            continue

        record_movement(
            session,
            consumable_id=cid,
            delta=ecart,
            motif="inventaire",
            note=note.strip() or f"Comptage du {jour.strftime('%d.%m.%Y')}",
            at=moment,
        )
        nb += 1

    session.commit()
    return RedirectResponse(f"/admin/mouvements?ok={nb}", status_code=303)


# ─────────────────────────── Bewegungen ──────────────────────────────


@router.get("/admin/mouvements", response_class=HTMLResponse)
def movements(
    request: Request,
    consumable: int = 0,
    motif: str = "",
    limit: int = 200,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    stmt = select(Movement).order_by(Movement.created_at.desc(), Movement.id.desc()).limit(limit)
    if consumable:
        stmt = stmt.where(Movement.consumable_id == consumable)
    if motif:
        stmt = stmt.where(Movement.motif == motif)

    movements_list = list(session.scalars(stmt).all())
    consumables = {
        c.id: c for c in session.scalars(select(Consumable)).all()
    }
    users = {u.id: u for u in session.scalars(select(AppUser)).all()}
    printers = {p.id: p for p in session.scalars(select(Printer)).all()}

    return templates.TemplateResponse(
        request,
        "movements.html",
        {
            "movements": movements_list,
            "consumables": consumables,
            "users": users,
            "printers": printers,
            "catalogue": sorted(consumables.values(), key=lambda c: c.sku),
            "motif_label": MOTIF_LABEL,
            "consumable_filtre": consumable,
            "motif_filtre": motif,
        },
    )


@router.post("/admin/mouvements/correction")
def correction(
    session: Session = Depends(get_session),
    consumable_id: int = Form(...),
    delta: int = Form(...),
    note: str = Form(""),
) -> RedirectResponse:
    if delta == 0:
        raise HTTPException(status_code=400, detail="La quantité ne peut pas être nulle")
    if session.get(Consumable, consumable_id) is None:
        raise HTTPException(status_code=404, detail="Consommable introuvable")

    record_movement(
        session,
        consumable_id=consumable_id,
        delta=delta,
        motif="correction",
        note=note.strip() or None,
    )
    session.commit()
    return RedirectResponse("/admin/mouvements", status_code=303)
