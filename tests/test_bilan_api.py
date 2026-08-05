"""Endpoints /api/bilan, /api/bilan/import, /api/bilan/entry,
/api/bilan/entries (api.py). Base en mémoire, lifespan non déclenché."""
import io

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

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


def _xlsx_bytes(rows):
    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_bilan_vide_anonyme():
    r = client.get("/api/bilan")
    assert r.status_code == 200
    body = r.json()
    assert body["total_actif"] == 0
    assert body["balanced"] is True
    assert body["has_imported_entries"] is False


def test_bilan_reflete_les_recus_sans_compte():
    client.post("/api/validate", json={
        "items": [{"name": "Café", "quantity": 1, "unit_price": 1000, "line_price": 1000}],
        "subtotal": 1000, "total": 1000, "country": "CI", "persist": True,
    })
    r = client.get("/api/bilan")
    assert r.status_code == 200
    body = r.json()
    assert body["total_charges"] == 1000
    assert body["balanced"] is True   # le resultat (perte) equilibre toujours


def test_import_sans_connexion_refuse():
    files = {"file": ("bilan.xlsx", _xlsx_bytes([["Compte", "Debit", "Credit"], ["101", "", "1000"]]), "application/octet-stream")}
    r = client.post("/api/bilan/import", files=files)
    assert r.status_code == 401


def test_import_puis_bilan_les_reflete():
    client.post("/api/auth/register", json={"email": "imp@x.com", "password": "motdepasse123"})
    files = {"file": ("bilan.xlsx", _xlsx_bytes([
        ["Compte", "Libellé", "Débit", "Crédit"],
        ["101", "Capital", "", "100000"],
        ["521", "Banque", "100000", ""],
    ]), "application/octet-stream")}
    r = client.post("/api/bilan/import", files=files)
    assert r.status_code == 200
    body = r.json()
    assert body["imported"] == 2
    assert body["skipped"] == 0
    assert body["balanced"] is True

    b = client.get("/api/bilan")
    assert b.status_code == 200
    bilan = b.json()
    assert bilan["has_imported_entries"] is True
    assert bilan["total_actif"] == 100000
    assert bilan["total_passif"] == 100000


def test_import_fichier_mal_forme_signale_sans_planter():
    files = {"file": ("bilan.xlsx", _xlsx_bytes([["Foo", "Bar"], ["1", "2"]]), "application/octet-stream")}
    client.post("/api/auth/register", json={"email": "bad@x.com", "password": "motdepasse123"})
    r = client.post("/api/bilan/import", files=files)
    assert r.status_code == 422
    assert r.json()["success"] is False


def test_import_partiel_signale_les_lignes_ignorees():
    client.post("/api/auth/register", json={"email": "part@x.com", "password": "motdepasse123"})
    files = {"file": ("bilan.xlsx", _xlsx_bytes([
        ["Compte", "Debit", "Credit"],
        ["", "500", ""],       # compte manquant -> ignoree
        ["601", "1000", ""],
    ]), "application/octet-stream")}
    r = client.post("/api/bilan/import", files=files)
    assert r.status_code == 200
    body = r.json()
    assert body["imported"] == 1
    assert body["skipped"] == 1
    assert len(body["errors"]) == 1


def test_saisie_manuelle_entree_bilan():
    client.post("/api/auth/register", json={"email": "manual@x.com", "password": "motdepasse123"})
    r = client.post("/api/bilan/entry", json={"account": "101", "label": "Capital", "credit": 5000})
    assert r.status_code == 200
    b = client.get("/api/bilan")
    accounts = {l["account"] for l in b.json()["passif"]}
    assert "101" in accounts


def test_saisie_manuelle_debit_et_credit_nuls_refusee():
    client.post("/api/auth/register", json={"email": "zero@x.com", "password": "motdepasse123"})
    r = client.post("/api/bilan/entry", json={"account": "101"})
    assert r.status_code == 422


def test_effacement_des_ecritures_importees():
    client.post("/api/auth/register", json={"email": "clear@x.com", "password": "motdepasse123"})
    client.post("/api/bilan/entry", json={"account": "101", "credit": 1000})
    r = client.request("DELETE", "/api/bilan/entries")
    assert r.status_code == 200
    assert r.json()["deleted"] == 1
    b = client.get("/api/bilan")
    assert b.json()["has_imported_entries"] is False


def test_ecritures_isolees_par_compte():
    client.post("/api/auth/register", json={"email": "iso1@x.com", "password": "motdepasse123"})
    client.post("/api/bilan/entry", json={"account": "101", "credit": 1000})
    client.post("/api/auth/logout")

    client.post("/api/auth/register", json={"email": "iso2@x.com", "password": "motdepasse123"})
    b = client.get("/api/bilan")
    assert b.json()["has_imported_entries"] is False


def test_suppression_compte_purge_les_ecritures_de_bilan():
    r0 = client.post("/api/auth/register", json={"email": "del@x.com", "password": "motdepasse123"})
    client.post("/api/bilan/entry", json={"account": "101", "credit": 1000})
    r = client.request("DELETE", "/api/auth/account", json={"password": "motdepasse123"})
    assert r.status_code == 200
    with db.get_db() as s:
        from src.models import LedgerEntry
        assert s.query(LedgerEntry).count() == 0
