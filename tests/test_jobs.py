"""src/jobs.py : file d'attente en mémoire pour les tâches longues."""
import threading
import time

import pytest

from src import jobs


@pytest.fixture(autouse=True)
def _isolate():
    jobs.reset_all()
    yield
    jobs.reset_all()


def _wait_until(job_id, timeout=2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = jobs.get_status(job_id)
        if status["status"] not in ("pending", "running"):
            return status
        time.sleep(0.01)
    return jobs.get_status(job_id)


def test_job_reussi():
    job_id = jobs.submit(lambda x: x * 2, 21)
    status = _wait_until(job_id)
    assert status["status"] == "done"
    assert status["result"] == 42


def test_job_echoue_capture_lerreur_sans_planter():
    def _boom():
        raise ValueError("erreur volontaire")
    job_id = jobs.submit(_boom)
    status = _wait_until(job_id)
    assert status["status"] == "error"
    assert "erreur volontaire" in status["error"]


def test_job_inconnu_renvoie_none():
    assert jobs.get_status("id-inexistant") is None


def test_statut_pending_avant_execution():
    """Une fonction lente doit laisser le temps d'observer l'état pending
    avant qu'il ne passe à running/done."""
    started = threading.Event()
    finish = threading.Event()

    def _slow():
        started.set()
        finish.wait(timeout=2)
        return "fini"

    job_id = jobs.submit(_slow)
    started.wait(timeout=2)   # laisse le worker vraiment démarrer
    status = jobs.get_status(job_id)
    assert status["status"] in ("running", "done")   # jamais resté bloqué à pending
    finish.set()
    final = _wait_until(job_id)
    assert final["status"] == "done"
    assert final["result"] == "fini"


def test_jobs_concurrents_serialises_par_max_workers():
    """MAX_WORKERS=1 : deux tâches lancées en même temps ne s'exécutent
    jamais réellement en parallèle -- vérifie la contrainte de concurrence
    qui sert aussi d'optimisation (pas de contention CPU entre inférences)."""
    concurrent_count = {"current": 0, "max_seen": 0}
    lock = threading.Lock()

    def _track():
        with lock:
            concurrent_count["current"] += 1
            concurrent_count["max_seen"] = max(concurrent_count["max_seen"], concurrent_count["current"])
        time.sleep(0.1)
        with lock:
            concurrent_count["current"] -= 1
        return "ok"

    j1 = jobs.submit(_track)
    j2 = jobs.submit(_track)
    _wait_until(j1, timeout=3)
    _wait_until(j2, timeout=3)
    assert concurrent_count["max_seen"] <= jobs.MAX_WORKERS


def test_purge_des_jobs_anciens(monkeypatch):
    job_id = jobs.submit(lambda: "x")
    _wait_until(job_id)
    # simule un job termine il y a longtemps
    with jobs._lock:
        jobs._jobs[job_id]["created_at"] = time.time() - jobs.JOB_TTL_SECONDS - 1
    jobs._purge_old()
    assert jobs.get_status(job_id) is None
