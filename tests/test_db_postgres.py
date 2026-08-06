"""src/db.py : bascule vers Postgres via DATABASE_URL, contre un VRAI
Postgres (pas un mock) -- c'est la piece qui manquait pour que la base
comptes/corrections/bilan soit partagee entre plusieurs instances (SQLite
est un fichier local a une seule instance, invisible aux autres)."""
import os

import pytest

psycopg = pytest.importorskip("psycopg")

from src import db  # noqa: E402
from src.models import User  # noqa: E402

TEST_POSTGRES_URL = os.environ.get(
    "TEST_POSTGRES_URL", "postgresql+psycopg://test:test@127.0.0.1:5435/copilote_test"
)


def _postgres_available():
    try:
        # enleve le prefixe SQLAlchemy "+psycopg" : psycopg.connect prend une URL brute
        raw = TEST_POSTGRES_URL.replace("postgresql+psycopg://", "postgresql://")
        conn = psycopg.connect(raw, connect_timeout=1)
        conn.close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _postgres_available(), reason="Postgres de test non joignable")


@pytest.fixture(autouse=True)
def _isolate():
    os.environ["DATABASE_URL"] = TEST_POSTGRES_URL
    db.init_db("ignore-ce-chemin-sqlite")   # DATABASE_URL doit prendre le pas
    from src.models import Base
    with db._engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())
    yield
    db.close_db()
    os.environ.pop("DATABASE_URL", None)


def test_database_url_bascule_bien_sur_postgres():
    assert db._engine.url.get_backend_name() == "postgresql"


def test_ecriture_visible_par_une_autre_connexion_process():
    """Simule DEUX instances : ecrit un utilisateur via un premier
    'process' (init_db), ferme completement ce moteur (close_db, comme un
    redemarrage/une autre instance), puis en ouvre un second qui pointe sur
    la MEME base -- l'utilisateur doit toujours etre la."""
    with db.get_db() as s:
        s.add(User(email="postgres@x.com", password_hash="hash-fictif"))

    db.close_db()
    db.init_db("ignore-ce-chemin-sqlite")   # "nouvelle instance" -> nouveau moteur, meme DATABASE_URL

    with db.get_db() as s:
        user = s.query(User).filter_by(email="postgres@x.com").first()
        assert user is not None
        assert user.password_hash == "hash-fictif"


def test_contrainte_unique_email_appliquee():
    with db.get_db() as s:
        s.add(User(email="dup@x.com", password_hash="a"))
    with pytest.raises(Exception):
        with db.get_db() as s:
            s.add(User(email="dup@x.com", password_hash="b"))


def test_repli_sqlite_sans_database_url():
    os.environ.pop("DATABASE_URL", None)
    db.close_db()
    db.init_db_memory()
    assert db._engine.url.get_backend_name() == "sqlite"
