"""Benutzer und Badges (M4).

myCard und Salto sind zwei getrennte Felder je Person. Beide funktionieren am
Kiosk gleichwertig; welcher Badge benutzt wurde, landet in
`movement.badge_type`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.db import get_session
from app.deps import templates
from app.models import AppUser, Movement
from app.badge_bus import einloesen
from app.security import badge_hash

router = APIRouter(dependencies=[Depends(require_admin)])

BADGE_FIELDS = {"mycard": "mycard_hash", "salto": "salto_hash"}


@router.get("/admin/utilisateurs", response_class=HTMLResponse)
def users_list(
    request: Request,
    erreur: str = "",
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
    nb_badges = session.scalar(
        select(func.count())
        .select_from(AppUser)
        .where(or_(AppUser.mycard_hash.is_not(None), AppUser.salto_hash.is_not(None)))
    ) or 0

    return templates.TemplateResponse(
        request,
        "users.html",
        {"users": users, "counts": counts, "nb_badges": nb_badges, "erreur": erreur},
    )


@router.get("/admin/badge-test", response_class=HTMLResponse)
def badge_test(request: Request) -> HTMLResponse:
    """Diagnoseseite für den RFID-Leser.

    Zeigt roh an, was das Gerät sendet — ohne etwas zu speichern. Damit lässt
    sich vor Ort klären, ob der Leser überhaupt als Tastatur schreibt, ob eine
    Eingabetaste folgt und ob die UID bei jeder Lesung gleich bleibt
    (Salto-Karten können eine zufällige UID liefern).
    """
    return templates.TemplateResponse(request, "badge_test.html", {})


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


@router.post("/admin/utilisateurs/{user_id}/badge")
def enroll_badge(
    user_id: int,
    session: Session = Depends(get_session),
    type: str = Form(...),
    uid: str = Form(""),
    ticket: str = Form(""),
) -> RedirectResponse:
    """Badge anlernen. Die UID verlässt diese Funktion nie im Klartext.

    Zwei Wege: 'ticket' kommt vom Lesedienst für PC/SC-Leser, 'uid' von einem
    Leser im Tastaturmodus, der direkt ins Feld tippt.
    """
    user = session.get(AppUser, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    field = BADGE_FIELDS.get(type)
    if field is None:
        raise HTTPException(status_code=400, detail="Type de badge inconnu")

    digest = einloesen(ticket.strip()) if ticket.strip() else badge_hash(uid)
    if not digest:
        return RedirectResponse(
            "/admin/utilisateurs?erreur=Aucun+badge+lu+—+réessayez", status_code=303
        )

    # Schon jemand anderem zugeordnet?
    owner = session.scalar(
        select(AppUser).where(
            or_(AppUser.mycard_hash == digest, AppUser.salto_hash == digest)
        )
    )
    if owner is not None and owner.id != user_id:
        return RedirectResponse(
            f"/admin/utilisateurs?erreur=Ce+badge+est+déjà+attribué+à+{owner.nom}",
            status_code=303,
        )

    setattr(user, field, digest)
    session.commit()
    return RedirectResponse("/admin/utilisateurs", status_code=303)


@router.post("/admin/utilisateurs/{user_id}/badge/supprimer")
def remove_badge(
    user_id: int,
    session: Session = Depends(get_session),
    type: str = Form(...),
) -> RedirectResponse:
    user = session.get(AppUser, user_id)
    field = BADGE_FIELDS.get(type)
    if user is None or field is None:
        raise HTTPException(status_code=404, detail="Introuvable")
    setattr(user, field, None)
    session.commit()
    return RedirectResponse("/admin/utilisateurs", status_code=303)
