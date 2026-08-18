"""Schnittstelle für den Kartenleser-Dienst (PC/SC).

Der Lesedienst meldet die UID, die Seite im Browser fragt nach. Bewusst schlank
gehalten: ein POST und ein GET, kein WebSocket — das läuft auch auf dem alten
Chromium des Raspberry Pi.
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.badge_bus import STATION_STANDARD, abholen, melden
from app.config import get_settings
from app.db import get_session
from app.models import AppUser
from app.security import badge_hash

router = APIRouter()


@router.post("/api/badge/scan")
def scan(
    request: Request,
    token: str = Form(""),
    uid: str = Form(...),
    station: str = Form(STATION_STANDARD),
) -> dict:
    """Vom Lesedienst aufgerufen. Die UID wird sofort gehasht und verworfen."""
    settings = get_settings()
    erwartet = settings.badge_agent_token
    if not erwartet:
        raise HTTPException(
            status_code=503,
            detail="BADGE_AGENT_TOKEN ist auf dem Server nicht gesetzt.",
        )
    kopf = request.headers.get("X-Badge-Token", "")
    if not (
        secrets.compare_digest(token or "", erwartet)
        or secrets.compare_digest(kopf, erwartet)
    ):
        raise HTTPException(status_code=403, detail="Token ungültig")

    digest = badge_hash(uid)
    if not digest:
        raise HTTPException(status_code=400, detail="Leere UID")

    melden(station or STATION_STANDARD, digest)
    return {"ok": True}


@router.get("/api/badge/pending")
def pending(
    station: str = STATION_STANDARD,
    session: Session = Depends(get_session),
) -> dict:
    """Von der Seite im Browser abgefragt.

    Antwortet mit einem Einmal-Ticket. Der Badge-Hash selbst bleibt auf dem
    Server. Ist die Karte bereits einer Person zugeordnet, kommt deren Name
    mit, damit der Kiosk sofort anzeigen kann, wer erkannt wurde.
    """
    ticket = abholen(station or STATION_STANDARD)
    if ticket is None:
        return {"ready": False}

    from app.badge_bus import _tickets  # nur lesen, Ticket bleibt gültig

    digest = _tickets.get(ticket, ("", 0.0))[0]
    user = session.scalar(
        select(AppUser).where(
            AppUser.actif == 1,
            or_(AppUser.mycard_hash == digest, AppUser.salto_hash == digest),
        )
    )
    return {
        "ready": True,
        "ticket": ticket,
        "nom": user.nom if user else None,
        "connu": user is not None,
    }
