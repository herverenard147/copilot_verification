"""src/account_preferences.py : mémoire catégorie -> compte par utilisateur."""
import pytest

from src import account_preferences as prefs
from src import auth, db


@pytest.fixture(autouse=True)
def _isolate():
    db.init_db_memory()
    yield
    db.close_db()


def _user():
    return auth.register_user("u@x.com", "motdepasse123")


def test_aucune_preference_par_defaut():
    uid = _user()
    assert prefs.get_account_overrides_map(uid) == {}


def test_memorise_puis_relit():
    uid = _user()
    prefs.remember_account(uid, "Transport", "6181")
    assert prefs.get_account_overrides_map(uid) == {"transport": "6181"}


def test_normalisation_categorie():
    """Accents/casse ne doivent pas créer deux entrées distinctes."""
    uid = _user()
    prefs.remember_account(uid, "Café", "601")
    prefs.remember_account(uid, "CAFE", "605")
    m = prefs.get_account_overrides_map(uid)
    assert m == {"cafe": "605"}   # la seconde ecrase la premiere (meme cle normalisee)


def test_preferences_isolees_par_utilisateur():
    u1 = auth.register_user("a@x.com", "motdepasse123")
    u2 = auth.register_user("b@x.com", "motdepasse123")
    prefs.remember_account(u1, "transport", "6181")
    prefs.remember_account(u2, "transport", "605")
    assert prefs.get_account_overrides_map(u1) == {"transport": "6181"}
    assert prefs.get_account_overrides_map(u2) == {"transport": "605"}


def test_categorie_vide_ignoree():
    uid = _user()
    prefs.remember_account(uid, "", "601")
    prefs.remember_account(uid, None, "601")
    assert prefs.get_account_overrides_map(uid) == {}


def test_aucun_utilisateur_renvoie_vide():
    assert prefs.get_account_overrides_map(None) == {}
