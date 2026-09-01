"""src/corrections.py : consentement RGPD et capture des corrections humaines.
Base en memoire (jamais sur disque)."""
import pytest

from src import auth, corrections, db
from src.models import Correction


@pytest.fixture(autouse=True)
def _isolate():
    db.init_db_memory()
    yield
    db.close_db()


def _user(email="u@x.com"):
    return auth.register_user(email, "motdepasse123")


def test_pas_de_capture_sans_consentement():
    uid = _user()
    # register_user() accorde le consentement par defaut (Tache 6) : on le
    # retire explicitement pour tester le cas SANS consentement.
    corrections.set_consent(uid, "training_data", False)
    result = corrections.record_correction(
        uid, None, {"total": 900}, {"total": 1000}, engine="donut", country="ID")
    assert result is None
    with db.get_db() as s:
        assert s.query(Correction).count() == 0


def test_capture_avec_consentement():
    uid = _user()
    corrections.set_consent(uid, "training_data", True)
    cid = corrections.record_correction(
        uid, None, {"total": 900}, {"total": 1000}, engine="donut", country="CI")
    assert cid is not None
    with db.get_db() as s:
        corr = s.query(Correction).one()
        assert corr.user_id == uid
        assert corr.raw_json == {"total": 900}
        assert corr.corrected_json == {"total": 1000}
        assert corr.engine == "donut"
        assert corr.country == "CI"


def test_pas_de_capture_si_rien_de_corrige():
    uid = _user()
    corrections.set_consent(uid, "training_data", True)
    result = corrections.record_correction(uid, None, {"total": 1000}, {"total": 1000})
    assert result is None


def test_retrait_du_consentement():
    uid = _user()
    corrections.set_consent(uid, "training_data", True)
    assert corrections.has_consent(uid, "training_data") is True
    corrections.set_consent(uid, "training_data", False)
    assert corrections.has_consent(uid, "training_data") is False
    # le retrait est un NOUVEL enregistrement, l'historique du consentement
    # initial n'est pas efface (journal append-only) -- 3 lignes : l'octroi
    # par defaut a l'inscription (Tache 6), l'octroi explicite ci-dessus, le
    # retrait.
    with db.get_db() as s:
        from src.models import Consent
        assert s.query(Consent).filter_by(user_id=uid).count() == 3
    result = corrections.record_correction(uid, None, {"total": 1}, {"total": 2})
    assert result is None


def test_consentement_utilisateur_inconnu_est_faux():
    assert corrections.has_consent(999, "training_data") is False
