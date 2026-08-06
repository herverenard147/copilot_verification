"""src/rate_limit.py : compteur de debit partagé via Redis contre un VRAI
Redis (pas un mock) -- sans ça, un attaquant contournerait la limite en
répartissant ses requêtes entre plusieurs instances."""
import os

import pytest

redis = pytest.importorskip("redis")

from src import rate_limit  # noqa: E402

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
    rate_limit.reset_all()
    rate_limit.init_redis(TEST_REDIS_URL)
    client = redis.from_url(TEST_REDIS_URL, decode_responses=True)
    for key in client.scan_iter(match=f"{rate_limit._REDIS_PREFIX}*"):
        client.delete(key)
    yield
    rate_limit.reset_all()
    rate_limit.close_redis()


def test_compteur_partage_entre_instances():
    """Simule DEUX instances : les hits d'une IP sont comptés via Redis, pas
    seulement le dict local -- vider le dict local ne doit RIEN changer."""
    max_requests, _ = rate_limit.LIMITS["bilan_import"]
    for _ in range(max_requests):
        assert rate_limit.check("bilan_import", "1.2.3.4") is True

    rate_limit._hits.clear()   # simule "une autre instance" qui n'a jamais vu cette IP
    assert rate_limit.check("bilan_import", "1.2.3.4") is False


def test_ips_distinctes_isolees():
    max_requests, _ = rate_limit.LIMITS["extract"]
    for _ in range(max_requests):
        assert rate_limit.check("extract", "9.9.9.9") is True
    assert rate_limit.check("extract", "9.9.9.9") is False
    assert rate_limit.check("extract", "8.8.8.8") is True


def test_repli_memoire_locale_si_redis_indisponible():
    rate_limit.init_redis("redis://127.0.0.1:1")   # port fermé
    assert rate_limit._redis is None
    assert rate_limit.check("default", "5.5.5.5") is True
