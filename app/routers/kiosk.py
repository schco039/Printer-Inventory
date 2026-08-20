"""Touch-Kiosk.

Ablauf: Namenskachel antippen, PIN eingeben, dann Modell, Farbe, Menge und
buchen. Die Anmeldung gilt für eine kurze Zeit, damit mehrere Entnahmen
hintereinander ohne erneute PIN-Eingabe möglich sind; danach fällt der Kiosk
von selbst auf die Namensauswahl zurück.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import abmelden, aktueller_benutzer, anmelden, require_kiosk
from app.db import get_session, get_setting
from app.deps import templates
from app.models import AppUser, Consumable, Printer, PrinterModel
from app.security import pruefe_anmeldung
from app.services import kiosk_groups, record_movement, stock_for

router = APIRouter()


def _ctx(session: Session, user: AppUser | None = None, **extra) -> dict:
    """Gemeinsamer Vorlagen-Kontext. Die angemeldete Person liefert der
    Kontextprozessor in app/deps.py, hier nur der Rest."""
    ctx = {"idle_reset": int(get_setting(session, "kiosk_session_seconds") or 120)}
    ctx.update(extra)
    return ctx


# ─────────────────────────── Anmeldung ───────────────────────────────


@router.get("/kiosk", response_class=HTMLResponse)
def accueil(request: Request, session: Session = Depends(get_session)) -> Response:
    """Namenskacheln. Wer angemeldet ist, kommt direkt zum Katalog."""
    if aktueller_benutzer(request, session, art="kiosk") is not None:
        return RedirectResponse("/kiosk/catalogue", status_code=303)

    users = list(
        session.scalars(
            select(AppUser)
            .where(AppUser.actif == 1, AppUser.pin_hash.is_not(None))
            .order_by(AppUser.nom)
        ).all()
    )
    return templates.TemplateResponse(
        request, "kiosk_users.html", _ctx(session, users=users)
    )


@router.get("/kiosk/code/{user_id}", response_class=HTMLResponse)
def code_form(
    user_id: int, request: Request, session: Session = Depends(get_session)
) -> Response:
    user = session.get(AppUser, user_id)
    if user is None or not user.actif or not user.pin_hash:
        return RedirectResponse("/kiosk", status_code=303)
    return templates.TemplateResponse(
        request, "kiosk_code.html", _ctx(session, cible=user, erreur=None)
    )


@router.post("/kiosk/code/{user_id}", response_class=HTMLResponse)
def code_pruefen(
    user_id: int,
    request: Request,
    pin: str = Form(""),
    session: Session = Depends(get_session),
) -> Response:
    user = session.get(AppUser, user_id)
    if user is None:
        return RedirectResponse("/kiosk", status_code=303)

    ok, meldung = pruefe_anmeldung(user, pin.strip())
    session.commit()
    if not ok:
        return templates.TemplateResponse(
            request,
            "kiosk_code.html",
            _ctx(session, cible=user, erreur=meldung),
            status_code=401,
        )

    anmelden(request, user, "kiosk")
    return RedirectResponse("/kiosk/catalogue", status_code=303)


@router.get("/kiosk/fin")
def fin(request: Request) -> RedirectResponse:
    abmelden(request)
    return RedirectResponse("/kiosk", status_code=303)


# ─────────────────────────── Katalog ─────────────────────────────────


def _active_models(session: Session) -> list[tuple[PrinterModel, int]]:
    rows = session.execute(
        select(PrinterModel, func.count(Printer.id))
        .join(Printer, Printer.model_id == PrinterModel.id)
        .where(Printer.etat == "actif")
        .group_by(PrinterModel.id)
        .order_by(func.count(Printer.id).desc(), PrinterModel.modele)
    ).all()
    return [(model, int(nb)) for model, nb in rows]


def _brand_level(session: Session, models: list[tuple[PrinterModel, int]]) -> bool:
    mode = get_setting(session, "kiosk_brand_level") or "auto"
    if mode == "always":
        return True
    if mode == "never":
        return False
    return len({model.marque_affichee for model, _ in models}) > 1


@router.get("/kiosk/catalogue", response_class=HTMLResponse)
def catalogue(
    request: Request,
    session: Session = Depends(get_session),
    user: AppUser = Depends(require_kiosk),
) -> HTMLResponse:
    models = _active_models(session)
    if _brand_level(session, models):
        marques: dict[str, int] = {}
        for model, nb in models:
            marques[model.marque_affichee] = marques.get(model.marque_affichee, 0) + nb
        return templates.TemplateResponse(
            request,
            "kiosk_brands.html",
            _ctx(session, user, marques=sorted(marques.items())),
        )
    return templates.TemplateResponse(
        request,
        "kiosk_models.html",
        _ctx(
            session,
            user,
            models=models,
            marque=None,
            mapping={m.id: bool(m.mapping_ok) for m, _ in models},
        ),
    )


@router.get("/kiosk/marque/{marque}", response_class=HTMLResponse)
def par_marque(
    marque: str,
    request: Request,
    session: Session = Depends(get_session),
    user: AppUser = Depends(require_kiosk),
) -> HTMLResponse:
    models = [
        (m, nb) for m, nb in _active_models(session) if m.marque_affichee == marque
    ]
    if not models:
        raise HTTPException(status_code=404, detail="Marque inconnue")
    return templates.TemplateResponse(
        request,
        "kiosk_models.html",
        _ctx(
            session,
            user,
            models=models,
            marque=marque,
            mapping={m.id: bool(m.mapping_ok) for m, _ in models},
        ),
    )


@router.get("/kiosk/modele/{slug}", response_class=HTMLResponse)
def par_modele(
    slug: str,
    request: Request,
    session: Session = Depends(get_session),
    user: AppUser = Depends(require_kiosk),
) -> HTMLResponse:
    model = session.scalar(select(PrinterModel).where(PrinterModel.slug == slug))
    if model is None:
        raise HTTPException(status_code=404, detail="Modèle inconnu")
    nb = (
        session.scalar(
            select(func.count())
            .select_from(Printer)
            .where(Printer.model_id == model.id, Printer.etat == "actif")
        )
        or 0
    )
    return templates.TemplateResponse(
        request,
        "kiosk_colors.html",
        _ctx(session, user, model=model, groups=kiosk_groups(session, model.id), nb=nb),
    )


# ─────────────────────────── Buchung ─────────────────────────────────


def _confirm_page(
    request: Request,
    session: Session,
    user: AppUser,
    consumable: Consumable,
    sens: str,
    erreur: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "kiosk_confirm.html",
        _ctx(
            session,
            user,
            consumable=consumable,
            qte=stock_for(session, consumable.id),
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
    user: AppUser = Depends(require_kiosk),
) -> HTMLResponse:
    consumable = session.get(Consumable, consumable_id)
    if consumable is None:
        raise HTTPException(status_code=404, detail="Consommable inconnu")
    return _confirm_page(request, session, user, consumable, sens)


@router.post("/kiosk/retrait")
def book(
    request: Request,
    session: Session = Depends(get_session),
    user: AppUser = Depends(require_kiosk),
    consumable_id: int = Form(...),
    quantite: int = Form(1),
    sens: str = Form("sortie"),
) -> Response:
    consumable = session.get(Consumable, consumable_id)
    if consumable is None:
        raise HTTPException(status_code=404, detail="Consommable inconnu")

    quantite = max(1, min(quantite, 99))
    stock = stock_for(session, consumable_id)

    if sens == "retour":
        delta, motif = quantite, "retour"
    else:
        delta, motif = -quantite, "retrait"
        if stock - quantite < 0:
            return _confirm_page(
                request,
                session,
                user,
                consumable,
                sens,
                erreur=f"Stock insuffisant : il ne reste que {stock}.",
                status_code=400,
            )

    record_movement(
        session,
        consumable_id=consumable_id,
        delta=delta,
        motif=motif,
        user_id=user.id,
    )
    session.commit()

    return templates.TemplateResponse(
        request,
        "kiosk_done.html",
        _ctx(session, user, consumable=consumable, delta=delta, reste=stock + delta),
    )
