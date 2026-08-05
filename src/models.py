"""Modeles SQLAlchemy : comptes utilisateurs, recus persistants, corrections
(apprentissage par correction humaine) et consentements RGPD.

Separe de src/session_store.py (sessions anonymes historiques, encore en
service) le temps de la migration vers de vrais comptes -- voir la TaskList
du chantier "users-db-corrections". Une fois l'authentification cablee dans
api.py, les recus migreront de session_store vers ces modeles.

Suppression en cascade : supprimer un User supprime ses receipts, corrections
et consents (droit a l'effacement RGPD). Declare a la fois cote ORM
(cascade="all, delete-orphan") et cote base (ondelete="CASCADE") -- SQLite
n'applique le ondelete que si les foreign keys sont activees par connexion
(voir src/db.py, PRAGMA foreign_keys=ON).
"""
from datetime import datetime, timezone

from sqlalchemy import ForeignKey, JSON, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow, nullable=False)

    receipts: Mapped[list["Receipt"]] = relationship(
        back_populates="user", cascade="all, delete-orphan")
    corrections: Mapped[list["Correction"]] = relationship(
        back_populates="user", cascade="all, delete-orphan")
    consents: Mapped[list["Consent"]] = relationship(
        back_populates="user", cascade="all, delete-orphan")


class Receipt(Base):
    """Recu valide, rattache a un compte (remplace a terme la persistance
    anonyme par cookie de src/session_store.py)."""
    __tablename__ = "receipts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    data: Mapped[dict] = mapped_column(JSON, nullable=False)  # {"receipt": {...}, "items": [...]}
    doc_type: Mapped[str | None] = mapped_column(String(20))
    invoice_number: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow, onupdate=_utcnow, nullable=False)

    user: Mapped["User"] = relationship(back_populates="receipts")
    # Pas de cascade delete-orphan ici : une correction est une donnee
    # d'entrainement qui doit survivre a la suppression du recu source (seul
    # receipt_id est detache, voir ondelete="SET NULL" sur Correction).
    corrections: Mapped[list["Correction"]] = relationship(back_populates="receipt")


class Correction(Base):
    """Paire (prediction brute, valeur corrigee par l'humain) : la donnee
    d'apprentissage pour ameliorer l'extraction sur les recus ivoiriens et
    francais. Minimisation deliberee : ne stocke JAMAIS l'image, seulement
    les champs structures (voir la miniature deja geree ailleurs pour
    l'affichage, distincte de cette table d'entrainement).

    Ne peut exister que rattachee a un utilisateur consentant (user_id non
    nullable) : pas de collecte de donnees d'entrainement anonyme."""
    __tablename__ = "corrections"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    receipt_id: Mapped[int | None] = mapped_column(
        ForeignKey("receipts.id", ondelete="SET NULL"))
    raw_json: Mapped[dict] = mapped_column(JSON, nullable=False)        # sortie brute du modele
    corrected_json: Mapped[dict] = mapped_column(JSON, nullable=False)  # valeurs validees par l'humain
    engine: Mapped[str | None] = mapped_column(String(30))  # donut / llm_fallback : cible l'entrainement
    country: Mapped[str | None] = mapped_column(String(2))  # ID / CI / FR... : pertinent pour ivoirien/francais
    created_at: Mapped[datetime] = mapped_column(default=_utcnow, nullable=False)

    user: Mapped["User"] = relationship(back_populates="corrections")
    receipt: Mapped["Receipt | None"] = relationship(back_populates="corrections")


class Consent(Base):
    """Historique de consentement RGPD (ex. 'training_data'). Un enregistrement
    par evenement (octroi/retrait), jamais ecrase, pour garder la preuve."""
    __tablename__ = "consents"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    consent_type: Mapped[str] = mapped_column(String(50), nullable=False)
    granted: Mapped[bool] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow, nullable=False)

    user: Mapped["User"] = relationship(back_populates="consents")
