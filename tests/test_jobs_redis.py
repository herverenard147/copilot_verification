"""src/jobs.py : statut de job partagé via Redis contre un VRAI Redis (pas
un mock) -- la pièce qui permet au polling de fonctionner quelle que soit
l'instance qui reçoit la requête."""
import os
import time

import pytest

redis = pytest.importorskip("redis")

from src import jobs  # noqa: E402

TEST_REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://127.0.0.1:6390")


def _redis_available():
    try:
        client = redis.from_url(TEST_REDIS_URL, socket_connect_timeout=1)
        client.ping()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _redis_available(), reason="Redis de test non joignable")


def _wait_until(job_id, timeout=2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = jobs.get_status(job_id)
        if status and status["status"] not in ("pending", "running"):
            return status
        time.sleep(0.01)
    return jobs.get_status(job_id)


@pytest.fixture(autouse=True)
def _isolate():
    jobs.reset_all()
    jobs.init_redis(TEST_REDIS_URL)
    # purge les cles de test residuelles
    client = redis.from_url(TEST_REDIS_URL, decode_responses=True)
    for key in client.scan_iter(match=f"{jobs._REDIS_PREFIX}*"):
        client.delete(key)
    yield
    jobs.reset_all()
    jobs.close_redis()


def test_statut_visible_sans_le_dict_local():
    """Simule DEUX instances : le job est soumis, puis le dict LOCAL vidé
    (simule un process B qui n'a jamais vu ce job) -- get_status() doit
    quand même le trouver, via Redis."""
    job_id = jobs.submit(lambda: {"total": 1000, "success": True})
    status = _wait_until(job_id)
    assert status["status"] == "done"

    jobs._jobs.clear()   # simule "une autre instance"
    status2 = jobs.get_status(job_id)
    assert status2["status"] == "done"
    assert status2["result"]["total"] == 1000


def test_job_inconnu_renvoie_none():
    assert jobs.get_status("id-jamais-vu") is None


def test_erreur_partagee_entre_instances():
    def _boom():
        raise ValueError("panne volontaire")
    job_id = jobs.submit(_boom)
    _wait_until(job_id)
    jobs._jobs.clear()
    status = jobs.get_status(job_id)
    assert status["status"] == "error"
    assert "panne volontaire" in status["error"]


def test_repli_memoire_locale_si_redis_indisponible():
    jobs.init_redis("redis://127.0.0.1:1")   # port fermé
    assert jobs._redis is None
    job_id = jobs.submit(lambda: "ok")
    status = _wait_until(job_id)
    assert status["status"] == "done"
    assert status["result"] == "ok"
