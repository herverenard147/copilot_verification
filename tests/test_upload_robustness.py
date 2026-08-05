"""Robustesse des uploads (/api/extract, /api/bilan/import) face à des
fichiers adverses : trop gros, corrompus, vides, mal nommés. Jamais de 500."""
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

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


# --- /api/extract ------------------------------------------------------------

def test_extract_fichier_vide():
    r = _no_500(client.post("/api/extract", files={"file": ("x.jpg", b"", "image/jpeg")}))
    assert r.status_code == 422


def test_extract_octets_aleatoires_pas_une_image():
    r = _no_500(client.post("/api/extract", files={"file": ("x.jpg", b"\x00\x01\x02" * 1000, "image/jpeg")}))
    assert r.status_code == 422


def test_extract_image_tronquee():
    img = Image.new("RGB", (2000, 2000), color="red")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    truncated = buf.getvalue()[: len(buf.getvalue()) // 2]
    r = _no_500(client.post("/api/extract", files={"file": ("x.jpg", truncated, "image/jpeg")}))
    assert r.status_code == 422


def test_extract_fichier_trop_volumineux():
    huge = b"\xff\xd8\xff" + b"0" * (api.MAX_UPLOAD_BYTES + 1024)
    r = _no_500(client.post("/api/extract", files={"file": ("x.jpg", huge, "image/jpeg")}))
    assert r.status_code == 422
    assert "volumineux" in r.json()["error"].lower()


def test_extract_extension_mensongere_contenu_valide():
    """Extension .txt mais vrai contenu JPEG -> doit être lu comme une image
    (l'extension du nom de fichier n'est jamais fiable, seul le contenu
    compte). Image volontairement SOUS le seuil de résolution : le rejet est
    alors immédiat (garde-fou de résolution), sans déclencher une vraie
    inférence Donut (30-60s) juste pour prouver que l'extension est ignorée."""
    img = Image.new("RGB", (400, 300), color="blue")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    r = _no_500(client.post("/api/extract", files={"file": ("recu.txt", buf.getvalue(), "text/plain")}))
    assert r.status_code == 422
    assert "résolution" in r.json()["error"].lower()   # rejeté pour le contenu, pas le nom


def test_extract_nom_de_fichier_adverse():
    img = Image.new("RGB", (400, 300), color="green")   # sous le seuil : rejet rapide, pas d'inference
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    for name in ["../../etc/passwd.jpg", "a" * 5000 + ".jpg", "<script>.jpg", "récu 🧾.jpg", ""]:
        _no_500(client.post("/api/extract", files={"file": (name, buf.getvalue(), "image/jpeg")}))


def test_extract_image_1x1_sous_le_seuil_de_resolution():
    img = Image.new("RGB", (1, 1), color="red")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    r = _no_500(client.post("/api/extract", files={"file": ("x.png", buf.getvalue(), "image/png")}))
    assert r.status_code == 422
    assert "résolution" in r.json()["error"].lower()


# --- /api/bilan/import --------------------------------------------------------

def _login():
    client.post("/api/auth/register", json={"email": "upload@x.com", "password": "motdepasse123"})


def test_import_fichier_vide():
    _login()
    r = _no_500(client.post("/api/bilan/import", files={"file": ("j.csv", b"", "text/csv")}))
    assert r.status_code == 422


def test_import_fichier_trop_volumineux():
    _login()
    huge = ("Compte,Debit,Credit\n" + "601,1,\n" * 10).encode() + b"#" * (api.MAX_UPLOAD_BYTES + 1024)
    r = _no_500(client.post("/api/bilan/import", files={"file": ("j.csv", huge, "text/csv")}))
    assert r.status_code == 422
    assert "volumineux" in r.json()["error"].lower()


def test_import_extension_inconnue():
    _login()
    r = _no_500(client.post("/api/bilan/import", files={"file": ("bilan.pdf", b"%PDF-1.4", "application/pdf")}))
    assert r.status_code == 422


def test_import_csv_deguise_en_xlsx():
    """Extension .xlsx mais contenu texte brut (pas un vrai zip) -> doit
    échouer proprement, pas planter openpyxl."""
    _login()
    r = _no_500(client.post("/api/bilan/import",
                            files={"file": ("bilan.xlsx", b"Compte,Debit,Credit\n601,1,\n", "text/csv")}))
    assert r.status_code == 422


def test_import_nom_de_fichier_adverse():
    _login()
    csv = b"Compte,Debit,Credit\n601,100,\n"
    for name in ["../../etc/passwd.csv", "a" * 5000 + ".csv", "<script>.csv", ""]:
        _no_500(client.post("/api/bilan/import", files={"file": (name, csv, "text/csv")}))


def test_import_csv_sans_extension():
    _login()
    r = _no_500(client.post("/api/bilan/import", files={"file": ("bilan", b"Compte,Debit,Credit\n601,1,\n", "text/csv")}))
    assert r.status_code == 422   # format non reconnu, message clair, pas un crash
