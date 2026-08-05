"""Endpoints /api/auth/* (api.py) : inscription, connexion, deconnexion,
identite courante. Base en memoire (jamais sur disque), lifespan de l'app
non declenche (meme discipline que test_api.py -- TestClient sans context
manager), donc src.db initialise directement par la fixture."""
import pytest
from fastapi.testclient import TestClient

import api
from src import auth, db

client = TestClient(api.app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _isolate():
    db.init_db_memory()
    auth._FAILED_LOGINS.clear()
    client.cookies.clear()
    yield
    db.close_db()
    client.cookies.clear()


def test_register_puis_me():
    r = client.post("/api/auth/register", json={"email": "a@x.com", "password": "motdepasse123"})
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert "auth_token" in r.cookies

    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["user_id"] == body["user_id"]


def test_register_email_deja_pris():
    client.post("/api/auth/register", json={"email": "dup@x.com", "password": "motdepasse123"})
    r = client.post("/api/auth/register", json={"email": "dup@x.com", "password": "autremotdepasse"})
    assert r.status_code == 422
    assert r.json()["success"] is False


def test_register_mot_de_passe_trop_court():
    r = client.post("/api/auth/register", json={"email": "d@x.com", "password": "court"})
    assert r.status_code == 422


def test_login_logout():
    client.post("/api/auth/register", json={"email": "b@x.com", "password": "motdepasse123"})
    client.post("/api/auth/logout")

    r = client.post("/api/auth/login", json={"email": "b@x.com", "password": "motdepasse123"})
    assert r.status_code == 200
    assert client.get("/api/auth/me").status_code == 200

    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401


def test_login_mauvais_mot_de_passe():
    client.post("/api/auth/register", json={"email": "c@x.com", "password": "motdepasse123"})
    r = client.post("/api/auth/login", json={"email": "c@x.com", "password": "faux-mot-de-passe"})
    assert r.status_code == 401
    assert r.json()["success"] is False


def test_me_sans_connexion():
    r = client.get("/api/auth/me")
    assert r.status_code == 401
