"""Gemeinsame Abhängigkeiten für alle Router."""

from __future__ import annotations

from pathlib import Path

from fastapi.templating import Jinja2Templates
from starlette.requests import Request

BASE_DIR = Path(__file__).resolve().parent


def _angemeldete_person(request: Request) -> dict:
    """Stellt die angemeldete Person jeder Vorlage zur Verfügung.

    Gefüllt wird sie von require_admin bzw. require_kiosk; auf öffentlichen
    Seiten bleibt sie None.
    """
    return {"utilisateur": getattr(request.state, "utilisateur", None)}


templates = Jinja2Templates(
    directory=BASE_DIR / "templates",
    context_processors=[_angemeldete_person],
)
