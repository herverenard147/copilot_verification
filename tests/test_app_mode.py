"""APP_MODE=prod : reçus rattachés au compte, pas d'accès anonyme, corpus de
démonstration indisponible. APP_MODE=demo (défaut) : comportement historique
inchangé (déjà couvert par les autres suites, on vérifie juste la
non-régression ici)."""
import pytest
from fastapi.testclient import TestClient

import api
from src import auth, db, session_store

client = TestClient(api.app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _isolate():
    db.init_db_memory()
    auth._FAILED_LOGINS.clear()
    session_store.reset_all()
    session_store.disable_persistence()
    client.cookies.clear()
    yield
    db.close_db()
    session_store.reset_all()
    client.cookies.clear()


def test_dashboard_refuse_anonyme_en_prod(monkeypatch):
    monkeypatch.setattr(api, "APP_MODE", "prod")
    r = client.get("/api/dashboard")
    assert r.status_code == 401


def test_dashboard_accessible_apres_connexion_en_prod(monkeypatch):
    monkeypatch.setattr(api, "APP_MODE", "prod")
    client.post("/api/auth/register", json={"email": "p@x.com", "password": "motdepasse123"})
    r = client.get("/api/dashboard")
    assert r.status_code == 200
    assert r.json()["empty"] is True


def test_recu_rattache_au_compte_pas_au_cookie_de_session(monkeypatch):
    """Le meme compte, meme sans le cookie de session anonyme (sid), voit ses
    reçus : la persistance suit le compte, pas un cookie ephemere."""
    monkeypatch.setattr(api, "APP_MODE", "prod")
    client.post("/api/auth/register", json={"email": "q@x.com", "password": "motdepasse123"})
    r = client.post("/api/validate", json={
        "items": [{"name": "Café", "quantity": 1, "unit_price": 1000, "line_price": 1000}],
        "subtotal": 1000, "total": 1000, "country": "CI", "persist": True,
    })
    assert r.status_code == 200
    assert r.json()["persisted"] is True

    # simule un nouvel appareil/navigateur (nouveau cookie sid), meme compte
    auth_token = client.cookies.get("auth_token")
    client.cookies.clear()
    client.cookies.set("auth_token", auth_token)

    d = client.get("/api/dashboard")
    assert d.status_code == 200
    assert d.json()["kpis"]["n_receipts"] == 1


def test_deux_comptes_ne_partagent_pas_leurs_recus(monkeypatch):
    monkeypatch.setattr(api, "APP_MODE", "prod")
    client.post("/api/auth/register", json={"email": "a1@x.com", "password": "motdepasse123"})
    client.post("/api/validate", json={
        "items": [], "subtotal": 500, "total": 500, "country": "CI", "persist": True,
    })
    client.post("/api/auth/logout")
    client.post("/api/auth/register", json={"email": "a2@x.com", "password": "motdepasse123"})

    d = client.get("/api/dashboard")
    assert d.status_code == 200
    assert d.json()["empty"] is True


def test_demo_indisponible_en_prod_meme_connecte(monkeypatch):
    monkeypatch.setattr(api, "APP_MODE", "prod")
    client.post("/api/auth/register", json={"email": "d1@x.com", "password": "motdepasse123"})
    r = client.post("/api/settings/demo", json={"enabled": True})
    assert r.status_code == 403


def test_config_expose_app_mode(monkeypatch):
    monkeypatch.setattr(api, "APP_MODE", "prod")
    assert client.get("/api/config").json()["app_mode"] == "prod"
    monkeypatch.setattr(api, "APP_MODE", "demo")
    assert client.get("/api/config").json()["app_mode"] == "demo"


def test_export_inclut_les_recus_en_prod(monkeypatch):
    monkeypatch.setattr(api, "APP_MODE", "prod")
    client.post("/api/auth/register", json={"email": "exp2@x.com", "password": "motdepasse123"})
    client.post("/api/validate", json={
        "items": [{"name": "Eau", "quantity": 2, "unit_price": 500, "line_price": 1000}],
        "subtotal": 1000, "total": 1000, "country": "CI", "persist": True,
    })
    r = client.get("/api/auth/export")
    assert r.status_code == 200
    body = r.json()
    assert len(body["receipts"]) == 1
    assert body["receipts"][0]["total"] == 1000


def test_suppression_compte_purge_le_registre_des_recus_en_prod(monkeypatch):
    monkeypatch.setattr(api, "APP_MODE", "prod")
    r0 = client.post("/api/auth/register", json={"email": "del2@x.com", "password": "motdepasse123"})
    uid = r0.json()["user_id"]
    client.post("/api/validate", json={
        "items": [], "subtotal": 200, "total": 200, "country": "CI", "persist": True,
    })
    assert f"user:{uid}" in session_store._sessions

    r = client.request("DELETE", "/api/auth/account", json={"password": "motdepasse123"})
    assert r.status_code == 200
    assert f"user:{uid}" not in session_store._sessions


def test_mode_demo_par_defaut_acces_anonyme_inchange():
    """Non-regression : sans APP_MODE=prod (defaut demo), l'acces anonyme
    marche toujours exactement comme avant."""
    r = client.get("/api/dashboard")
    assert r.status_code == 200
    r2 = client.post("/api/settings/demo", json={"enabled": True})
    assert r2.status_code == 200
