"""Excel-Import mit Diff-Vorschau."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.config import get_settings
from app.db import get_session, get_setting
from app.deps import templates
from app.importer import ImportError_, apply_plan, build_plan, read_rows, sha256_of
from app.models import ImportRun

router = APIRouter(dependencies=[Depends(require_admin)])


@router.get("/admin/import", response_class=HTMLResponse)
def import_form(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    return _render_form(request, session)


@router.post("/admin/import", response_class=HTMLResponse)
def import_preview(
    request: Request,
    fichier: UploadFile = File(...),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    settings = get_settings()
    original = Path(fichier.filename or "export.xlsx").name
    if not original.lower().endswith((".xlsx", ".xlsm")):
        return _render_form(request, session, erreur="Format attendu : .xlsx", status_code=400)

    token = uuid.uuid4().hex
    target = settings.upload_dir / f"{token}__{original}"
    with target.open("wb") as out:
        shutil.copyfileobj(fichier.file, out)

    try:
        rows = read_rows(target)
        plan = build_plan(session, rows, get_setting(session, "excluded_category_ids"))
    except ImportError_ as exc:
        target.unlink(missing_ok=True)
        return _render_form(request, session, erreur=str(exc), status_code=400)

    return templates.TemplateResponse(
        request,
        "import_preview.html",
        {"plan": plan, "token": token, "filename": original},
    )


@router.post("/admin/import/{token}/appliquer")
def import_apply(
    token: str,
    filename: str = Form(...),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    settings = get_settings()
    if not token.isalnum():
        raise HTTPException(status_code=400, detail="Jeton invalide")

    matches = sorted(settings.upload_dir.glob(f"{token}__*"))
    if not matches:
        raise HTTPException(
            status_code=404, detail="Fichier expiré — veuillez le téléverser à nouveau."
        )
    path = matches[0]

    rows = read_rows(path)
    plan = build_plan(session, rows, get_setting(session, "excluded_category_ids"))
    run = apply_plan(session, plan, filename=filename, sha256=sha256_of(path))

    return RedirectResponse(f"/admin/import?ok={run.id}", status_code=303)


def _render_form(
    request: Request,
    session: Session,
    erreur: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    runs = session.scalars(select(ImportRun).order_by(ImportRun.id.desc()).limit(20)).all()
    return templates.TemplateResponse(
        request,
        "import.html",
        {
            "runs": runs,
            "erreur": erreur,
            "excluded": get_setting(session, "excluded_category_ids"),
        },
        status_code=status_code,
    )
