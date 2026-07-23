"""Tests de l'API : aucun endpoint ne doit renvoyer un 500 avec traceback.
Lancer avec : pytest tests/ -q

Le chemin Donut est monkeypatche (pas de telechargement du modele en test) ;
les cas d'erreur (image invalide, fichier vide, PDF renomme) s'arretent AVANT
Donut de toute facon."""
import io

from fastapi.testclient import TestClient
from PIL import Image

import api

# raise_server_exceptions=False : si une erreur passait entre les mailles, le
# test verrait la reponse (jamais une exception) -- c'est justement ce qu'on garantit.
client = TestClient(api.app, raise_server_exceptions=False)


def png_bytes():
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (210, 210, 210)).save(buf, "PNG")
    return buf.getvalue()


def test_extract_image_valide_200(monkeypatch):
    # Donut simule : renvoie un JSON CORD exploitable, sans charger le vrai modele
    monkeypatch.setattr(api, "get_donut", lambda: (None, None, "cpu"))
    monkeypatch.setattr(api, "extract",
                        lambda *a, **k: {"menu": [{"nm": "Article", "price": "1000"}],
                                          "total": {"total_price": "1000"}})
    r = client.post("/api/extract",
                    files={"file": ("recu.png", png_bytes(), "image/png")},
                    data={"country": "ID", "payment_mode": "cash"})
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["engine"] in ("donut", "llm_fallback")
    assert "audit" in body and "journal" in body


def test_extract_pas_une_image():
    r = client.post("/api/extract",
                    files={"file": ("faux.jpg", b"ceci n'est pas une image", "image/jpeg")},
                    data={"country": "ID"})
    assert r.status_code != 500
    body = r.json()
    assert body["success"] is False
    assert body["error"] and body["detail"]
    assert isinstance(body["suggestions"], list) and body["suggestions"]


def test_extract_fichier_vide():
    r = client.post("/api/extract",
                    files={"file": ("vide.jpg", b"", "image/jpeg")},
                    data={"country": "ID"})
    assert r.status_code != 500
    body = r.json()
    assert body["success"] is False
    assert "vide" in (body["error"] + body["detail"]).lower()


def test_extract_pdf_renomme_en_jpg():
    fake_pdf = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"
    r = client.post("/api/extract",
                    files={"file": ("doc.jpg", fake_pdf, "image/jpeg")},
                    data={"country": "ID"})
    assert r.status_code != 500
    body = r.json()
    assert body["success"] is False
    assert isinstance(body["suggestions"], list)


def test_endpoints_lecture_ne_plantent_pas():
    # Dashboard / technical / config lisent les CSV reels, sans Donut
    for path in ("/api/config", "/api/dashboard", "/api/technical"):
        r = client.get(path)
        assert r.status_code == 200, path
        assert r.json()["success"] is True
