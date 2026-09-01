"""Connexion et sessions SQLAlchemy pour les comptes, recus persistants,
corrections et consentements (src/models.py).

Meme discipline que src/session_store.py : AUCUNE I/O disque tant que
init_db() n'est pas appele explicitement (api.py au demarrage d'un vrai
serveur). Les tests utilisent init_db_memory() (SQLite en memoire, jamais
sur disque, jamais partage entre tests).

SCALING HORIZONTAL : SQLite est un fichier sur le disque LOCAL d'une seule
instance -- invisible aux autres. Des que DATABASE_URL est definie (ex.
"postgresql+psycopg://user:pass@host/db"), init_db() l'utilise a la place
de son chemin SQLite par defaut : toutes les instances partagent alors la
meme base Postgres. Sans DATABASE_URL, comportement historique inchange
(SQLite local, aucune regression pour un usage mono-instance)."""
import os
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.models import Base

_engine = None
_SessionLocal = None


def _is_sqlite(url):
    return url.startswith("sqlite")


def _enable_foreign_keys(engine):
    """SQLite n'applique les ondelete=CASCADE/SET NULL que si les foreign
    keys sont explicitement activees, par connexion. Postgres les applique
    nativement -- rien a faire de ce cote la."""
    @event.listens_for(engine, "connect")
    def _pragma(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def _migrate_add_columns(engine):
    """create_all() ne cree que les tables ABSENTES : une colonne ajoutee au
    modele (ex. User.full_name) n'apparait jamais sur une base existante sans
    ca. Migration minimale et idempotente (pas d'Alembic dans ce projet) :
    compare les colonnes du modele a celles reellement en base et ajoute
    celles qui manquent, en NULL/valeur par defaut -- jamais destructif."""
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue  # deja creee a neuf par create_all(), a jour
            existing_cols = {c["name"] for c in inspector.get_columns(table.name)}
            for col in table.columns:
                if col.name in existing_cols:
                    continue
                col_type = col.type.compile(engine.dialect)
                conn.execute(text(f"ALTER TABLE {table.name} ADD COLUMN {col.name} {col_type}"))


def _build(url, **engine_kwargs):
    global _engine, _SessionLocal
    # check_same_thread=False est une option specifique au driver SQLite
    # (sqlite3) -- la passer au driver Postgres (psycopg) leverait une
    # erreur, ce n'est un concept qui n'existe pas cote serveur SQL.
    connect_args = {"check_same_thread": False} if _is_sqlite(url) else {}
    _engine = create_engine(url, connect_args=connect_args, **engine_kwargs)
    if _is_sqlite(url):
        _enable_foreign_keys(_engine)
    Base.metadata.create_all(_engine)
    _migrate_add_columns(_engine)
    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)


def init_db(path):
    """Active la persistance vers `path` (SQLite, hors depot, ex.
    .local_state/app.db) -- SAUF si DATABASE_URL est definie, auquel cas
    elle est utilisee a la place (Postgres partage entre instances)."""
    url = os.environ.get("DATABASE_URL", "").strip()
    if url:
        _build(url)
        return
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    _build(f"sqlite:///{path}")


def init_db_memory():
    """Base ephemere en memoire : pour les tests, jamais sur disque.
    StaticPool = une seule connexion partagee entre threads : sans ca, chaque
    thread du threadpool FastAPI verrait sa PROPRE base ':memory:' vide (donc
    "no such table") des qu'un endpoint API est appele via TestClient."""
    _build("sqlite:///:memory:", poolclass=StaticPool)


def close_db():
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


@contextmanager
def get_db():
    """Session courte : commit automatique en sortie, rollback si exception."""
    if _SessionLocal is None:
        raise RuntimeError("init_db()/init_db_memory() n'a pas ete appele avant get_db().")
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
