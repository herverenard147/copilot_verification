"""Modeles SQLAlchemy : comptes utilisateurs, corrections (apprentissage par
correction humaine) et consentements RGPD.

Pas de modele Receipt ici : les recus valides vivent dans
src/session_store.py, qui etait deja concu pour etre rattache a un compte
(get_session(session_id, user_id=None), voir son commentaire "AUTH FUTURE").
En mode APP_MODE=prod, api.py cle la session sur l'identifiant du compte au
lieu du cookie anonyme -- ca reutilise tout le calcul (dashboard, TVA,
anomalies) deja teste, sans dupliquer la logique dans un second systeme de
persistance.

Suppression en cascade : supprimer un User supprime ses corrections et
consents (droit a l'effacement RGPD). Declare a la fois cote ORM
(cascade="all, delete-orphan") et cote base (ondelete="CASCADE") -- SQLite
n'applique le ondelete que si les foreign keys sont activees par connexion
(voir src/db.py, PRAGMA foreign_keys=ON). Les reçus de session_store sont
purges separement (session_store.drop_session), voir api.py.
"""
from datetime import datetime, timezone

from sqlalchemy import ForeignKey, Integer, JSON, String
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

    corrections: Mapped[list["Correction"]] = relationship(
        back_populates="user", cascade="all, delete-orphan")
    consents: Mapped[list["Consent"]] = relationship(
        back_populates="user", cascade="all, delete-orphan")


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
    # PAS une foreign key : les recus valides vivent dans src/session_store.py
    # (numerotation par session/compte, pas dans une table SQL de ce module).
    # Identifiant informatif pour retrouver le contexte, pas une contrainte
    # d'integrite referentielle.
    receipt_id: Mapped[int | None] = mapped_column(Integer)
    raw_json: Mapped[dict] = mapped_column(JSON, nullable=False)        # sortie brute du modele
    corrected_json: Mapped[dict] = mapped_column(JSON, nullable=False)  # valeurs validees par l'humain
    engine: Mapped[str | None] = mapped_column(String(30))  # donut / llm_fallback : cible l'entrainement
    country: Mapped[str | None] = mapped_column(String(2))  # ID / CI / FR... : pertinent pour ivoirien/francais
    created_at: Mapped[datetime] = mapped_column(default=_utcnow, nullable=False)

    user: Mapped["User"] = relationship(back_populates="corrections")


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
