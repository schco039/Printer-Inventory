"""Verbrauchsmaterial: Katalog und Kompatibilitätsmatrix (M2)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.db import get_session, get_setting
from app.deps import templates
from app.models import Consumable, ModelConsumable, Movement, PrinterModel
from app.services import (
    COLOR_LABEL,
    consumables_for_model,
    link_model_consumable,
    models_for_consumable,
    printer_counts,
    refresh_mapping_flag,
    stock_map,
    suggest_seuil,
)

router = APIRouter(dependencies=[Depends(require_admin)])

TYPE_LABEL = {
    "toner": "Toner",
    "tambour": "Tambour",
    "encre": "Encre",
    "papier": "Papier",
}

# Vorlagen für den Assistenten: (type, couleur)
JEUX = {
    "cmyk": [("toner", "BK"), ("toner", "C"), ("toner", "M"), ("toner", "Y"), ("tambour", None)],
    "mono": [("toner", "BK"), ("tambour", None)],
    "encre": [("encre", "BK"), ("encre", "C"), ("encre", "M"), ("encre", "Y")],
    "libre": [("toner", None), ("toner", None), ("toner", None)],
}


# ─────────────────────────── Katalog ─────────────────────────────────


@router.get("/admin/consommables", response_class=HTMLResponse)
def catalogue(
    request: Request,
    q: str = "",
    type: str = "",
    session: Session = Depends(get_session),
) -> HTMLResponse:
    stmt = select(Consumable).order_by(Consumable.type, Consumable.sku)
    if type:
        stmt = stmt.where(Consumable.type == type)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(Consumable.sku.ilike(like) | Consumable.designation.ilike(like))

    consumables = list(session.scalars(stmt).all())
    stock = stock_map(session)

    links = dict(
        session.execute(
            select(ModelConsumable.consumable_id, func.count(ModelConsumable.model_id)).group_by(
                ModelConsumable.consumable_id
            )
        ).all()
    )

    return templates.TemplateResponse(
        request,
        "consumables.html",
        {
            "consumables": consumables,
            "stock": stock,
            "links": links,
            "q": q,
            "type_filtre": type,
            "type_label": TYPE_LABEL,
            "color_label": COLOR_LABEL,
        },
    )


@router.get("/admin/consommables/nouveau", response_class=HTMLResponse)
def new_form(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "consumable_form.html",
        {
            "consumable": None,
            "models": _all_models(session),
            "linked_ids": set(),
            "type_label": TYPE_LABEL,
            "color_label": COLOR_LABEL,
        },
    )


@router.get("/admin/consommables/{consumable_id}", response_class=HTMLResponse)
def edit_form(
    consumable_id: int, request: Request, session: Session = Depends(get_session)
) -> HTMLResponse:
    consumable = session.get(Consumable, consumable_id)
    if consumable is None:
        raise HTTPException(status_code=404, detail="Consommable introuvable")

    linked = {m.id for m in models_for_consumable(session, consumable_id)}
    nb_mouvements = session.scalar(
        select(func.count()).select_from(Movement).where(Movement.consumable_id == consumable_id)
    )

    return templates.TemplateResponse(
        request,
        "consumable_form.html",
        {
            "consumable": consumable,
            "models": _all_models(session),
            "linked_ids": linked,
            "stock": stock_map(session).get(consumable_id, 0),
            "nb_mouvements": nb_mouvements,
            "type_label": TYPE_LABEL,
            "color_label": COLOR_LABEL,
        },
    )


@router.post("/admin/consommables")
def save_consumable(
    session: Session = Depends(get_session),
    consumable_id: int = Form(0),
    sku: str = Form(...),
    designation: str = Form(""),
    type: str = Form("toner"),
    couleur: str = Form(""),
    marque: str = Form(""),
    ean: str = Form(""),
    emplacement: str = Form(""),
    seuil_alerte: int = Form(0),
    actif: str = Form("1"),
    modeles: list[int] = Form([]),
) -> RedirectResponse:
    sku = sku.strip()
    if not sku:
        raise HTTPException(status_code=400, detail="La référence est obligatoire")

    if consumable_id:
        consumable = session.get(Consumable, consumable_id)
        if consumable is None:
            raise HTTPException(status_code=404, detail="Consommable introuvable")
    else:
        clash = session.scalar(select(Consumable).where(func.lower(Consumable.sku) == sku.lower()))
        if clash is not None:
            return RedirectResponse(f"/admin/consommables/{clash.id}?doublon=1", status_code=303)
        consumable = Consumable(sku=sku)
        session.add(consumable)

    consumable.sku = sku
    consumable.designation = designation.strip() or _default_designation(type, marque, sku, couleur)
    consumable.type = type
    consumable.couleur = couleur.strip() or None
    consumable.marque = marque.strip() or None
    consumable.ean = ean.strip() or None
    consumable.emplacement = emplacement.strip() or None
    consumable.seuil_alerte = max(0, seuil_alerte)
    consumable.actif = 1 if actif == "1" else 0
    session.flush()

    # Verknüpfungen abgleichen
    wanted = set(modeles)
    current = {m.id for m in models_for_consumable(session, consumable.id)}
    for model_id in wanted - current:
        link_model_consumable(session, model_id, consumable.id)
    for model_id in current - wanted:
        link = session.get(ModelConsumable, (model_id, consumable.id))
        if link is not None:
            session.delete(link)
    session.flush()
    for model_id in wanted | current:
        refresh_mapping_flag(session, model_id)

    session.commit()
    return RedirectResponse("/admin/consommables", status_code=303)


# ─────────────────────────── Kompatibilitäten ────────────────────────


@router.get("/admin/compatibilites", response_class=HTMLResponse)
def matrix(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    models = _all_models(session)
    counts = printer_counts(session)
    rows = [
        {
            "model": model,
            "nb": counts.get(model.id, 0),
            "consumables": consumables_for_model(session, model.id),
        }
        for model in models
    ]
    # Modelle ohne Material und mit vielen Geräten zuerst
    rows.sort(key=lambda r: (bool(r["consumables"]), -r["nb"]))

    return templates.TemplateResponse(
        request,
        "compatibilities.html",
        {"rows": rows, "color_label": COLOR_LABEL, "type_label": TYPE_LABEL},
    )


@router.get("/admin/compatibilites/{model_id}", response_class=HTMLResponse)
def configure(
    model_id: int,
    request: Request,
    jeu: str = "",
    session: Session = Depends(get_session),
) -> HTMLResponse:
    model = session.get(PrinterModel, model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="Modèle introuvable")

    nb = printer_counts(session).get(model_id, 0)
    reserve = int(get_setting(session, "reserve_factor") or 10)
    seuil = suggest_seuil(nb, reserve)

    lignes = []
    if jeu in JEUX:
        for type_, couleur in JEUX[jeu]:
            lignes.append(
                {
                    "type": type_,
                    "couleur": couleur or "",
                    "label": COLOR_LABEL.get(couleur, TYPE_LABEL.get(type_, type_)) if couleur else TYPE_LABEL.get(type_, type_),
                    "seuil": seuil if type_ != "tambour" else max(1, seuil // 2),
                }
            )

    autres = [
        m
        for m in _all_models(session)
        if m.id != model_id and consumables_for_model(session, m.id)
    ]

    return templates.TemplateResponse(
        request,
        "compatibility_form.html",
        {
            "model": model,
            "nb": nb,
            "seuil": seuil,
            "reserve": reserve,
            "jeu": jeu,
            "lignes": lignes,
            "existants": consumables_for_model(session, model_id),
            "autres_modeles": autres,
            "catalogue": list(session.scalars(
                select(Consumable).where(Consumable.actif == 1).order_by(Consumable.sku)
            ).all()),
            "stock": stock_map(session),
            "color_label": COLOR_LABEL,
            "type_label": TYPE_LABEL,
        },
    )


@router.post("/admin/compatibilites/{model_id}/assistant")
def run_assistant(
    model_id: int,
    session: Session = Depends(get_session),
    sku: list[str] = Form([]),
    designation: list[str] = Form([]),
    type: list[str] = Form([]),
    couleur: list[str] = Form([]),
    seuil: list[int] = Form([]),
) -> RedirectResponse:
    model = session.get(PrinterModel, model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="Modèle introuvable")

    for i, ref in enumerate(sku):
        ref = ref.strip()
        if not ref:
            continue  # leere Zeilen überspringen

        ligne_type = type[i] if i < len(type) else "toner"
        ligne_couleur = (couleur[i] if i < len(couleur) else "").strip() or None
        ligne_seuil = seuil[i] if i < len(seuil) else 0
        ligne_designation = (designation[i] if i < len(designation) else "").strip()

        existing = session.scalar(select(Consumable).where(func.lower(Consumable.sku) == ref.lower()))
        if existing is None:
            existing = Consumable(
                sku=ref,
                designation=ligne_designation
                or _default_designation(ligne_type, model.marque_affichee, ref, ligne_couleur),
                type=ligne_type,
                couleur=ligne_couleur,
                marque=model.marque_affichee,
                seuil_alerte=max(0, ligne_seuil),
            )
            session.add(existing)
            session.flush()

        link_model_consumable(session, model_id, existing.id)

    session.flush()
    refresh_mapping_flag(session, model_id)
    session.commit()
    return RedirectResponse(f"/admin/compatibilites/{model_id}?ok=1", status_code=303)


@router.post("/admin/compatibilites/{model_id}/copier")
def copy_from_model(
    model_id: int,
    source_id: int = Form(...),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    if session.get(PrinterModel, model_id) is None:
        raise HTTPException(status_code=404, detail="Modèle introuvable")

    for consumable in consumables_for_model(session, source_id):
        link_model_consumable(session, model_id, consumable.id)

    session.flush()
    refresh_mapping_flag(session, model_id)
    session.commit()
    return RedirectResponse(f"/admin/compatibilites/{model_id}?ok=1", status_code=303)


@router.post("/admin/compatibilites/{model_id}/lier")
def link_existing(
    model_id: int,
    consumable_id: int = Form(...),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    link_model_consumable(session, model_id, consumable_id)
    session.flush()
    refresh_mapping_flag(session, model_id)
    session.commit()
    return RedirectResponse(f"/admin/compatibilites/{model_id}?ok=1", status_code=303)


@router.post("/admin/compatibilites/{model_id}/delier")
def unlink(
    model_id: int,
    consumable_id: int = Form(...),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    link = session.get(ModelConsumable, (model_id, consumable_id))
    if link is not None:
        session.delete(link)
    session.flush()
    refresh_mapping_flag(session, model_id)
    session.commit()
    return RedirectResponse(f"/admin/compatibilites/{model_id}", status_code=303)


# ─────────────────────────── Hilfsfunktionen ─────────────────────────


def _all_models(session: Session) -> list[PrinterModel]:
    return list(
        session.scalars(select(PrinterModel).order_by(PrinterModel.marque, PrinterModel.modele)).all()
    )


def _default_designation(type_: str, marque: str | None, sku: str, couleur: str | None) -> str:
    parts = [TYPE_LABEL.get(type_, type_.capitalize())]
    if marque:
        parts.append(marque)
    parts.append(sku)
    if couleur:
        parts.append(COLOR_LABEL.get(couleur, couleur))
    return " ".join(parts)
