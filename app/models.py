"""Datenmodell — siehe docs/SPEC.md Abschnitt 4.

Die Tabellen für Verbrauchsmaterial, Bewegungen, Benutzer und Lieferungen sind
bereits hier definiert, obwohl erst M2–M5 sie benutzen. Grund: eine Migration
weniger, und das Schema ist ohnehin durchdacht.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# ─────────────────────────── Einstellungen ───────────────────────────


class AppSetting(Base):
    """Key/Value-Einstellungen, Wert als JSON-Text."""

    __tablename__ = "app_setting"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value_json: Mapped[str] = mapped_column(Text, nullable=False)


# ─────────────────────────── Drucker ─────────────────────────────────


class PrinterModel(Base):
    __tablename__ = "printer_model"
    __table_args__ = (UniqueConstraint("marque", "modele", name="uq_model_marque_modele"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    marque: Mapped[str] = mapped_column(String(120), nullable=False)
    modele: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    categorie: Mapped[str | None] = mapped_column(String(120))
    categorie_id: Mapped[int | None] = mapped_column(Integer)
    # Korrektur, falls die Marke im Quellsystem falsch erfasst ist (z. B. SC-T5100)
    marque_override: Mapped[str | None] = mapped_column(String(120))
    # 0 = noch kein Verbrauchsmaterial zugeordnet
    mapping_ok: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    printers: Mapped[list["Printer"]] = relationship(back_populates="model")

    @property
    def marque_affichee(self) -> str:
        return self.marque_override or self.marque

    @property
    def libelle(self) -> str:
        return f"{self.marque_affichee} {self.modele}"


class Printer(Base):
    __tablename__ = "printer"

    id: Mapped[int] = mapped_column(primary_key=True)
    # 'ID article' aus der Excel — einziger stabiler Schlüssel (CGIE ist lückenhaft)
    source_item_id: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    nom: Mapped[str] = mapped_column(String(255), nullable=False)
    serial: Mapped[str | None] = mapped_column(String(120))
    cgie: Mapped[str | None] = mapped_column(String(120))

    model_id: Mapped[int] = mapped_column(ForeignKey("printer_model.id"), nullable=False)
    model: Mapped[PrinterModel] = relationship(back_populates="printers")

    code_entite: Mapped[str | None] = mapped_column(String(60))
    annexe: Mapped[str | None] = mapped_column(String(120))
    salle: Mapped[str | None] = mapped_column(String(120))
    salle_type: Mapped[str | None] = mapped_column(String(60))

    statut: Mapped[str] = mapped_column(String(20), nullable=False)  # installe | entrepot
    etat: Mapped[str] = mapped_column(String(20), nullable=False, default="actif")  # actif | absent

    ip: Mapped[str | None] = mapped_column(String(60))
    mac: Mapped[str | None] = mapped_column(String(60))
    date_mise_service: Mapped[date | None] = mapped_column(Date)
    fournisseur: Mapped[str | None] = mapped_column(String(255))

    first_seen_import: Mapped[int | None] = mapped_column(ForeignKey("import_run.id"))
    last_seen_import: Mapped[int | None] = mapped_column(ForeignKey("import_run.id"))


Index("ix_printer_model", Printer.model_id)
Index("ix_printer_etat", Printer.etat)


# ─────────────────────────── Verbrauchsmaterial ──────────────────────


class Consumable(Base):
    __tablename__ = "consumable"

    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    designation: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)  # toner|tambour|encre|papier
    couleur: Mapped[str | None] = mapped_column(String(10))  # BK|C|M|Y|NULL
    marque: Mapped[str | None] = mapped_column(String(120))
    ean: Mapped[str | None] = mapped_column(String(40))
    emplacement: Mapped[str | None] = mapped_column(String(60))
    seuil_alerte: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    actif: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class ModelConsumable(Base):
    """Kompatibilitätsmatrix Modell ↔ Material."""

    __tablename__ = "model_consumable"

    model_id: Mapped[int] = mapped_column(ForeignKey("printer_model.id"), primary_key=True)
    consumable_id: Mapped[int] = mapped_column(ForeignKey("consumable.id"), primary_key=True)


# ─────────────────────────── Benutzer ────────────────────────────────


class AppUser(Base):
    __tablename__ = "app_user"

    id: Mapped[int] = mapped_column(primary_key=True)
    nom: Mapped[str] = mapped_column(String(160), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    # HMAC-SHA256 der Badge-UID — die rohe UID wird nie gespeichert
    mycard_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    salto_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    pin_hash: Mapped[str | None] = mapped_column(String(255))
    actif: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


# ─────────────────────────── Bestand ─────────────────────────────────


class Delivery(Base):
    __tablename__ = "delivery"

    id: Mapped[int] = mapped_column(primary_key=True)
    fournisseur: Mapped[str | None] = mapped_column(String(255))
    bon_livraison: Mapped[str | None] = mapped_column(String(120))
    date_livr: Mapped[date] = mapped_column(Date, nullable=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)


class DeliveryLine(Base):
    __tablename__ = "delivery_line"
    __table_args__ = (CheckConstraint("quantite > 0", name="ck_delivery_line_qte"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    delivery_id: Mapped[int] = mapped_column(ForeignKey("delivery.id"), nullable=False)
    consumable_id: Mapped[int] = mapped_column(ForeignKey("consumable.id"), nullable=False)
    quantite: Mapped[int] = mapped_column(Integer, nullable=False)


class Movement(Base):
    """Hauptbuch. Bestand = SUM(delta). Wird nie gelöscht, nur gegengebucht."""

    __tablename__ = "movement"

    id: Mapped[int] = mapped_column(primary_key=True)
    consumable_id: Mapped[int] = mapped_column(ForeignKey("consumable.id"), nullable=False)
    delta: Mapped[int] = mapped_column(Integer, nullable=False)
    # retrait | reception | retour | inventaire | rebut
    motif: Mapped[str] = mapped_column(String(20), nullable=False)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
    badge_type: Mapped[str | None] = mapped_column(String(10))  # mycard|salto|pin
    printer_id: Mapped[int | None] = mapped_column(ForeignKey("printer.id"))
    delivery_id: Mapped[int | None] = mapped_column(ForeignKey("delivery.id"))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    # denormalisiert für die Saisonauswertung (SPEC 6.4)
    mois: Mapped[str] = mapped_column(String(7), nullable=False)  # '2026-09'
    annee_scolaire: Mapped[str] = mapped_column(String(9), nullable=False)  # '2026/27'


Index("ix_mov_consumable", Movement.consumable_id)
Index("ix_mov_created", Movement.created_at)
Index("ix_mov_saison", Movement.annee_scolaire, Movement.mois)


# ─────────────────────────── Import-Historie ─────────────────────────


class ImportRun(Base):
    __tablename__ = "import_run"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    imported_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
    rows_total: Mapped[int] = mapped_column(Integer, default=0)
    rows_kept: Mapped[int] = mapped_column(Integer, default=0)
    rows_state_filtered: Mapped[int] = mapped_column(Integer, default=0)
    rows_category_filtered: Mapped[int] = mapped_column(Integer, default=0)
    nb_created: Mapped[int] = mapped_column(Integer, default=0)
    nb_updated: Mapped[int] = mapped_column(Integer, default=0)
    nb_absent: Mapped[int] = mapped_column(Integer, default=0)
    nb_new_models: Mapped[int] = mapped_column(Integer, default=0)
    raw_json: Mapped[str | None] = mapped_column(Text)
