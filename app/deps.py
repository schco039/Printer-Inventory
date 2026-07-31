"""Gemeinsame Abhängigkeiten für alle Router."""

from __future__ import annotations

from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.auth import admin_protection_enabled

BASE_DIR = Path(__file__).resolve().parent

templates = Jinja2Templates(directory=BASE_DIR / "templates")
templates.env.globals["admin_protected"] = admin_protection_enabled
