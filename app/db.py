"""Datenbank-Session und Einstellungs-Speicher."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.models import AppSetting, Base

_settings = get_settings()
_settings.ensure_dirs()

engine = create_engine(
    _settings.database_url,
    connect_args={"check_same_thread": False},
    future=True,
)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _record):  # noqa: ANN001
    """WAL für gleichzeitiges Lesen, Fremdschlüssel aktiv (SQLite: default aus!)."""
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def get_session() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


# ─────────────────────────── Einstellungen ───────────────────────────

DEFAULT_SETTINGS: dict[str, Any] = {
    # Kategorien, die nicht verwaltet werden (SPEC 2):
    #   10246 = Imprimante 3D, 132 = Imprimante à cartes myCard
    "excluded_category_ids": [10246, 132],
    # Schuljahresbeginn (Monat) für die Saisonauswertung
    "school_year_start_month": 9,
    # Kiosk: auto | always | never
    "kiosk_brand_level": "auto",
    # Reservefaktor: 1 Satz Material je N Geräte
    "reserve_factor": 10,
    # Sekunden, die eine Kiosk-Anmeldung ohne Bedienung gültig bleibt
    "kiosk_session_seconds": 120,
}


def get_setting(session: Session, key: str) -> Any:
    row = session.get(AppSetting, key)
    if row is None:
        return DEFAULT_SETTINGS.get(key)
    return json.loads(row.value_json)


def set_setting(session: Session, key: str, value: Any) -> None:
    row = session.get(AppSetting, key)
    if row is None:
        session.add(AppSetting(key=key, value_json=json.dumps(value)))
    else:
        row.value_json = json.dumps(value)


def seed_settings(session: Session) -> None:
    """Fehlende Einstellungen mit Standardwerten anlegen (idempotent)."""
    existing = set(session.scalars(select(AppSetting.key)).all())
    for key, value in DEFAULT_SETTINGS.items():
        if key not in existing:
            session.add(AppSetting(key=key, value_json=json.dumps(value)))
    session.commit()


def create_all() -> None:
    """Nur für Tests und lokale Entwicklung — produktiv macht das Alembic."""
    Base.metadata.create_all(engine)
