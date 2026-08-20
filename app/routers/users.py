"""Benutzerverwaltung: Personen, Anmeldenamen und PIN-Codes."""

from __future__ import annotations

import re
from datetime import datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.db import get_session
from app.deps import templates
from app.models import AppUser, Movement
from app.security import (
    MAX_ECHECS,
    PIN_LAENGE_MIN,
    PinFehler,
    ist_gesperrt,
    pin_erzeugen,
    pin_hashen,
)

router = APIRouter(dependencies=[Depends(require_admin)])


def benutzername_vorschlagen(nom: str, session: Session) -> str:
    """'Paul Muller' -> 'pmuller', bei Kollision 'pmuller2'."""
    teile = [t for t in re.split(r"[^A-Za-zÀ-ÿ]+", nom) if t]
    if not teile:
        basis = "user"
    elif len(teile) == 1:
        basis = teile[0]
    else:
        basis = teile[0][0] + teile[-1]
    basis = re.sub(r"[^a-z0-9]", "", basis.lower()) or "user"

    kandidat, n = basis, 1
    while session.scalar(select(AppUser).where(func.lower(AppUser.username) == kandidat)):
        n += 1
        kandidat = f"{basis}{n}"
    return kandidat


@router.get("/admin/utilisateurs", response_class=HTMLResponse)
def users_list(
    request: Request,
    message: str = "",
    erreur: str = "",
    nouveau_code: str = "",
    nouveau_nom: str = "",
    session: Session = Depends(get_session),
) -> HTMLResponse:
    users = list(session.scalars(select(AppUser).order_by(AppUser.nom)).all())
    counts = dict(
        session.execute(
            select(Movement.user_id, func.count(Movement.id))
            .where(Movement.user_id.is_not(None))
            .group_by(Movement.user_id)
        ).all()
    )
    return templates.TemplateResponse(
        request,
        "users.html",
        {
            "users": users,
            "counts": counts,
            "message": message,
            "erreur": erreur,
            "nouveau_code": nouveau_code,
            "nouveau_nom": nouveau_nom,
            "gesperrt": {u.id: ist_gesperrt(u) for u in users},
            "pin_min": PIN_LAENGE_MIN,
            "max_echecs": MAX_ECHECS,
        },
    )


@router.post("/admin/utilisateurs")
def save_user(
    session: Session = Depends(get_session),
    user_id: int = Form(0),
    nom: str = Form(...),
    username: str = Form(""),
    role: str = Form("user"),
    actif: str = Form("1"),
) -> RedirectResponse:
    nom = nom.strip()
    if not nom:
        raise HTTPException(status_code=400, detail="Le nom est obligatoire")

    username = re.sub(r"[^a-z0-9._-]", "", username.strip().lower())

    if user_id:
        user = session.get(AppUser, user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    else:
        user = AppUser(nom=nom)
        session.add(user)

    if not username:
        username = benutzername_vorschlagen(nom, session)

    kollision = session.scalar(
        select(AppUser).where(
            func.lower(AppUser.username) == username, AppUser.id != (user.id or 0)
        )
    )
    if kollision is not None:
        return RedirectResponse(
            f"/admin/utilisateurs?erreur=L%27identifiant+{username}+est+déjà+pris",
            status_code=303,
        )

    user.nom = nom
    user.username = username
    user.role = role if role in ("user", "admin") else "user"
    user.actif = 1 if actif == "1" else 0
    session.commit()

    if not user_id:
        # Neue Person bekommt gleich einen PIN, sonst kann sie sich nicht anmelden
        return RedirectResponse(
            f"/admin/utilisateurs/{user.id}/code?auto=1", status_code=303
        )
    return RedirectResponse("/admin/utilisateurs?message=Enregistré", status_code=303)


@router.post("/admin/utilisateurs/{user_id}/code")
@router.get("/admin/utilisateurs/{user_id}/code")
def set_code(
    user_id: int,
    session: Session = Depends(get_session),
    pin: str = Form(""),
    auto: int = 0,
) -> RedirectResponse:
    """PIN setzen — entweder selbst gewählt oder zufällig erzeugt.

    Der Code wird genau einmal angezeigt und danach nur noch gehasht gehalten.
    """
    user = session.get(AppUser, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")

    pin = (pin or "").strip()
    erzeugt = False
    if not pin:
        pin = pin_erzeugen(PIN_LAENGE_MIN)
        erzeugt = True

    try:
        user.pin_hash = pin_hashen(pin)
    except PinFehler as exc:
        return RedirectResponse(
            f"/admin/utilisateurs?erreur={exc}", status_code=303
        )

    user.pin_change_at = datetime.now()
    user.echecs = 0
    user.bloque_jusqua = None
    session.commit()

    if erzeugt or auto:
        return RedirectResponse(
            f"/admin/utilisateurs?nouveau_code={pin}&nouveau_nom={user.nom}",
            status_code=303,
        )
    return RedirectResponse(
        "/admin/utilisateurs?message=Code+modifié", status_code=303
    )


@router.post("/admin/utilisateurs/{user_id}/debloquer")
def unlock(user_id: int, session: Session = Depends(get_session)) -> RedirectResponse:
    user = session.get(AppUser, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    user.echecs = 0
    user.bloque_jusqua = None
    session.commit()
    return RedirectResponse("/admin/utilisateurs?message=Compte+débloqué", status_code=303)
