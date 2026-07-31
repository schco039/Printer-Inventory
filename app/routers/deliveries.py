"""Wareneingang (M5).

Eine Lieferung ist eine Klammer um mehrere Zubuchungen. Storniert wird nie
durch Löschen, sondern durch Gegenbuchungen — die Historie bleibt lesbar.
"""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.db import get_session
from app.deps import templates
from app.models import Consumable, Delivery, DeliveryLine, Movement, Printer
from app.services import record_movement, stock_map

router = APIRouter(dependencies=[Depends(require_admin)])

LIGNES_PAR_DEFAUT = 8


@router.get("/admin/reception", response_class=HTMLResponse)
def reception_form(
    request: Request,
    lignes: int = LIGNES_PAR_DEFAUT,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    catalogue = list(
        session.scalars(
            select(Consumable).where(Consumable.actif == 1).order_by(Consumable.sku)
        ).all()
    )

    # Lieferantenvorschläge aus Druckerbestand und bisherigen Lieferungen
    fournisseurs = set(
        session.scalars(select(Printer.fournisseur).where(Printer.fournisseur.is_not(None))).all()
    ) | set(
        session.scalars(select(Delivery.fournisseur).where(Delivery.fournisseur.is_not(None))).all()
    )

    livraisons = list(
        session.scalars(select(Delivery).order_by(Delivery.id.desc()).limit(15)).all()
    )
    totaux = dict(
        session.execute(
            select(DeliveryLine.delivery_id, func.sum(DeliveryLine.quantite)).group_by(
                DeliveryLine.delivery_id
            )
        ).all()
    )

    return templates.TemplateResponse(
        request,
        "reception.html",
        {
            "catalogue": catalogue,
            "fournisseurs": sorted(f for f in fournisseurs if f),
            "nb_lignes": max(1, min(lignes, 40)),
            "aujourdhui": date.today().isoformat(),
            "livraisons": livraisons,
            "totaux": totaux,
            "stock": stock_map(session),
        },
    )


@router.post("/admin/reception")
def reception_save(
    session: Session = Depends(get_session),
    fournisseur: str = Form(""),
    bon_livraison: str = Form(""),
    date_livr: str = Form(...),
    note: str = Form(""),
    consumable_id: list[int] = Form([]),
    quantite: list[str] = Form([]),
) -> RedirectResponse:
    try:
        jour = date.fromisoformat(date_livr)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Date de livraison invalide") from exc

    lignes: list[tuple[int, int]] = []
    for i, cid in enumerate(consumable_id):
        brut = (quantite[i] if i < len(quantite) else "").strip()
        if not brut or not cid:
            continue
        try:
            qte = int(brut)
        except ValueError:
            continue
        if qte > 0:
            lignes.append((cid, qte))

    if not lignes:
        return RedirectResponse("/admin/reception?vide=1", status_code=303)

    delivery = Delivery(
        fournisseur=fournisseur.strip() or None,
        bon_livraison=bon_livraison.strip() or None,
        date_livr=jour,
        created_at=datetime.now(),
        note=note.strip() or None,
    )
    session.add(delivery)
    session.flush()

    moment = datetime.combine(jour, datetime.min.time().replace(hour=12))
    for cid, qte in lignes:
        session.add(DeliveryLine(delivery_id=delivery.id, consumable_id=cid, quantite=qte))
        record_movement(
            session,
            consumable_id=cid,
            delta=qte,
            motif="reception",
            delivery_id=delivery.id,
            at=moment,
            note=f"BL {delivery.bon_livraison}" if delivery.bon_livraison else None,
        )
        # Lieferant am Material merken — der Bestellvorschlag gruppiert danach
        consumable = session.get(Consumable, cid)
        if consumable is not None and delivery.fournisseur and not consumable.fournisseur:
            consumable.fournisseur = delivery.fournisseur

    session.commit()
    return RedirectResponse(f"/admin/reception/{delivery.id}", status_code=303)


@router.get("/admin/reception/{delivery_id}", response_class=HTMLResponse)
def reception_detail(
    delivery_id: int, request: Request, session: Session = Depends(get_session)
) -> HTMLResponse:
    delivery = session.get(Delivery, delivery_id)
    if delivery is None:
        raise HTTPException(status_code=404, detail="Livraison introuvable")

    lignes = list(
        session.scalars(
            select(DeliveryLine).where(DeliveryLine.delivery_id == delivery_id)
        ).all()
    )
    consumables = {c.id: c for c in session.scalars(select(Consumable)).all()}
    mouvements = list(
        session.scalars(select(Movement).where(Movement.delivery_id == delivery_id)).all()
    )
    annulee = sum(m.delta for m in mouvements) == 0 and len(mouvements) > len(lignes)

    return templates.TemplateResponse(
        request,
        "reception_detail.html",
        {
            "delivery": delivery,
            "lignes": lignes,
            "consumables": consumables,
            "annulee": annulee,
        },
    )


@router.post("/admin/reception/{delivery_id}/annuler")
def reception_cancel(
    delivery_id: int, session: Session = Depends(get_session)
) -> RedirectResponse:
    """Storno per Gegenbuchung — die ursprüngliche Buchung bleibt sichtbar."""
    delivery = session.get(Delivery, delivery_id)
    if delivery is None:
        raise HTTPException(status_code=404, detail="Livraison introuvable")

    mouvements = list(
        session.scalars(select(Movement).where(Movement.delivery_id == delivery_id)).all()
    )
    if sum(m.delta for m in mouvements) == 0:
        return RedirectResponse(f"/admin/reception/{delivery_id}", status_code=303)

    for m in mouvements:
        if m.delta > 0:
            record_movement(
                session,
                consumable_id=m.consumable_id,
                delta=-m.delta,
                motif="correction",
                delivery_id=delivery_id,
                note=f"Annulation livraison n° {delivery_id}",
            )
    session.commit()
    return RedirectResponse(f"/admin/reception/{delivery_id}", status_code=303)
