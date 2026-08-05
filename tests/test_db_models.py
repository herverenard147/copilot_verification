"""Modele SQLAlchemy (src/db.py, src/models.py) : comptes, corrections,
consentements. Pas de Receipt ici (les recus vivent dans session_store.py,
voir src/models.py). Base en memoire uniquement (jamais sur disque pendant
les tests, meme discipline que test_persistence.py pour session_store)."""
import pytest
from sqlalchemy.exc import IntegrityError

from src import db
from src.models import Consent, Correction, User


@pytest.fixture(autouse=True)
def _isolate():
    db.init_db_memory()
    yield
    db.close_db()


def test_creation_utilisateur():
    with db.get_db() as s:
        s.add(User(email="a@b.com", password_hash="hash-opaque"))
    with db.get_db() as s:
        u = s.query(User).filter_by(email="a@b.com").one()
        assert u.id is not None
        assert u.password_hash == "hash-opaque"
        assert u.is_active is True


def test_email_unique():
    with db.get_db() as s:
        s.add(User(email="dup@x.com", password_hash="h1"))
    with pytest.raises(IntegrityError):
        with db.get_db() as s:
            s.add(User(email="dup@x.com", password_hash="h2"))


def test_correction_sans_utilisateur_refusee():
    """Pas de collecte de donnees d'entrainement anonyme : user_id obligatoire."""
    with pytest.raises(IntegrityError):
        with db.get_db() as s:
            s.add(Correction(user_id=None, raw_json={"total": 0}, corrected_json={"total": 1}))


def test_correction_utilisateur_inexistant_refusee():
    """Foreign key reellement appliquee (PRAGMA foreign_keys=ON)."""
    with pytest.raises(IntegrityError):
        with db.get_db() as s:
            s.add(Correction(user_id=999, raw_json={"total": 0}, corrected_json={"total": 1}))


def test_suppression_utilisateur_cascade():
    with db.get_db() as s:
        u = User(email="c@x.com", password_hash="h")
        s.add(u)
        s.flush()
        s.add(Correction(user_id=u.id, receipt_id=7,
                         raw_json={"total": 900}, corrected_json={"total": 1000}))
        s.add(Consent(user_id=u.id, consent_type="training_data", granted=True))

    with db.get_db() as s:
        assert s.query(Correction).count() == 1
        assert s.query(Consent).count() == 1

    with db.get_db() as s:
        u = s.query(User).filter_by(email="c@x.com").one()
        s.delete(u)

    with db.get_db() as s:
        assert s.query(Correction).count() == 0
        assert s.query(Consent).count() == 0


def test_correction_receipt_id_nest_pas_une_foreign_key():
    """receipt_id sur Correction reste un entier informatif (voir commentaire
    du modele) : aucune contrainte d'integrite ne le relie a session_store,
    ou il n'existe pas necessairement de recu portant ce numero -- ca ne doit
    jamais empecher la creation d'une correction."""
    with db.get_db() as s:
        u = User(email="d@x.com", password_hash="h")
        s.add(u)
        s.flush()
        s.add(Correction(user_id=u.id, receipt_id=4242,
                         raw_json={"total": 0}, corrected_json={"total": 1}))

    with db.get_db() as s:
        corr = s.query(Correction).one()
        assert corr.receipt_id == 4242
        assert corr.corrected_json == {"total": 1}


def test_pas_dio_disque_sans_init(tmp_path, monkeypatch):
    """Sans init_db()/init_db_memory(), get_db() echoue plutot que d'ecrire
    silencieusement quelque part (meme garantie que session_store)."""
    db.close_db()
    with pytest.raises(RuntimeError):
        with db.get_db():
            pass
