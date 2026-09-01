"""Pipeline complet via l'API : connexion + consentement + /api/validate ou
PUT /api/receipt/{id} avec raw_json => une Correction est capturee, et
seulement dans ce cas (jamais pour un anonyme, jamais sans consentement,
jamais si rien n'a ete corrige). Base en memoire, lifespan non declenche
(meme discipline que test_auth_api.py)."""
import pytest
from fastapi.testclient import TestClient

import api
from src import auth, db
from src.models import Correction

client = TestClient(api.app, raise_server_exceptions=False)

FLAGS_ITEMS = [{"name": "Café", "quantity": 1, "unit_price": 1000,
               "line_price": 1000, "category": "food"}]
RAW = {"items": [{"name": "Cafe", "quantity": 1, "unit_price": 900, "line_price": 900}],
       "subtotal": 900, "tax": None, "total": 900}


def _payload(**overrides):
    body = {"items": FLAGS_ITEMS, "subtotal": 1000, "tax": None, "total": 1000,
            "category": "food", "country": "CI", "persist": True}
    body.update(overrides)
    return body


@pytest.fixture(autouse=True)
def _isolate():
    db.init_db_memory()
    auth._FAILED_LOGINS.clear()
    client.cookies.clear()
    yield
    db.close_db()
    client.cookies.clear()


def _register_login_consent(email):
    client.post("/api/auth/register", json={"email": email, "password": "motdepasse123"})
    client.post("/api/auth/consent", json={"consent_type": "training_data", "granted": True})


def test_correction_capturee_si_connecte_et_consentant():
    _register_login_consent("ok@x.com")
    r = client.post("/api/validate", json=_payload(raw_json=RAW, engine="donut"))
    assert r.status_code == 200
    with db.get_db() as s:
        corr = s.query(Correction).one()
        assert corr.engine == "donut"
        assert corr.country == "CI"
        assert corr.raw_json == RAW


def test_pas_de_capture_sans_raw_json():
    _register_login_consent("norw@x.com")
    r = client.post("/api/validate", json=_payload())
    assert r.status_code == 200
    with db.get_db() as s:
        assert s.query(Correction).count() == 0


def test_pas_de_capture_sans_consentement():
    client.post("/api/auth/register", json={"email": "noconsent@x.com", "password": "motdepasse123"})
    # register_user() accorde le consentement par defaut (Tache 6) : on le
    # retire explicitement pour tester le cas SANS consentement.
    client.post("/api/auth/consent", json={"consent_type": "training_data", "granted": False})
    r = client.post("/api/validate", json=_payload(raw_json=RAW))
    assert r.status_code == 200
    with db.get_db() as s:
        assert s.query(Correction).count() == 0


def test_pas_de_capture_anonyme():
    client.cookies.clear()
    r = client.post("/api/validate", json=_payload(raw_json=RAW))
    assert r.status_code == 200
    with db.get_db() as s:
        assert s.query(Correction).count() == 0


def test_validate_fonctionne_normalement_sans_toucher_a_raw_json():
    """Non-regression : le champ raw_json est optionnel, un client qui ne
    l'envoie jamais (front actuel non encore mis a jour) continue de marcher."""
    r = client.post("/api/validate", json=_payload(persist=False))
    assert r.status_code == 200
    assert r.json()["success"] is True


def test_capture_sur_put_receipt_update():
    _register_login_consent("edit@x.com")
    created = client.post("/api/validate", json=_payload(persist=True))
    receipt_id = created.json()["receipt_id"]

    r = client.put(f"/api/receipt/{receipt_id}", json=_payload(raw_json=RAW, engine="llm_fallback"))
    assert r.status_code == 200
    with db.get_db() as s:
        corr = s.query(Correction).one()
        assert corr.receipt_id == receipt_id
        assert corr.engine == "llm_fallback"
