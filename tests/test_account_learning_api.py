"""Boucle complète : un utilisateur connecté surcharge manuellement le
compte d'une catégorie -> le prochain reçu de la même catégorie propose
directement ce compte, sans qu'il ait à recorriger. Mode prod (le seul où
la préférence a un sens : nécessite un compte)."""
import pytest
from fastapi.testclient import TestClient

import api
from src import auth, db, session_store

client = TestClient(api.app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    db.init_db_memory()
    auth._FAILED_LOGINS.clear()
    session_store.reset_all()
    session_store.disable_persistence()
    client.cookies.clear()
    monkeypatch.setattr(api, "APP_MODE", "prod")
    yield
    db.close_db()
    session_store.reset_all()
    client.cookies.clear()


def _payload(account_overrides=None, persist=True):
    return {
        "items": [{"name": "Taxi", "quantity": 1, "unit_price": 2000, "line_price": 2000,
                   "category": "transport"}],
        "subtotal": 2000, "total": 2000, "country": "CI", "persist": persist,
        "account_overrides": account_overrides or {},
    }


def test_surcharge_puis_reutilisee_automatiquement():
    client.post("/api/auth/register", json={"email": "learn@x.com", "password": "motdepasse123"})

    # 1er reçu "transport" : compte par défaut (6181), pas de surcharge
    r1 = client.post("/api/validate", json=_payload())
    assert r1.status_code == 200
    line1 = next(l for l in r1.json()["journal"] if l["debit"] > 0 and l["account"] != "4452")
    assert line1["account"] == "6181"

    # L'utilisateur corrige manuellement vers 605 sur ce reçu
    r2 = client.post("/api/validate", json=_payload(account_overrides={"0": "605"}))
    assert r2.status_code == 200
    line2 = next(l for l in r2.json()["journal"] if l["debit"] > 0 and l["account"] != "4452")
    assert line2["account"] == "605"
    assert line2.get("manual") is True

    # Nouveau reçu "transport", SANS surcharge cette fois : 605 proposé directement
    r3 = client.post("/api/validate", json=_payload())
    assert r3.status_code == 200
    line3 = next(l for l in r3.json()["journal"] if l["debit"] > 0 and l["account"] != "4452")
    assert line3["account"] == "605"
    assert not line3.get("manual")   # proposé par défaut, pas une surcharge de CE reçu


def test_preference_isolee_par_compte():
    client.post("/api/auth/register", json={"email": "l1@x.com", "password": "motdepasse123"})
    client.post("/api/validate", json=_payload(account_overrides={"0": "605"}))
    client.post("/api/auth/logout")

    client.post("/api/auth/register", json={"email": "l2@x.com", "password": "motdepasse123"})
    r = client.post("/api/validate", json=_payload())
    line = next(l for l in r.json()["journal"] if l["debit"] > 0 and l["account"] != "4452")
    assert line["account"] == "6181"   # pas influencé par la préférence de l1


def test_anonyme_garde_le_mapping_par_defaut():
    """Non-régression du bug corrigé : un anonyme (category_account_map={})
    doit toujours voir le mapping par défaut, jamais un mapping vidé. persist
    à False n'exige pas de session (calcul seul), donc marche même en prod."""
    r = client.post("/api/validate", json=_payload(persist=False))
    assert r.status_code == 200
    line = next(l for l in r.json()["journal"] if l["debit"] > 0 and l["account"] != "4452")
    assert line["account"] == "6181"
