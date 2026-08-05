"""src/auth.py : hachage argon2id, inscription/authentification, jetons de
session signes. Base en memoire (jamais sur disque pendant les tests)."""
import pytest

from src import auth, db


@pytest.fixture(autouse=True)
def _isolate():
    db.init_db_memory()
    auth._FAILED_LOGINS.clear()
    yield
    db.close_db()


def test_hash_password_est_different_du_clair():
    h = auth.hash_password("motdepasse123")
    assert h != "motdepasse123"
    assert auth.verify_password("motdepasse123", h)
    assert not auth.verify_password("mauvais", h)


def test_register_puis_authenticate():
    uid = auth.register_user("Test@Exemple.com", "motdepasse123")
    assert uid is not None
    # email normalise en minuscule, verifie a l'authentification aussi
    assert auth.authenticate("test@exemple.com", "motdepasse123") == uid


def test_register_email_deja_pris():
    auth.register_user("dup@x.com", "motdepasse123")
    with pytest.raises(ValueError):
        auth.register_user("dup@x.com", "autremotdepasse")


def test_register_mot_de_passe_trop_court():
    with pytest.raises(ValueError):
        auth.register_user("a@x.com", "court1")


def test_register_email_invalide():
    with pytest.raises(ValueError):
        auth.register_user("pas-un-email", "motdepasse123")


def test_authenticate_mauvais_mot_de_passe():
    auth.register_user("b@x.com", "motdepasse123")
    assert auth.authenticate("b@x.com", "faux-mot-de-passe") is None


def test_authenticate_email_inconnu():
    assert auth.authenticate("inconnu@x.com", "peu-importe") is None


def test_verrouillage_apres_echecs_repetes():
    auth.register_user("lock@x.com", "motdepasse123")
    for _ in range(auth.MAX_ATTEMPTS):
        assert auth.authenticate("lock@x.com", "mauvais") is None
    # verrouille temporairement, meme avec le bon mot de passe
    assert auth.authenticate("lock@x.com", "motdepasse123") is None


def test_token_roundtrip():
    uid = auth.register_user("c@x.com", "motdepasse123")
    token = auth.issue_token(uid)
    assert auth.verify_token(token) == uid


def test_token_invalide():
    assert auth.verify_token("charabia-non-signe") is None
    assert auth.verify_token("") is None
    assert auth.verify_token(None) is None


def test_token_altere_refuse():
    # Modifier le dernier caractere seul est peu fiable (bits de bourrage
    # base64 parfois ignores au decodage) : on altere le milieu du jeton,
    # qui casse forcement soit le payload soit la signature.
    token = auth.issue_token(1)
    mid = len(token) // 2
    altered = token[:mid] + ("x" if token[mid] != "x" else "y") + token[mid + 1:]
    assert auth.verify_token(altered) is None


def test_token_expire(monkeypatch):
    token = auth.issue_token(1)
    monkeypatch.setattr(auth, "SESSION_MAX_AGE", -1)
    assert auth.verify_token(token) is None


def test_secret_key_depuis_env(monkeypatch):
    monkeypatch.setenv("AUTH_SECRET_KEY", "cle-de-test-suffisamment-longue")
    token = auth.issue_token(42)
    assert auth.verify_token(token) == 42
