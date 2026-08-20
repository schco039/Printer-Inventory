"""Anmeldung über Sitzungen.

Zwei Arten von Sitzungen im selben signierten Cookie:

  web    — Verwaltung am PC, Anmeldung mit Benutzername + PIN, längere Laufzeit
  kiosk  — Touchscreen am Lager, Anmeldung über Namenskachel + PIN,
           läuft nach kurzer Untätigkeit ab, weil das Gerät öffentlich steht

Die Laufzeit wird bei jeder Anfrage nachgeführt (gleitendes Fenster).
"""

from __future__ import annotations

import time

from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_session, get_setting
from app.models import AppUser

WEB_LAUFZEIT = 8 * 3600      # Verwaltung: ein Arbeitstag
KIOSK_STANDARD = 120         # Kiosk: Standard, überschreibbar in den Einstellungen


class Umleitung(Exception):
    """Signalisiert dem Handler, dass zur Anmeldung umgeleitet werden soll."""

    def __init__(self, ziel: str) -> None:
        self.ziel = ziel


def anmelden(request: Request, user: AppUser, art: str) -> None:
    request.session["uid"] = user.id
    request.session["art"] = art
    request.session["seit"] = time.time()
    request.session["zuletzt"] = time.time()


def abmelden(request: Request) -> None:
    request.session.clear()


def _laufzeit(session: Session, art: str) -> int:
    if art == "kiosk":
        return int(get_setting(session, "kiosk_session_seconds") or KIOSK_STANDARD)
    return WEB_LAUFZEIT


def aktueller_benutzer(
    request: Request, session: Session, art: str | None = None
) -> AppUser | None:
    """Angemeldete Person oder None. Erneuert das gleitende Zeitfenster."""
    uid = request.session.get("uid")
    if not uid:
        return None
    gespeicherte_art = request.session.get("art", "web")
    if art is not None and gespeicherte_art != art:
        return None

    zuletzt = float(request.session.get("zuletzt", 0))
    if time.time() - zuletzt > _laufzeit(session, gespeicherte_art):
        request.session.clear()
        return None

    user = session.get(AppUser, uid)
    if user is None or not user.actif:
        request.session.clear()
        return None

    request.session["zuletzt"] = time.time()
    return user


def keine_admins(session: Session) -> bool:
    """Noch kein Administrator mit PIN — dann ist die Ersteinrichtung offen."""
    return not session.scalar(
        select(func.count())
        .select_from(AppUser)
        .where(AppUser.role == "admin", AppUser.pin_hash.is_not(None), AppUser.actif == 1)
    )


# ─────────────────────────── Abhängigkeiten ──────────────────────────


def require_admin(
    request: Request, session: Session = Depends(get_session)
) -> AppUser:
    """Für /admin. Leitet zur Anmeldung oder zur Ersteinrichtung um."""
    if keine_admins(session):
        raise Umleitung("/setup")

    user = aktueller_benutzer(request, session, art="web")
    if user is None:
        ziel = request.url.path
        raise Umleitung(f"/login?next={ziel}")
    request.state.utilisateur = user
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Réservé aux administrateurs.",
        )
    return user


def require_kiosk(
    request: Request, session: Session = Depends(get_session)
) -> AppUser:
    """Für /kiosk. Leitet zur Namensauswahl um."""
    user = aktueller_benutzer(request, session, art="kiosk")
    if user is None:
        raise Umleitung("/kiosk")
    request.state.utilisateur = user
    return user


def umleitung_handler(_request: Request, exc: Umleitung) -> RedirectResponse:
    return RedirectResponse(exc.ziel, status_code=303)
