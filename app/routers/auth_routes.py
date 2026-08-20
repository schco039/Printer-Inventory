"""Anmeldung im Web und Ersteinrichtung."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import abmelden, aktueller_benutzer, anmelden, keine_admins
from app.db import get_session
from app.deps import templates
from app.models import AppUser
from app.security import PinFehler, pin_hashen, pruefe_anmeldung

router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
def login_form(
    request: Request,
    next: str = "/admin",
    session: Session = Depends(get_session),
) -> Response:
    if keine_admins(session):
        return RedirectResponse("/setup", status_code=303)
    if aktueller_benutzer(request, session, art="web") is not None:
        return RedirectResponse(next or "/admin", status_code=303)
    return templates.TemplateResponse(
        request, "login.html", {"next": next, "erreur": None}
    )


@router.post("/login", response_class=HTMLResponse)
def login(
    request: Request,
    username: str = Form(...),
    pin: str = Form(...),
    next: str = Form("/admin"),
    session: Session = Depends(get_session),
) -> Response:
    user = session.scalar(
        select(AppUser).where(func.lower(AppUser.username) == username.strip().lower())
    )
    ok, meldung = pruefe_anmeldung(user, pin.strip())
    session.commit()

    if not ok:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"next": next, "erreur": meldung, "username": username},
            status_code=401,
        )

    anmelden(request, user, "web")
    ziel = next if next.startswith("/") else "/admin"
    return RedirectResponse(ziel, status_code=303)


@router.get("/logout")
def logout(request: Request) -> RedirectResponse:
    abmelden(request)
    return RedirectResponse("/login", status_code=303)


# ─────────────────────────── Ersteinrichtung ─────────────────────────


@router.get("/setup", response_class=HTMLResponse)
def setup_form(request: Request, session: Session = Depends(get_session)) -> Response:
    if not keine_admins(session):
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(request, "setup.html", {"erreur": None})


@router.post("/setup", response_class=HTMLResponse)
def setup(
    request: Request,
    nom: str = Form(...),
    username: str = Form(...),
    pin: str = Form(...),
    pin2: str = Form(...),
    session: Session = Depends(get_session),
) -> Response:
    """Erster Administrator. Nur möglich, solange es keinen gibt."""
    if not keine_admins(session):
        return RedirectResponse("/login", status_code=303)

    def fehler(meldung: str) -> Response:
        return templates.TemplateResponse(
            request,
            "setup.html",
            {"erreur": meldung, "nom": nom, "username": username},
            status_code=400,
        )

    nom = nom.strip()
    username = username.strip().lower()
    if not nom or not username:
        return fehler("Nom et identifiant sont obligatoires.")
    if pin != pin2:
        return fehler("Les deux codes ne correspondent pas.")
    try:
        pin_hash = pin_hashen(pin)
    except PinFehler as exc:
        return fehler(str(exc))

    vorhanden = session.scalar(
        select(AppUser).where(func.lower(AppUser.username) == username)
    )
    user = vorhanden or AppUser(nom=nom)
    user.nom = nom
    user.username = username
    user.role = "admin"
    user.actif = 1
    user.pin_hash = pin_hash
    user.pin_change_at = datetime.now()
    user.echecs = 0
    user.bloque_jusqua = None
    if vorhanden is None:
        session.add(user)
    session.commit()

    anmelden(request, user, "web")
    return RedirectResponse("/admin", status_code=303)
