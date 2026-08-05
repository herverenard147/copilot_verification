"""Connexion et sessions SQLAlchemy pour les comptes, recus persistants,
corrections et consentements (src/models.py).

Meme discipline que src/session_store.py : AUCUNE I/O disque tant que
init_db() n'est pas appele explicitement (api.py au demarrage d'un vrai
serveur). Les tests utilisent init_db_memory() (SQLite en memoire, jamais
sur disque, jamais partage entre tests).
"""
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from src.models import Base

_engine = None
_SessionLocal = None


def _enable_foreign_keys(engine):
    """SQLite n'applique les ondelete=CASCADE/SET NULL que si les foreign
    keys sont explicitement activees, par connexion."""
    @event.listens_for(engine, "connect")
    def _pragma(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def _build(url):
    global _engine, _SessionLocal
    _engine = create_engine(url, connect_args={"check_same_thread": False})
    _enable_foreign_keys(_engine)
    Base.metadata.create_all(_engine)
    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)


def init_db(path):
    """Active la persistance SQLite vers `path` (hors depot, ex. .local_state/app.db)."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    _build(f"sqlite:///{path}")


def init_db_memory():
    """Base ephemere en memoire : pour les tests, jamais sur disque."""
    _build("sqlite:///:memory:")


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
