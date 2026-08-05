"""Robustesse face à des données erronées/adverses sur les endpoints
principaux. Règle unique vérifiée partout : JAMAIS de 500 (trace Python
exposée), toujours une réponse structurée -- même philosophie que le
décorateur @safe déjà en place. Base en mémoire, lifespan non déclenché."""
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


def _no_500(r):
    assert r.status_code != 500, f"500 renvoyé : {r.text[:500]}"
    return r


# --- Auth : entrées adverses -------------------------------------------------

@pytest.mark.parametrize("email", [
    "", None, "pas-un-email", "a" * 5000 + "@x.com", "a@" + "b" * 5000,
    "<script>alert(1)</script>@x.com", "'; DROP TABLE users; --@x.com",
    "a@x.com\x00", "ADMIN@X.COM", "  a@x.com  ", 12345, ["a@x.com"], {"e": "a@x.com"},
])
def test_register_email_adversarial(email):
    r = _no_500(client.post("/api/auth/register", json={"email": email, "password": "motdepasse123"}))
    assert r.status_code in (200, 422)


@pytest.mark.parametrize("password", [
    "", None, "a", "a" * 1_000_000, "🔥" * 1000, "\x00\x01\x02",
    12345, ["password"], {"p": "x"}, "motdepasse123' OR '1'='1",
])
def test_register_password_adversarial(password):
    r = _no_500(client.post("/api/auth/register", json={"email": "adv@x.com", "password": password}))
    assert r.status_code in (200, 422)


def test_login_champs_manquants():
    _no_500(client.post("/api/auth/login", json={}))
    _no_500(client.post("/api/auth/login", json={"email": "a@x.com"}))
    _no_500(client.post("/api/auth/login", json=None))
    _no_500(client.post("/api/auth/login", data="pas du json"))


def test_login_injection_sqlite_dans_email():
    client.post("/api/auth/register", json={"email": "victim@x.com", "password": "motdepasse123"})
    payloads = [
        "victim@x.com' OR '1'='1", "victim@x.com'--", "' OR 1=1--",
        "victim@x.com\"; DROP TABLE users;--", "%' OR '1'='1",
    ]
    for p in payloads:
        r = _no_500(client.post("/api/auth/login", json={"email": p, "password": "nimportequoi"}))
        assert r.status_code == 401   # jamais un contournement
    # la table users doit toujours exister et fonctionner normalement ensuite
    r = client.post("/api/auth/login", json={"email": "victim@x.com", "password": "motdepasse123"})
    assert r.status_code == 200


# --- /api/validate : reçu adverse -------------------------------------------

def _validate(payload):
    return _no_500(client.post("/api/validate", json=payload))


def test_validate_items_types_incorrects():
    _validate({"items": "pas-une-liste", "persist": False})
    _validate({"items": [{"name": 12345, "quantity": "beaucoup", "unit_price": None, "line_price": "abc"}],
              "persist": False})
    _validate({"items": [{"name": "x", "quantity": -999999, "unit_price": -1, "line_price": -1}],
              "persist": False})
    _validate({"items": [{}], "persist": False})
    _validate({"items": [None], "persist": False})


def _raw_json_post(url, raw_body):
    """Envoie un corps JSON écrit à la main (httpx refuse de sérialiser
    Infinity/NaN via json=, mais un vrai attaquant n'est pas limité par notre
    propre client de test -- json.loads standard les accepte par défaut)."""
    return _no_500(client.post(url, content=raw_body, headers={"Content-Type": "application/json"}))


def test_validate_montants_extremes():
    _validate({"items": [], "subtotal": 1e308, "tax": 1e308, "total": 1e308, "persist": False})
    _validate({"items": [], "subtotal": -1000000, "total": -1000000, "persist": False})
    _raw_json_post("/api/validate", '{"items": [], "subtotal": Infinity, "total": Infinity, "persist": false}')
    _raw_json_post("/api/validate", '{"items": [], "subtotal": NaN, "total": 100, "persist": false}')


def test_validate_chaines_extremes_et_unicode():
    _validate({"items": [{"name": "🧾" * 10000, "line_price": 1}], "persist": False})
    _validate({"items": [{"name": "<script>alert(1)</script>", "line_price": 1}], "persist": False})
    _validate({"items": [{"name": "a" * 1_000_000, "line_price": 1}], "persist": False})
    _validate({"items": [], "merchant": "'; DROP TABLE receipts; --", "persist": False,
              "country": "CI", "total": 100})


def test_validate_liste_items_geante():
    huge = [{"name": f"item{i}", "quantity": 1, "unit_price": 1, "line_price": 1} for i in range(5000)]
    r = _validate({"items": huge, "persist": False})
    assert r.status_code in (200, 422)


def test_validate_country_et_payment_mode_invalides():
    _validate({"items": [], "country": "XX", "total": 100, "persist": False})
    _validate({"items": [], "payment_mode": "bitcoin", "total": 100, "persist": False})
    _validate({"items": [], "payment_mode": None, "total": 100, "persist": False})
    _validate({"items": [], "doc_type": "<script>", "total": 100, "persist": False})


def test_validate_account_overrides_adversarial():
    _validate({"items": [{"name": "x", "line_price": 100}], "total": 100,
              "account_overrides": {"0": "'; DROP TABLE receipts;--"}, "persist": False})
    _validate({"items": [{"name": "x", "line_price": 100}], "total": 100,
              "account_overrides": {"index-invalide": "601", "-1": "601", "99999": "601"},
              "persist": False})
    _validate({"items": [], "total": 100, "account_overrides": "pas-un-dict", "persist": False})


def test_validate_corps_completement_absent_ou_invalide():
    _no_500(client.post("/api/validate", data="pas du json", headers={"Content-Type": "application/json"}))
    _no_500(client.post("/api/validate", json=None))
    _no_500(client.post("/api/validate", json=[]))
    _no_500(client.post("/api/validate", json="chaine"))
    _no_500(client.post("/api/validate", json=12345))


# --- /api/receipt/{id} : id adverse -----------------------------------------

@pytest.mark.parametrize("rid", ["abc", "-1", "99999999999999999999999999", "1.5", "1;DROP TABLE receipts", "%00"])
def test_receipt_id_adversarial(rid):
    _no_500(client.get(f"/api/receipt/{rid}"))
    _no_500(client.put(f"/api/receipt/{rid}", json={"items": [], "persist": True}))
    _no_500(client.delete(f"/api/receipt/{rid}"))


# --- /api/bilan/entry : écriture adverse ------------------------------------

def test_bilan_entry_adversarial():
    client.post("/api/auth/register", json={"email": "bilanadv@x.com", "password": "motdepasse123"})
    _no_500(client.post("/api/bilan/entry", json={"account": "", "debit": 100}))
    _no_500(client.post("/api/bilan/entry", json={"account": "1" * 10000, "debit": 100}))
    _raw_json_post("/api/bilan/entry", '{"account": "101", "debit": Infinity}')
    _no_500(client.post("/api/bilan/entry", json={"account": "101", "debit": -1000000, "credit": -1000000}))
    _no_500(client.post("/api/bilan/entry", json={"account": "'; DROP TABLE ledger_entries;--", "debit": 1}))
    _no_500(client.post("/api/bilan/entry", json={"account": "<script>alert(1)</script>", "credit": 1}))
    # la table doit toujours fonctionner ensuite
    r = client.post("/api/bilan/entry", json={"account": "101", "credit": 100})
    assert r.status_code == 200


def test_bilan_entry_types_incorrects():
    client.post("/api/auth/register", json={"email": "bilanadv2@x.com", "password": "motdepasse123"})
    _no_500(client.post("/api/bilan/entry", json={"account": 12345, "debit": "cent"}))
    _no_500(client.post("/api/bilan/entry", json={"account": None, "debit": 100}))
    _no_500(client.post("/api/bilan/entry", json={}))


# --- /api/search : question adverse -----------------------------------------

def test_search_adversarial():
    _no_500(client.post("/api/search", json={"question": ""}))
    _no_500(client.post("/api/search", json={"question": "a" * 100000}))
    _no_500(client.post("/api/search", json={"question": "'; DROP TABLE receipts;--"}))
    _no_500(client.post("/api/search", json={"question": None}))
    _no_500(client.post("/api/search", json={}))


# --- /api/settings/apikey : cle adverse --------------------------------------

def test_settings_apikey_adversarial():
    _no_500(client.post("/api/settings/apikey", json={"provider": "groq", "key": "a" * 100000}))
    _no_500(client.post("/api/settings/apikey", json={"provider": "'; DROP TABLE users;--", "key": "x"}))
    _no_500(client.post("/api/settings/apikey", json={"provider": "inconnu", "key": "x"}))
    _no_500(client.post("/api/settings/apikey", json={}))
