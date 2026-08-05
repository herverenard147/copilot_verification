"""Endpoints RGPD (api.py) : export des données personnelles, suppression de
compte en cascade. Base en mémoire, lifespan non déclenché (même discipline
que test_auth_api.py)."""
import pytest
from fastapi.testclient import TestClient

import api
from src import auth, corrections, db
from src.models import Consent, Correction, User

client = TestClient(api.app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _isolate():
    db.init_db_memory()
    auth._FAILED_LOGINS.clear()
    client.cookies.clear()
    yield
    db.close_db()
    client.cookies.clear()


def test_export_sans_connexion():
    r = client.get("/api/auth/export")
    assert r.status_code == 401


def test_export_contenu():
    client.post("/api/auth/register", json={"email": "exp@x.com", "password": "motdepasse123"})
    client.post("/api/auth/consent", json={"consent_type": "training_data", "granted": True})
    client.post("/api/validate", json={
        "items": [{"name": "Café", "quantity": 1, "unit_price": 1000, "line_price": 1000}],
        "subtotal": 1000, "total": 1000, "country": "CI", "persist": True,
        "engine": "donut",
        "raw_json": {"items": [], "subtotal": 900, "total": 900},
    })

    r = client.get("/api/auth/export")
    assert r.status_code == 200
    body = r.json()
    assert body["account"]["email"] == "exp@x.com"
    assert len(body["consents"]) == 1
    assert body["consents"][0]["granted"] is True
    assert len(body["corrections"]) == 1
    assert body["corrections"][0]["engine"] == "donut"
    assert "note" in body  # honnête sur ce qui n'est pas encore inclus


def test_suppression_compte_sans_connexion():
    r = client.request("DELETE", "/api/auth/account", json={"password": "peu-importe"})
    assert r.status_code == 401


def test_suppression_compte_mauvais_mot_de_passe():
    client.post("/api/auth/register", json={"email": "del@x.com", "password": "motdepasse123"})
    r = client.request("DELETE", "/api/auth/account", json={"password": "faux-mot-de-passe"})
    assert r.status_code == 401
    with db.get_db() as s:
        assert s.query(User).count() == 1  # pas supprimé


def test_suppression_compte_cascade():
    client.post("/api/auth/register", json={"email": "gone@x.com", "password": "motdepasse123"})
    client.post("/api/auth/consent", json={"consent_type": "training_data", "granted": True})
    client.post("/api/validate", json={
        "items": [], "subtotal": 1, "total": 1, "country": "CI", "persist": False,
        "raw_json": {"total": 0}, "engine": "donut",
    })
    with db.get_db() as s:
        assert s.query(User).count() == 1
        assert s.query(Consent).count() == 1
        assert s.query(Correction).count() == 1

    r = client.request("DELETE", "/api/auth/account", json={"password": "motdepasse123"})
    assert r.status_code == 200
    assert r.json()["deleted"] is True

    with db.get_db() as s:
        assert s.query(User).count() == 0
        assert s.query(Consent).count() == 0
        assert s.query(Correction).count() == 0

    # le cookie d'auth est bien invalidé après suppression
    assert client.get("/api/auth/me").status_code == 401
