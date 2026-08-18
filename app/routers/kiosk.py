"""Touch-Kiosk (M3) — Marke ▸ Modell ▸ Farbe ▸ Entnahme.

Bis M4 wird die Person aus einer Liste gewählt statt per Badge gescannt.
Die Buchung selbst ist bereits die endgültige: Badge-Anmeldung wird später
nur das Auswählen der Person ersetzen.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from sqlalchemy import or_

from app.db import get_session, get_setting
from app.deps import templates
from app.models import AppUser, Consumable, Printer, PrinterModel
from app.badge_bus import einloesen
from app.security import badge_hash
from app.services import kiosk_groups, record_movement, stock_for

router = APIRouter()


def _active_models(session: Session) -> list[tuple[PrinterModel, int]]:
    """Modelle mit aktiven Geräten, häufigste zuerst."""
    rows = session.execute(
        select(PrinterModel, func.count(Printer.id).label("nb"))
        .join(Printer, Printer.model_id == PrinterModel.id)
        .where(Printer.etat == "actif")
        .group_by(PrinterModel.id)
        .order_by(func.count(Printer.id).desc(), PrinterModel.modele)
    ).all()
    return [(model, int(nb)) for model, nb in rows]


def _brand_level(session: Session, models: list[tuple[PrinterModel, int]]) -> bool:
    """Markenebene anzeigen? auto = erst ab der zweiten Marke (SPEC 6.1)."""
    mode = get_setting(session, "kiosk_brand_level") or "auto"
    if mode == "always":
        return True
    if mode == "never":
        return False
    return len({model.marque_affichee for model, _ in models}) > 1


def _ctx(session: Session, **extra) -> dict:
    ctx = {"idle_reset": int(get_setting(session, "kiosk_idle_reset_seconds") or 45)}
    ctx.update(extra)
    return ctx


@router.get("/kiosk", response_class=HTMLResponse)
def home(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    models = _active_models(session)

    if _brand_level(session, models):
        marques: dict[str, int] = {}
        for model, nb in models:
            marques[model.marque_affichee] = marques.get(model.marque_affichee, 0) + nb
        return templates.TemplateResponse(
            request,
            "kiosk_brands.html",
            _ctx(session, marques=sorted(marques.items())),
        )

    return templates.TemplateResponse(
        request,
        "kiosk_models.html",
        _ctx(session, models=models, marque=None, mapping=_mapping_state(session, models)),
    )


@router.get("/kiosk/marque/{marque}", response_class=HTMLResponse)
def by_brand(marque: str, request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    models = [(m, nb) for m, nb in _active_models(session) if m.marque_affichee == marque]
    if not models:
        raise HTTPException(status_code=404, detail="Marque inconnue")
    return templates.TemplateResponse(
        request,
        "kiosk_models.html",
        _ctx(session, models=models, marque=marque, mapping=_mapping_state(session, models)),
    )


@router.get("/kiosk/modele/{slug}", response_class=HTMLResponse)
def by_model(slug: str, request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    model = session.scalar(select(PrinterModel).where(PrinterModel.slug == slug))
    if model is None:
        raise HTTPException(status_code=404, detail="Modèle inconnu")

    groups = kiosk_groups(session, model.id)
    nb = session.scalar(
        select(func.count())
        .select_from(Printer)
        .where(Printer.model_id == model.id, Printer.etat == "actif")
    ) or 0

    return templates.TemplateResponse(
        request,
        "kiosk_colors.html",
        _ctx(session, model=model, groups=groups, nb=nb),
    )


def _badge_mode(session: Session) -> bool:
    """Badge-Modus, sobald mindestens eine Karte angelernt ist (M4).

    Vorher — und wenn kein Badge angelernt ist — bleibt die Namensliste
    stehen, damit das System auch am ersten Tag benutzbar ist.
    """
    return bool(
        session.scalar(
            select(AppUser.id)
            .where(
                AppUser.actif == 1,
                or_(AppUser.mycard_hash.is_not(None), AppUser.salto_hash.is_not(None)),
            )
            .limit(1)
        )
    )


def _confirm_page(
    request: Request,
    session: Session,
    consumable: Consumable,
    sens: str,
    erreur: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    users = list(
        session.scalars(select(AppUser).where(AppUser.actif == 1).order_by(AppUser.nom)).all()
    )
    return templates.TemplateResponse(
        request,
        "kiosk_confirm.html",
        _ctx(
            session,
            consumable=consumable,
            qte=stock_for(session, consumable.id),
            users=users,
            badge_mode=_badge_mode(session),
            sens=sens if sens in ("sortie", "retour") else "sortie",
            erreur=erreur,
        ),
        status_code=status_code,
    )


@router.get("/kiosk/retrait/{consumable_id}", response_class=HTMLResponse)
def confirm_form(
    consumable_id: int,
    request: Request,
    sens: str = "sortie",
    session: Session = Depends(get_session),
) -> HTMLResponse:
    consumable = session.get(Consumable, consumable_id)
    if consumable is None:
        raise HTTPException(status_code=404, detail="Consommable inconnu")
    return _confirm_page(request, session, consumable, sens)


@router.post("/kiosk/retrait")
def book(
    request: Request,
    session: Session = Depends(get_session),
    consumable_id: int = Form(...),
    quantite: int = Form(1),
    user_id: int = Form(0),
    badge: str = Form(""),
    ticket: str = Form(""),
    sens: str = Form("sortie"),
) -> Response:
    consumable = session.get(Consumable, consumable_id)
    if consumable is None:
        raise HTTPException(status_code=404, detail="Consommable inconnu")

    quantite = max(1, min(quantite, 99))
    stock = stock_for(session, consumable_id)

    # Person bestimmen: Badge hat Vorrang, sonst Auswahl aus der Liste
    user: AppUser | None = None
    badge_type: str | None = None
    # Ticket: PC/SC-Leser über den Lesedienst. badge: Leser im Tastaturmodus.
    digest = einloesen(ticket.strip()) if ticket.strip() else None
    if digest or badge.strip():
        digest = digest or badge_hash(badge)
        user = session.scalar(
            select(AppUser).where(
                AppUser.actif == 1,
                or_(AppUser.mycard_hash == digest, AppUser.salto_hash == digest),
            )
        )
        if user is None:
            return _confirm_page(
                request, session, consumable, sens,
                erreur="Badge inconnu. Faites-le enregistrer par l'administrateur.",
                status_code=403,
            )
        badge_type = "mycard" if user.mycard_hash == digest else "salto"
    elif user_id:
        user = session.get(AppUser, user_id)
    elif _badge_mode(session):
        return _confirm_page(
            request, session, consumable, sens,
            erreur="Présentez votre badge pour confirmer.",
            status_code=400,
        )

    if sens == "retour":
        delta, motif = quantite, "retour"
    else:
        delta, motif = -quantite, "retrait"
        if stock - quantite < 0:
            # Negativbestand blockieren (SPEC 12, offener Punkt 6)
            return _confirm_page(
                request, session, consumable, sens,
                erreur=f"Stock insuffisant : il ne reste que {stock}.",
                status_code=400,
            )

    record_movement(
        session,
        consumable_id=consumable_id,
        delta=delta,
        motif=motif,
        user_id=user.id if user else None,
        badge_type=badge_type,
    )
    session.commit()
    return templates.TemplateResponse(
        request,
        "kiosk_done.html",
        _ctx(
            session,
            consumable=consumable,
            delta=delta,
            reste=stock + delta,
            user=user,
        ),
    )


def _mapping_state(session: Session, models: list[tuple[PrinterModel, int]]) -> dict[int, bool]:
    """{model_id: hat Material} — Modelle ohne Material werden ausgegraut."""
    return {model.id: bool(model.mapping_ok) for model, _ in models}
