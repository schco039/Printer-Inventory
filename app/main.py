"""LGK Printer — Verbrauchsmaterial-Lager.

M0/M1  Excel-Import, Druckerliste
M2     Verbrauchsmaterial, Kompatibilitäten, Inventur, Bewegungen
M3     Kiosk (Person aus Liste; Badges folgen in M4)

Siehe docs/SPEC.md.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.db import SessionLocal, seed_settings
from app.deps import BASE_DIR
from app.routers import consumables, imports, kiosk, printers, stock, users

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings.ensure_dirs()
    with SessionLocal() as session:
        seed_settings(session)
    yield


app = FastAPI(
    title="LGK — Gestion des consommables",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

app.include_router(printers.router)
app.include_router(imports.router)
app.include_router(consumables.router)
app.include_router(stock.router)
app.include_router(users.router)
app.include_router(kiosk.router)


@app.get("/healthz", include_in_schema=False)
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse("/admin", status_code=302)
