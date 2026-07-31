"""Test-Setup.

DATA_DIR wird gesetzt, BEVOR app.* importiert wird — sonst legt die Anwendung
ihre SQLite-Datei im echten ./data an.
"""

from __future__ import annotations

import os
import tempfile

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="lgk-test-"))
os.environ.setdefault("ADMIN_PASSWORD", "")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal, engine, seed_settings  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402


@pytest.fixture
def db():
    """Frische Datenbank je Test."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        seed_settings(session)
        yield session


@pytest.fixture
def client(db):
    with TestClient(app) as c:
        yield c
