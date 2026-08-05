"""Limitation de débit appliquée pour de vrai via le middleware (api.py),
pas seulement le module src/rate_limit.py en isolation."""
import pytest
from fastapi.testclient import TestClient

import api
from src import rate_limit, session_store

client = TestClient(api.app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _isolate():
    session_store.reset_all()
    session_store.disable_persistence()
    rate_limit.reset_all()
    client.cookies.clear()
    yield
    session_store.reset_all()
    rate_limit.reset_all()
    client.cookies.clear()


def test_endpoint_normal_pas_limite_en_usage_courant():
    for _ in range(20):
        r = client.get("/api/config")
        assert r.status_code == 200


def test_limite_par_defaut_declenche_429(monkeypatch):
    monkeypatch.setitem(rate_limit.LIMITS, "default", (5, 60))
    for _ in range(5):
        assert client.get("/api/config").status_code == 200
    r = client.get("/api/config")
    assert r.status_code == 429
    assert r.json()["success"] is False


def test_front_statique_jamais_limite(monkeypatch):
    """La limitation ne s'applique qu'à /api/*, jamais aux fichiers statiques
    (le front React) -- sinon charger la page elle-même pourrait échouer."""
    monkeypatch.setitem(rate_limit.LIMITS, "default", (2, 60))
    for _ in range(10):
        r = client.get("/")
        assert r.status_code != 429


def test_bucket_extract_plus_strict_que_default(monkeypatch):
    monkeypatch.setitem(rate_limit.LIMITS, "extract", (2, 60))
    monkeypatch.setitem(rate_limit.LIMITS, "default", (100, 60))
    for _ in range(2):
        client.post("/api/extract", files={"file": ("x.jpg", b"", "image/jpeg")})
    r = client.post("/api/extract", files={"file": ("x.jpg", b"", "image/jpeg")})
    assert r.status_code == 429
    # un autre endpoint /api/* n'est pas affecté (bucket "extract" isolé)
    assert client.get("/api/config").status_code == 200
