"""Benutzerverwaltung — Minimalfassung.

Namen und Rollen. Die Badge-Felder (myCard/Salto) sind im Datenmodell bereits
vorhanden, werden aber erst in M4 befüllt.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.db import get_session
from app.deps import templates
from app.models import AppUser, Movement

router = APIRouter(dependencies=[Depends(require_admin)])


@router.get("/admin/utilisateurs", response_class=HTMLResponse)
def users_list(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    users = list(session.scalars(select(AppUser).order_by(AppUser.nom)).all())
    counts = dict(
        session.execute(
            select(Movement.user_id, func.count(Movement.id))
            .where(Movement.user_id.is_not(None))
            .group_by(Movement.user_id)
        ).all()
    )
    return templates.TemplateResponse(
        request, "users.html", {"users": users, "counts": counts}
    )


@router.post("/admin/utilisateurs")
def save_user(
    session: Session = Depends(get_session),
    user_id: int = Form(0),
    nom: str = Form(...),
    role: str = Form("user"),
    actif: str = Form("1"),
) -> RedirectResponse:
    nom = nom.strip()
    if not nom:
        raise HTTPException(status_code=400, detail="Le nom est obligatoire")

    if user_id:
        user = session.get(AppUser, user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    else:
        user = AppUser(nom=nom)
        session.add(user)

    user.nom = nom
    user.role = role if role in ("user", "admin") else "user"
    user.actif = 1 if actif == "1" else 0
    session.commit()
    return RedirectResponse("/admin/utilisateurs", status_code=303)
