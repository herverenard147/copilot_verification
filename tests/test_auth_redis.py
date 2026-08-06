"""src/auth.py : verrou anti brute-force partagé via Redis contre un VRAI
Redis (pas un mock) -- sans ça, un attaquant contourne le verrou en
répartissant ses tentatives entre plusieurs instances."""
import os

import pytest

redis = pytest.importorskip("redis")

from src import auth, db  # noqa: E402

TEST_REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://127.0.0.1:6390")


def _redis_available():
    try:
        client = redis.from_url(TEST_REDIS_URL, socket_connect_timeout=1)
        client.ping()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _redis_available(), reason="Redis de test non joignable")


@pytest.fixture(autouse=True)
def _isolate():
    db.init_db_memory()
    auth._FAILED_LOGINS.clear()
    auth.init_redis(TEST_REDIS_URL)
    client = redis.from_url(TEST_REDIS_URL, decode_responses=True)
    for key in client.scan_iter(match=f"{auth._REDIS_PREFIX}*"):
        client.delete(key)
    yield
    auth.close_redis()
    db.close_db()


def test_verrouillage_visible_sans_le_dict_local():
    """Simule DEUX instances : les échecs sont enregistrés, puis le dict
    local vidé (simule un process B qui n'a vu aucun de ces échecs) -- le
    verrou doit quand même s'appliquer, via Redis."""
    auth.register_user("lock@x.com", "motdepasse123")
    for _ in range(auth.MAX_ATTEMPTS):
        assert auth.authenticate("lock@x.com", "mauvais") is None

    auth._FAILED_LOGINS.clear()   # simule "une autre instance"
    assert auth.authenticate("lock@x.com", "motdepasse123") is None


def test_succes_efface_le_verrou_entre_instances():
    auth.register_user("clear@x.com", "motdepasse123")
    for _ in range(auth.MAX_ATTEMPTS - 1):
        auth.authenticate("clear@x.com", "mauvais")
    assert auth.authenticate("clear@x.com", "motdepasse123") is not None

    auth._FAILED_LOGINS.clear()
    # le verrou est bien levé (pas seulement localement) : re-échouer ne
    # verrouille pas immédiatement puisque le compteur a été remis à zéro
    assert auth.authenticate("clear@x.com", "mauvais") is None
    assert auth.authenticate("clear@x.com", "motdepasse123") is not None


def test_repli_memoire_locale_si_redis_indisponible():
    auth.init_redis("redis://127.0.0.1:1")   # port fermé
    assert auth._redis is None
    auth.register_user("fallback@x.com", "motdepasse123")
    assert auth.authenticate("fallback@x.com", "motdepasse123") is not None
