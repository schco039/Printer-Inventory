"""Test-Setup.

DATA_DIR wird gesetzt, BEVOR app.* importiert wird — sonst legt die Anwendung
ihre SQLite-Datei im echten ./data an.
"""

from __future__ import annotations

import os
import tempfile

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="lgk-test-"))
os.environ.setdefault("APP_SECRET", "test-secret-nur-fuer-tests")
os.environ.setdefault("BACKUP_ENABLED", "false")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal, engine, seed_settings  # noqa: E402
from app.main import app  # noqa: E402
from app.models import AppUser, Base  # noqa: E402
from app.security import pin_hashen  # noqa: E402

ADMIN_PIN = "1234"
USER_PIN = "5678"


@pytest.fixture
def db():
    """Frische Datenbank je Test, mit einem Administrator und einer Person."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        seed_settings(session)
        session.add_all([
            AppUser(nom="Conny Schumacher", username="cschumacher", role="admin",
                    pin_hash=pin_hashen(ADMIN_PIN), actif=1),
            AppUser(nom="Paul Muller", username="pmuller", role="user",
                    pin_hash=pin_hashen(USER_PIN), actif=1),
        ])
        session.commit()
        yield session


@pytest.fixture
def anon(db):
    """Nicht angemeldeter Client."""
    with TestClient(app) as c:
        yield c


@pytest.fixture
def client(anon):
    """Am Web angemeldeter Administrator."""
    anon.post("/login", data={"username": "cschumacher", "pin": ADMIN_PIN},
              follow_redirects=False)
    return anon


@pytest.fixture
def kiosk(db):
    """Am Kiosk angemeldete Person (Paul Muller)."""
    with TestClient(app) as c:
        from sqlalchemy import select
        user = db.scalar(select(AppUser).where(AppUser.username == "pmuller"))
        c.post(f"/kiosk/code/{user.id}", data={"pin": USER_PIN}, follow_redirects=False)
        yield c
