"""Übergangs-Authentifizierung für /admin (HTTP Basic).

Wird in M4 durch die echte Benutzerverwaltung mit Badges ersetzt.
Ist ADMIN_PASSWORD leer, bleibt der Zugang offen und die Oberfläche zeigt
eine Warnung — damit eine unfertige Installation nicht unbemerkt offen steht.
"""

from __future__ import annotations

import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.config import get_settings

_basic = HTTPBasic(auto_error=False)


def require_admin(credentials: HTTPBasicCredentials | None = Depends(_basic)) -> str:
    settings = get_settings()
    if not settings.admin_password:
        return "anonyme"

    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentification requise",
        headers={"WWW-Authenticate": "Basic"},
    )
    if credentials is None:
        raise unauthorized

    user_ok = secrets.compare_digest(credentials.username, settings.admin_user)
    pass_ok = secrets.compare_digest(credentials.password, settings.admin_password)
    if not (user_ok and pass_ok):
        raise unauthorized
    return credentials.username


def admin_protection_enabled() -> bool:
    return bool(get_settings().admin_password)
