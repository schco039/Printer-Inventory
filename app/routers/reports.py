"""Bestellvorschlag (M6), Saisonanalyse (M7) und CSV-Exporte."""

from __future__ import annotations

import csv
import io
from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.db import get_session, get_setting
from app.deps import templates
from app.models import AppUser, Consumable, Movement
from app.services import (
    COLOR_LABEL,
    MOIS_COURTS,
    consumption_by_month,
    month_order,
    order_proposals,
    school_years,
    seasonal_factors,
)

router = APIRouter(dependencies=[Depends(require_admin)])


# ─────────────────────────── Bestellvorschlag ────────────────────────


@router.get("/admin/propositions", response_class=HTMLResponse)
def proposals(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    items = order_proposals(session)
    par_fournisseur: dict[str, list] = {}
    for item in items:
        key = item["consumable"].fournisseur or "Fournisseur non précisé"
        par_fournisseur.setdefault(key, []).append(item)

    return templates.TemplateResponse(
        request,
        "proposals.html",
        {
            "groupes": par_fournisseur,
            "total": sum(i["manque"] for i in items),
            "reserve": int(get_setting(session, "reserve_factor") or 10),
            "color_label": COLOR_LABEL,
        },
    )


@router.get("/admin/propositions.csv")
def proposals_csv(session: Session = Depends(get_session)) -> StreamingResponse:
    items = order_proposals(session)
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(["Fournisseur", "Reference", "Designation", "Stock", "Cible", "A commander"])
    for item in items:
        c = item["consumable"]
        writer.writerow(
            [c.fournisseur or "", c.sku, c.designation, item["stock"], item["cible"], item["manque"]]
        )
    return _csv_response(buffer, f"propositions-{date.today().isoformat()}.csv")


@router.get("/admin/mouvements.csv")
def movements_csv(session: Session = Depends(get_session)) -> StreamingResponse:
    consumables = {c.id: c for c in session.scalars(select(Consumable)).all()}
    users = {u.id: u for u in session.scalars(select(AppUser)).all()}

    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(
        ["Date", "Annee scolaire", "Mois", "Reference", "Designation",
         "Quantite", "Motif", "Personne", "Badge", "Note"]
    )
    for m in session.scalars(select(Movement).order_by(Movement.created_at)).all():
        c = consumables.get(m.consumable_id)
        writer.writerow(
            [
                m.created_at.strftime("%d.%m.%Y %H:%M"),
                m.annee_scolaire,
                m.mois,
                c.sku if c else "",
                c.designation if c else "",
                m.delta,
                m.motif,
                users[m.user_id].nom if m.user_id in users else "",
                m.badge_type or "",
                m.note or "",
            ]
        )
    return _csv_response(buffer, f"mouvements-{date.today().isoformat()}.csv")


def _csv_response(buffer: io.StringIO, filename: str) -> StreamingResponse:
    buffer.seek(0)
    # BOM, damit Excel die Umlaute richtig anzeigt
    data = "﻿" + buffer.read()
    return StreamingResponse(
        iter([data]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ─────────────────────────── Saisonanalyse ───────────────────────────


@router.get("/admin/saisonnalite", response_class=HTMLResponse)
def seasonality(
    request: Request,
    annee: str = "",
    session: Session = Depends(get_session),
) -> HTMLResponse:
    start_month = int(get_setting(session, "school_year_start_month") or 9)
    annees = school_years(session)
    courante = annee if annee in annees else (annees[-1] if annees else "")

    data = consumption_by_month(session)
    ordre = month_order(start_month)
    consumables = list(
        session.scalars(select(Consumable).order_by(Consumable.type, Consumable.sku)).all()
    )

    lignes = []
    for c in consumables:
        valeurs = [data.get((c.id, courante, m), 0) for m in ordre]
        if not any(valeurs):
            continue
        maximum = max(valeurs)
        lignes.append(
            {
                "consumable": c,
                "valeurs": valeurs,
                "total": sum(valeurs),
                "max": maximum,
                # Intensität je Zeile normiert: sonst verschwinden die Trommeln
                "niveaux": [(0 if maximum == 0 else round(v / maximum * 4)) for v in valeurs],
                "pics": _peak_months(valeurs, ordre),
            }
        )

    # Jahresvergleich über alle Materialien
    totaux_annuels = {}
    for a in annees:
        totaux_annuels[a] = [
            sum(data.get((c.id, a, m), 0) for c in consumables) for m in ordre
        ]

    return templates.TemplateResponse(
        request,
        "seasonality.html",
        {
            "lignes": lignes,
            "annees": annees,
            "courante": courante,
            "mois_labels": [MOIS_COURTS[m - 1] for m in ordre],
            "ordre": ordre,
            "totaux_annuels": totaux_annuels,
            "nb_annees": len(annees),
            "color_label": COLOR_LABEL,
            "facteurs": {
                l["consumable"].id: seasonal_factors(session, l["consumable"].id, start_month)
                for l in lignes
            },
        },
    )


def _peak_months(valeurs: list[int], ordre: list[int]) -> list[str]:
    """Die drei stärksten Monate im Klartext."""
    paires = sorted(zip(valeurs, ordre), reverse=True)
    return [f"{MOIS_COURTS[m - 1]} ({v})" for v, m in paires[:3] if v > 0]
