"""Tests d'intrusion : accès croisé entre comptes (IDOR), contournement
d'authentification, cookies falsifiés. Mode prod (le seul avec de vrais
comptes à isoler)."""
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


def _register(email):
    r = client.post("/api/auth/register", json={"email": email, "password": "motdepasse123"})
    return r.json()["user_id"], client.cookies.get(auth.AUTH_COOKIE)


# --- IDOR : reçus, comptabilité, bilan --------------------------------------

def test_idor_meme_receipt_id_isole_par_compte():
    """Deux comptes valident chacun un reçu -> même receipt_id=0 côté
    session_store (numérotation locale à chaque session), mais chacun ne doit
    voir QUE le sien."""
    uid1, token1 = _register("victim@x.com")
    client.post("/api/validate", json={
        "items": [{"name": "Secret A", "quantity": 1, "unit_price": 111, "line_price": 111}],
        "subtotal": 111, "total": 111, "country": "CI", "persist": True,
    })
    client.post("/api/auth/logout")

    uid2, token2 = _register("attacker@x.com")
    client.post("/api/validate", json={
        "items": [{"name": "Secret B", "quantity": 1, "unit_price": 222, "line_price": 222}],
        "subtotal": 222, "total": 222, "country": "CI", "persist": True,
    })

    # attaquant (connecté) essaie de lire le reçu #0 -> c'est le SIEN, pas celui de victim
    r = client.get("/api/receipt/0")
    assert r.status_code == 200
    assert r.json()["receipt"]["items"][0]["name"] == "Secret B"
    assert "Secret A" not in r.text

    # dashboard/comptabilité/bilan de l'attaquant ne mentionnent jamais victim
    for path in ["/api/dashboard", "/api/accounting?payment_mode=cash&country=CI", "/api/bilan"]:
        rr = client.get(path)
        assert "Secret A" not in rr.text


def test_idor_cookie_auth_vole_ne_donne_pas_acces_sans_le_bon_id():
    """Un jeton d'auth signé avec un user_id inexistant/différent ne doit
    jamais donner accès à des données -- vérifie que verify_token() seul ne
    suffit pas, il faut un compte réel derrière."""
    fake_token = auth.issue_token(999999)   # user_id qui n'existe pas
    client.cookies.set(auth.AUTH_COOKIE, fake_token)
    r = client.get("/api/dashboard")
    # soit 401 (session vide propre a cet id fictif), soit 200 avec un dashboard
    # vide -- jamais les donnees d'un autre compte reel
    assert r.status_code in (200, 401)
    if r.status_code == 200:
        assert r.json().get("empty", True) is True


def test_suppression_ne_supprime_pas_le_compte_dautrui():
    _register("keepme@x.com")
    client.post("/api/auth/logout")
    _register("deleteme@x.com")
    r = client.request("DELETE", "/api/auth/account", json={"password": "motdepasse123"})
    assert r.status_code == 200

    r2 = client.post("/api/auth/login", json={"email": "keepme@x.com", "password": "motdepasse123"})
    assert r2.status_code == 200   # toujours vivant


def test_export_dun_compte_ne_contient_jamais_les_donnees_dun_autre():
    _register("a@x.com")
    client.post("/api/auth/consent", json={"consent_type": "training_data", "granted": True})
    client.post("/api/validate", json={
        "items": [], "subtotal": 1, "total": 1, "country": "CI", "persist": True,
        "raw_json": {"total": 0}, "engine": "donut",
    })
    client.post("/api/auth/logout")

    _register("b@x.com")
    r = client.get("/api/auth/export")
    assert r.status_code == 200
    assert r.json()["account"]["email"] == "b@x.com"
    assert r.json()["corrections"] == []
    assert r.json()["receipts"] == []


# --- Contournement d'authentification ---------------------------------------

@pytest.mark.parametrize("path,method,body", [
    ("/api/dashboard", "get", None),
    ("/api/accounting", "get", None),
    ("/api/bilan", "get", None),
    ("/api/auth/me", "get", None),
    ("/api/auth/export", "get", None),
    ("/api/bilan/entry", "post", {"account": "101", "credit": 100}),
    ("/api/auth/consent", "get", None),
])
def test_endpoints_proteges_refusent_sans_cookie(path, method, body):
    client.cookies.clear()
    r = client.post(path, json=body) if method == "post" else client.get(path)
    assert r.status_code == 401


def test_cookie_auth_vide_refuse():
    client.cookies.set(auth.AUTH_COOKIE, "")
    r = client.get("/api/dashboard")
    assert r.status_code == 401


def test_cookie_auth_token_dun_autre_type_refuse():
    """Un cookie auth_token qui contient autre chose qu'un jeton signé
    (ex. le cookie de session anonyme sid, ou une chaîne arbitraire)."""
    for bogus in ["12345", "null", "{}", "' OR '1'='1", "a" * 5000]:
        client.cookies.set(auth.AUTH_COOKIE, bogus)
        r = client.get("/api/dashboard")
        assert r.status_code == 401


def test_verrouillage_login_ne_permet_pas_de_deviner_un_mot_de_passe():
    _register("brute@x.com")
    client.post("/api/auth/logout")
    for _ in range(auth.MAX_ATTEMPTS + 2):
        r = client.post("/api/auth/login", json={"email": "brute@x.com", "password": "essai-invalide"})
        assert r.status_code == 401
    # meme apres verrouillage, le bon mot de passe ne marche plus temporairement
    r = client.post("/api/auth/login", json={"email": "brute@x.com", "password": "motdepasse123"})
    assert r.status_code == 401


def test_mot_de_passe_demesure_rejete_avant_hachage_registration():
    """Empêche un candidat énorme de forcer un hachage argon2 coûteux (DoS)."""
    r = client.post("/api/auth/register",
                    json={"email": "dos@x.com", "password": "a" * (auth.MAX_PASSWORD_LENGTH + 1)})
    assert r.status_code == 422


def test_mot_de_passe_demesure_rejete_avant_verification_login():
    """Même protection côté connexion : un mot de passe légitime existe déjà,
    un candidat énorme sur CE compte ne doit jamais déclencher verify_password."""
    _register("dos2@x.com")
    client.post("/api/auth/logout")
    r = client.post("/api/auth/login",
                    json={"email": "dos2@x.com", "password": "a" * (auth.MAX_PASSWORD_LENGTH + 1)})
    assert r.status_code == 401
    # ne consomme pas le compteur anti brute-force (rejeté avant meme la verification)
    assert not auth._too_many_attempts("dos2@x.com")
