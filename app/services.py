"""Fachlogik: Bestand, Bewegungen, Schuljahr, Vorschläge.

Bestand wird nie gespeichert, sondern immer aus dem Hauptbuch summiert
(siehe docs/SPEC.md Abschnitt 4).
"""

from __future__ import annotations

import math
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_setting
from app.models import Consumable, ModelConsumable, Movement, Printer, PrinterModel

# ─────────────────────────── Schuljahr ───────────────────────────────


def school_year_label(day: date, start_month: int = 9) -> str:
    """'2026/27' für alles ab September 2026 bis August 2027."""
    year = day.year if day.month >= start_month else day.year - 1
    return f"{year}/{str(year + 1)[2:]}"


def month_key(day: date) -> str:
    return f"{day.year:04d}-{day.month:02d}"


# ─────────────────────────── Bewegungen ──────────────────────────────


def record_movement(
    session: Session,
    *,
    consumable_id: int,
    delta: int,
    motif: str,
    user_id: int | None = None,
    badge_type: str | None = None,
    printer_id: int | None = None,
    delivery_id: int | None = None,
    note: str | None = None,
    at: datetime | None = None,
) -> Movement:
    """Eine Buchung anlegen. Bucht nichts bei delta == 0."""
    if delta == 0:
        raise ValueError("delta darf nicht 0 sein")

    moment = at or datetime.now()
    start_month = int(get_setting(session, "school_year_start_month") or 9)

    movement = Movement(
        consumable_id=consumable_id,
        delta=delta,
        motif=motif,
        user_id=user_id,
        badge_type=badge_type,
        printer_id=printer_id,
        delivery_id=delivery_id,
        note=note,
        created_at=moment,
        mois=month_key(moment),
        annee_scolaire=school_year_label(moment.date(), start_month),
    )
    session.add(movement)
    return movement


# ─────────────────────────── Bestand ─────────────────────────────────


def stock_map(session: Session) -> dict[int, int]:
    """{consumable_id: Bestand} für alle Materialien mit Bewegungen."""
    rows = session.execute(
        select(Movement.consumable_id, func.sum(Movement.delta)).group_by(Movement.consumable_id)
    ).all()
    return {cid: int(total or 0) for cid, total in rows}


def stock_for(session: Session, consumable_id: int) -> int:
    total = session.scalar(
        select(func.sum(Movement.delta)).where(Movement.consumable_id == consumable_id)
    )
    return int(total or 0)


# ─────────────────────────── Modelle / Material ──────────────────────


def printer_counts(session: Session) -> dict[int, int]:
    """{model_id: Anzahl aktiver Geräte}."""
    rows = session.execute(
        select(Printer.model_id, func.count(Printer.id))
        .where(Printer.etat == "actif")
        .group_by(Printer.model_id)
    ).all()
    return {mid: int(n) for mid, n in rows}


def consumables_for_model(session: Session, model_id: int) -> list[Consumable]:
    return list(
        session.scalars(
            select(Consumable)
            .join(ModelConsumable, ModelConsumable.consumable_id == Consumable.id)
            .where(ModelConsumable.model_id == model_id, Consumable.actif == 1)
            .order_by(Consumable.type, Consumable.couleur, Consumable.sku)
        ).all()
    )


def models_for_consumable(session: Session, consumable_id: int) -> list[PrinterModel]:
    return list(
        session.scalars(
            select(PrinterModel)
            .join(ModelConsumable, ModelConsumable.model_id == PrinterModel.id)
            .where(ModelConsumable.consumable_id == consumable_id)
            .order_by(PrinterModel.marque, PrinterModel.modele)
        ).all()
    )


def link_model_consumable(session: Session, model_id: int, consumable_id: int) -> None:
    exists = session.get(ModelConsumable, (model_id, consumable_id))
    if exists is None:
        session.add(ModelConsumable(model_id=model_id, consumable_id=consumable_id))


def refresh_mapping_flag(session: Session, model_id: int) -> None:
    """mapping_ok spiegelt, ob dem Modell mindestens ein Material zugeordnet ist."""
    model = session.get(PrinterModel, model_id)
    if model is None:
        return
    n = session.scalar(
        select(func.count())
        .select_from(ModelConsumable)
        .where(ModelConsumable.model_id == model_id)
    )
    model.mapping_ok = 1 if n else 0


def suggest_seuil(nb_printers: int, reserve_factor: int) -> int:
    """1 Reservesatz je N Geräte, mindestens 1 (SPEC 6.3)."""
    if nb_printers <= 0 or reserve_factor <= 0:
        return 1
    return max(1, math.ceil(nb_printers / reserve_factor))


# ─────────────────────────── Kiosk-Ansicht ───────────────────────────

COLOR_ORDER = {"BK": 0, "C": 1, "M": 2, "Y": 3}
COLOR_LABEL = {"BK": "Noir", "C": "Cyan", "M": "Magenta", "Y": "Jaune"}

MOIS_COURTS = ["JAN", "FÉV", "MAR", "AVR", "MAI", "JUN",
               "JUL", "AOÛ", "SEP", "OCT", "NOV", "DÉC"]


def kiosk_groups(session: Session, model_id: int) -> list[dict]:
    """Material eines Modells nach Farbe gruppiert.

    Mehrere Ergiebigkeiten derselben Farbe (TN-421/423/426) landen in einer
    Gruppe und werden am Kiosk unter einer Kachel angeboten.
    """
    stock = stock_map(session)
    groups: dict[str, dict] = {}

    for consumable in consumables_for_model(session, model_id):
        if consumable.type == "toner" and consumable.couleur:
            key = consumable.couleur
            label = COLOR_LABEL.get(consumable.couleur, consumable.couleur)
            order = COLOR_ORDER.get(consumable.couleur, 9)
        else:
            key = consumable.type
            label = {"tambour": "Tambour", "encre": "Encre", "papier": "Papier"}.get(
                consumable.type, consumable.type.capitalize()
            )
            order = 10
            if consumable.couleur:
                label = f"{label} {COLOR_LABEL.get(consumable.couleur, consumable.couleur)}"
                key = f"{consumable.type}-{consumable.couleur}"
                order = 10 + COLOR_ORDER.get(consumable.couleur, 9)

        group = groups.setdefault(
            key,
            {"key": key, "label": label, "couleur": consumable.couleur, "order": order, "items": [], "total": 0},
        )
        qte = stock.get(consumable.id, 0)
        group["items"].append({"consumable": consumable, "qte": qte})
        group["total"] += qte

    return sorted(groups.values(), key=lambda g: g["order"])


# ─────────────────────────── Saison (M7) ─────────────────────────────


def month_order(start_month: int) -> list[int]:
    """Monatsreihenfolge des Schuljahres: [9, 10, …, 12, 1, …, 8]."""
    return [((start_month - 1 + i) % 12) + 1 for i in range(12)]


def consumption_by_month(session: Session) -> dict[tuple[int, str, int], int]:
    """{(consumable_id, annee_scolaire, monat): Entnahmen}."""
    rows = session.execute(
        select(Movement.consumable_id, Movement.annee_scolaire, Movement.mois, func.sum(-Movement.delta))
        .where(Movement.motif == "retrait")
        .group_by(Movement.consumable_id, Movement.annee_scolaire, Movement.mois)
    ).all()
    out: dict[tuple[int, str, int], int] = {}
    for cid, annee, mois, total in rows:
        month = int(str(mois)[5:7])
        out[(cid, annee, month)] = out.get((cid, annee, month), 0) + int(total or 0)
    return out


def school_years(session: Session) -> list[str]:
    rows = session.scalars(
        select(Movement.annee_scolaire).where(Movement.motif == "retrait").distinct()
    ).all()
    return sorted(set(rows))


def seasonal_factors(session: Session, consumable_id: int, start_month: int) -> dict[int, float]:
    """Faktor je Monat: Verbrauch dieses Monats ÷ Durchschnitt aller Monate.

    Über alle vollständigen Schuljahre gemittelt. Werte > 1 markieren
    Spitzenmonate. Ohne Daten kommt ein leeres Ergebnis zurück — die
    Oberfläche zeigt dann bewusst keine Prognose.
    """
    data = consumption_by_month(session)
    par_mois: dict[int, list[int]] = {m: [] for m in range(1, 13)}
    annees = {annee for (cid, annee, _m) in data if cid == consumable_id}
    if not annees:
        return {}

    for annee in annees:
        for month in range(1, 13):
            par_mois[month].append(data.get((consumable_id, annee, month), 0))

    moyennes = {m: (sum(v) / len(v) if v else 0.0) for m, v in par_mois.items()}
    total = sum(moyennes.values())
    if total <= 0:
        return {}
    moyenne_globale = total / 12
    return {m: (moyennes[m] / moyenne_globale if moyenne_globale else 0.0) for m in range(1, 13)}


def order_proposals(session: Session) -> list[dict]:
    """Bestellvorschlag je Material (M6), mit saisonalem Aufschlag (M7)."""
    reserve = int(get_setting(session, "reserve_factor") or 10)
    start_month = int(get_setting(session, "school_year_start_month") or 9)
    prochain_mois = (date.today().month % 12) + 1

    stock = stock_map(session)
    counts = printer_counts(session)

    # Wie viele Geräte nutzen dieses Material?
    rows = session.execute(
        select(ModelConsumable.consumable_id, ModelConsumable.model_id)
    ).all()
    appareils: dict[int, int] = {}
    for cid, mid in rows:
        appareils[cid] = appareils.get(cid, 0) + counts.get(mid, 0)

    proposals = []
    for consumable in session.scalars(select(Consumable).where(Consumable.actif == 1)).all():
        nb = appareils.get(consumable.id, 0)
        base = max(consumable.seuil_alerte, suggest_seuil(nb, reserve) if nb else 0)

        facteurs = seasonal_factors(session, consumable.id, start_month)
        facteur = facteurs.get(prochain_mois, 1.0) if facteurs else 1.0
        cible = max(base, round(base * facteur)) if base else 0

        qte = stock.get(consumable.id, 0)
        manque = max(0, cible - qte)
        if manque <= 0:
            continue

        proposals.append(
            {
                "consumable": consumable,
                "stock": qte,
                "appareils": nb,
                "base": base,
                "cible": cible,
                "manque": manque,
                "facteur": facteur if facteurs else None,
                "saison": bool(facteurs),
            }
        )

    proposals.sort(key=lambda p: (p["consumable"].fournisseur or "zzz", -p["manque"]))
    return proposals
