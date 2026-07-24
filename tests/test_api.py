"""Tests de l'API : aucun endpoint ne doit renvoyer un 500 avec traceback.
Lancer avec : pytest tests/ -q

Le chemin Donut est monkeypatche (pas de telechargement du modele en test) ;
les cas d'erreur (image invalide, fichier vide, PDF renomme) s'arretent AVANT
Donut de toute facon."""
import io
import pathlib

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import api
import src.llm as llm
from src import session_store
from src.llm import VisionUnavailable

# raise_server_exceptions=False : si une erreur passait entre les mailles, le
# test verrait la reponse (jamais une exception) -- c'est justement ce qu'on garantit.
client = TestClient(api.app, raise_server_exceptions=False)

VALID_KEY = "gsk_test_key_1234567890"     # forme plausible, jamais envoyee a Groq


@pytest.fixture(autouse=True)
def _reset_sessions():
    """Chaque test part d'un registre de sessions vierge (global de module)."""
    session_store.reset_all()
    yield
    session_store.reset_all()


@pytest.fixture
def clean_keys(monkeypatch):
    """Isole les tests de cles : aucune variable d'env, memoire de session vide
    avant ET apres (le stockage est un global de module qui persiste sinon)."""
    for var in ("GROQ_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    llm._session_keys.clear()
    yield
    llm._session_keys.clear()


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


# ---------------------------------------------------------------------------
# Reglages : cles API (memoire seule, jamais renvoyees ni ecrites sur disque)
# ---------------------------------------------------------------------------
def test_apikey_post_puis_status_session(clean_keys):
    r = client.post("/api/settings/apikey", json={"provider": "groq", "key": VALID_KEY})
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True and body["source"] == "session"
    assert VALID_KEY not in r.text            # la valeur n'est JAMAIS renvoyee

    st = client.get("/api/settings/status")
    assert st.status_code == 200
    assert st.json()["groq"] == {"source": "session", "configured": True}
    assert VALID_KEY not in st.text           # ni dans le status


def test_apikey_delete_puis_status_none(clean_keys):
    client.post("/api/settings/apikey", json={"provider": "groq", "key": VALID_KEY})
    r = client.delete("/api/settings/apikey?provider=groq")
    assert r.status_code == 200
    assert client.get("/api/settings/status").json()["groq"] == {"source": "none", "configured": False}


def test_env_prioritaire_et_post_ne_lecrase_pas(clean_keys, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_env_key_abcdefgh")
    assert client.get("/api/settings/status").json()["groq"]["source"] == "env"

    r = client.post("/api/settings/apikey", json={"provider": "groq", "key": "gsk_session_override_x"})
    assert r.status_code == 200
    assert r.json()["source"] == "env"        # non ecrasee

    # une fois l'env retiree, rien n'a ete stocke en session
    monkeypatch.delenv("GROQ_API_KEY")
    assert client.get("/api/settings/status").json()["groq"]["source"] == "none"


def test_apikey_vide_ou_malformee_erreur_propre(clean_keys):
    for bad in ("", "   ", "short", "cle avec des espaces"):
        r = client.post("/api/settings/apikey", json={"provider": "groq", "key": bad})
        assert r.status_code != 500
        assert r.json()["success"] is False
    assert client.get("/api/settings/status").json()["groq"]["source"] == "none"


def test_test_endpoint_sans_cle_ne_plante_pas(clean_keys):
    r = client.post("/api/settings/test", json={"provider": "groq"})
    assert r.status_code != 500
    assert r.json()["success"] is False       # aucune cle -> echec propre, pas d'appel reseau


def test_apikey_ne_cree_aucun_fichier(clean_keys):
    root, data = pathlib.Path("."), pathlib.Path("data")
    before_root = {p.name for p in root.iterdir()}
    before_data = {p.name for p in data.iterdir()}

    client.post("/api/settings/apikey", json={"provider": "groq", "key": VALID_KEY})
    client.get("/api/settings/status")
    client.delete("/api/settings/apikey?provider=groq")

    assert {p.name for p in root.iterdir()} == before_root
    assert {p.name for p in data.iterdir()} == before_data


# ---------------------------------------------------------------------------
# Cloisonnement par session : donnees utilisateur vs corpus de reference CORD
# ---------------------------------------------------------------------------
def test_dashboard_session_neuve_compteurs_a_zero():
    r = client.get("/api/dashboard", headers={"X-Session-Id": "neuve"})
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True and body["empty"] is True and body["demo_mode"] is False


def test_validate_ajoute_le_recu_a_cette_session():
    sid = {"X-Session-Id": "avec-recu"}
    payload = {"items": [{"name": "Café", "line_price": 1500}], "subtotal": 1500,
               "tax": None, "total": 1500, "category": "food",
               "country": "ID", "payment_mode": "cash", "persist": True}
    v = client.post("/api/validate", json=payload, headers=sid)
    assert v.status_code == 200 and v.json()["persisted"] is True

    d = client.get("/api/dashboard", headers=sid).json()
    assert d["empty"] is False
    assert d["kpis"]["n_receipts"] == 1


def test_deux_sessions_sont_isolees():
    a, b = {"X-Session-Id": "sess-A"}, {"X-Session-Id": "sess-B"}
    payload = {"items": [], "subtotal": 1000, "tax": None, "total": 1000,
               "category": "food", "country": "ID", "persist": True}
    client.post("/api/validate", json=payload, headers=a)

    da = client.get("/api/dashboard", headers=a).json()
    db = client.get("/api/dashboard", headers=b).json()
    assert da["empty"] is False and da["kpis"]["n_receipts"] == 1
    assert db["empty"] is True     # aucune fuite de A vers B


def test_mode_demo_charge_cord_et_leve_le_drapeau():
    sid = {"X-Session-Id": "demo"}
    r = client.post("/api/settings/demo", json={"enabled": True}, headers=sid)
    assert r.status_code == 200
    body = r.json()
    assert body["demo_mode"] is True and body["n_receipts"] > 100   # corpus CORD

    d = client.get("/api/dashboard", headers=sid).json()
    assert d["empty"] is False and d["demo_mode"] is True
    assert d["kpis"]["n_receipts"] > 100


def test_delete_session_revient_a_vide():
    sid = {"X-Session-Id": "a-vider"}
    client.post("/api/settings/demo", json={"enabled": True}, headers=sid)
    r = client.delete("/api/session", headers=sid)
    assert r.status_code == 200 and r.json()["empty"] is True

    d = client.get("/api/dashboard", headers=sid).json()
    assert d["empty"] is True and d["demo_mode"] is False


def test_technical_inchange_quelle_que_soit_la_session():
    r1 = client.get("/api/technical", headers={"X-Session-Id": "t-vide"}).json()
    client.post("/api/settings/demo", json={"enabled": True}, headers={"X-Session-Id": "t-demo"})
    r2 = client.get("/api/technical", headers={"X-Session-Id": "t-demo"}).json()
    assert r1["success"] and r2["success"]
    assert r1["results"] == r2["results"]      # donnees d'EVALUATION, jamais de la session
    assert any("Donut" in str(row.get("modele", "")) for row in r1["results"])


# ---------------------------------------------------------------------------
# Fallback vision : cle valide mais aucun modele vision -> degradation propre
# ---------------------------------------------------------------------------
def test_extract_sans_modele_vision_ne_plante_pas(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_env_key_abcdefgh")   # cle presente
    monkeypatch.setattr(api, "get_donut", lambda: (None, None, "cpu"))
    monkeypatch.setattr(api, "extract", lambda *a, **k: {})       # Donut vide (hors domaine)

    def _no_vision(*a, **k):
        raise VisionUnavailable("aucun modele vision accessible")
    monkeypatch.setattr(api, "extract_receipt_via_vision", _no_vision)

    r = client.post("/api/extract",
                    files={"file": ("recu.png", png_bytes(), "image/png")},
                    data={"country": "CI", "payment_mode": "cash"},
                    headers={"X-Session-Id": "vision"})
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["engine"] == "fallback_indisponible"            # engine indique l'indisponibilite
    assert "indisponible" in (body.get("fallback_note") or "").lower()
