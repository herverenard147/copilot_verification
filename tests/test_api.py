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
    """Chaque test part d'un registre de sessions vierge (global de module).
    On coupe aussi la persistance : aucun fichier .local_state pendant les tests."""
    session_store.reset_all()
    session_store.disable_persistence()
    yield
    session_store.reset_all()
    session_store.disable_persistence()


@pytest.fixture
def clean_keys(monkeypatch):
    """Isole les tests de cles : aucune variable d'env, memoire de session vide
    avant ET apres (le stockage est un global de module qui persiste sinon)."""
    for var in ("GROQ_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    llm._session_keys.clear()
    yield
    llm._session_keys.clear()


def png_bytes(size=(700, 500)):
    """Image au-dessus du seuil de resolution par defaut (~0.25 Mpx)."""
    buf = io.BytesIO()
    Image.new("RGB", size, (210, 210, 210)).save(buf, "PNG")
    return buf.getvalue()


# Menu Donut RÉEL sur la facture française (test_images/06_facture_francaise_design.webp)
_FACTURE_MENU = {"menu": [
    {"nm": "Facture n 12345"}, {"nm": "CELIA NAUDIN"}, {"nm": "hello@reallygreatsite.com"},
    {"nm": "123 Anywhere St., Any City DESCRIPTION PRX", "price": "900"},
    {"nm": "Creation de logo", "price": "900"}, {"nm": "Conception d'un flyer", "price": "300"},
    {"nm": "Carte de visite", "price": "900"}, {"nm": "Illustration personalisee", "price": "1500"},
    {"nm": "Banniere publicitaire", "price": "250"},
]}


def test_extract_mode_facture_filtre_les_entetes(monkeypatch):
    monkeypatch.setattr(api, "get_donut", lambda: (None, None, "cpu"))
    monkeypatch.setattr(api, "extract", lambda *a, **k: _FACTURE_MENU)
    r = client.post("/api/extract", files={"file": ("f.png", png_bytes(), "image/png")},
                    data={"country": "ID", "doc_type": "facture"}, headers={"X-Session-Id": "fac"})
    assert r.status_code == 200
    body = r.json()
    names = [it["name"] for it in body["receipt"]["items"]]
    assert "CELIA NAUDIN" not in names and "hello@reallygreatsite.com" not in names
    assert "Facture n 12345" not in names
    assert "Creation de logo" in names            # vrais articles conservés
    assert body["doc_type"] == "facture"


def test_extract_mode_ticket_ne_change_rien(monkeypatch):
    """Mode ticket = comportement identique à avant : aucun item retiré."""
    monkeypatch.setattr(api, "get_donut", lambda: (None, None, "cpu"))
    monkeypatch.setattr(api, "extract", lambda *a, **k: _FACTURE_MENU)
    r = client.post("/api/extract", files={"file": ("f.png", png_bytes(), "image/png")},
                    data={"country": "ID", "doc_type": "ticket"}, headers={"X-Session-Id": "tic"})
    body = r.json()
    names = [it["name"] for it in body["receipt"]["items"]]
    assert "CELIA NAUDIN" in names and len(names) == 9   # TOUS conservés
    assert body["doc_type"] == "ticket"


def test_extract_facture_trouve_le_numero(monkeypatch):
    monkeypatch.setattr(api, "get_donut", lambda: (None, None, "cpu"))
    monkeypatch.setattr(api, "extract", lambda *a, **k: _FACTURE_MENU)
    r = client.post("/api/extract", files={"file": ("f.png", png_bytes(), "image/png")},
                    data={"country": "ID", "doc_type": "facture"}, headers={"X-Session-Id": "num"})
    assert r.json()["invoice_number"] == "12345"


def test_extract_ticket_ne_cherche_pas_de_numero(monkeypatch):
    monkeypatch.setattr(api, "get_donut", lambda: (None, None, "cpu"))
    monkeypatch.setattr(api, "extract", lambda *a, **k: _FACTURE_MENU)
    r = client.post("/api/extract", files={"file": ("f.png", png_bytes(), "image/png")},
                    data={"country": "ID", "doc_type": "ticket"}, headers={"X-Session-Id": "tic2"})
    assert r.json()["invoice_number"] is None


def test_facture_numero_conserve_dashboard_et_detail():
    """Le numero de facture est conserve dans le contexte et exposé partout."""
    sid = {"X-Session-Id": "lbl"}
    v = client.post("/api/validate", json={
        "items": [{"name": "Creation de logo", "line_price": 900}],
        "subtotal": 900, "total": 900, "category": "advertising", "country": "ID",
        "doc_type": "facture", "invoice_number": "12345", "persist": True}, headers=sid).json()
    assert v["doc_type"] == "facture" and v["invoice_number"] == "12345"

    rr = client.get("/api/dashboard", headers=sid).json()["receipts"][0]
    assert rr["doc_type"] == "facture" and rr["invoice_number"] == "12345"   # dashboard

    det = client.get(f"/api/receipt/{v['receipt_id']}?country=ID", headers=sid).json()
    assert det["doc_type"] == "facture" and det["invoice_number"] == "12345"  # détail


def test_update_receipt_recalcule_et_visible_partout():
    sid = {"X-Session-Id": "upd"}
    v = client.post("/api/validate", json={"items": [{"name": "x", "line_price": 1000}],
        "subtotal": 1000, "total": 1000, "category": "food", "country": "ID", "persist": True}, headers=sid).json()
    rid = v["receipt_id"]
    u = client.put(f"/api/receipt/{rid}", json={"items": [{"name": "x", "line_price": 5000}],
        "subtotal": 5000, "total": 5000, "category": "food", "country": "ID"}, headers=sid).json()
    assert u["updated"] is True and u["receipt"]["total"] == 5000
    assert client.get("/api/dashboard", headers=sid).json()["receipts"][0]["total"] == 5000  # visible


def test_delete_receipt_disparait_de_toutes_les_vues():
    sid = {"X-Session-Id": "del"}
    v = client.post("/api/validate", json={"items": [{"name": "UNIQUE", "line_price": 1000}],
        "subtotal": 1000, "total": 1000, "category": "food", "country": "ID", "persist": True}, headers=sid).json()
    rid = v["receipt_id"]
    assert client.delete(f"/api/receipt/{rid}", headers=sid).json()["deleted"] is True
    assert client.get("/api/dashboard", headers=sid).json()["empty"] is True          # dashboard
    assert client.get("/api/accounting", headers=sid).json()["empty"] is True          # journal/TVA
    assert client.get(f"/api/receipt/{rid}", headers=sid).json()["success"] is False   # plus de référence


def test_delete_receipt_introuvable_404_propre():
    r = client.delete("/api/receipt/999", headers={"X-Session-Id": "del2"})
    assert r.status_code != 500 and r.json()["success"] is False


def test_account_override_equilibre_manuel_et_persiste():
    sid = {"X-Session-Id": "ovr"}
    # food -> compte auto 601 ; on force 605
    v = client.post("/api/validate", json={"items": [{"name": "x", "line_price": 10000, "category": "food"}],
        "subtotal": 10000, "total": 10000, "category": "food", "country": "ID",
        "account_overrides": {"0": "605"}, "persist": True}, headers=sid).json()
    charge = [l for l in v["journal"] if l["debit"] > 0]
    assert charge[0]["account"] == "605" and charge[0].get("manual") is True
    assert v["balanced"] is True                                    # équilibre préservé
    # persistance : rechargé, garde 605 + drapeau manuel
    d = client.get(f"/api/receipt/{v['receipt_id']}?country=ID", headers=sid).json()
    dc = [l for l in d["journal"] if l["debit"] > 0]
    assert dc[0]["account"] == "605" and dc[0].get("manual") is True


def test_mapping_automatique_inchange():
    """La surcharge par reçu ne modifie PAS le mapping par défaut."""
    from src.accounting import map_category_to_account
    assert map_category_to_account("food") == "601"        # comportement par défaut intact


def test_extract_renvoie_une_miniature_redimensionnee(monkeypatch):
    monkeypatch.setattr(api, "get_donut", lambda: (None, None, "cpu"))
    monkeypatch.setattr(api, "extract",
                        lambda *a, **k: {"menu": [{"nm": "X", "price": "1000"}], "total": {"total_price": "1000"}})
    r = client.post("/api/extract", files={"file": ("r.png", png_bytes((2000, 1500)), "image/png")},
                    data={"country": "ID"}, headers={"X-Session-Id": "img"})
    b = r.json()
    assert b["image_data"].startswith("data:image/jpeg;base64,")
    import base64
    import io
    raw = base64.b64decode(b["image_data"].split(",", 1)[1])
    thumb = Image.open(io.BytesIO(raw))
    assert thumb.width <= 800                 # redimensionnée (2000 -> <=800)


def test_image_stockee_et_recuperable():
    sid = {"X-Session-Id": "imgstore"}
    du = "data:image/jpeg;base64,/9j/4AAQSkZJRg=="
    v = client.post("/api/validate", json={"items": [{"name": "x", "line_price": 1000}],
        "subtotal": 1000, "total": 1000, "category": "food", "country": "ID",
        "image_data": du, "persist": True}, headers=sid).json()
    d = client.get(f"/api/receipt/{v['receipt_id']}?country=ID", headers=sid).json()
    assert d["image_data"] == du              # stockée puis récupérable


def test_recu_sans_image_renvoie_none():
    sid = {"X-Session-Id": "noimg"}
    v = client.post("/api/validate", json={"items": [{"name": "x", "line_price": 1000}],
        "subtotal": 1000, "total": 1000, "category": "food", "country": "ID", "persist": True}, headers=sid).json()
    d = client.get(f"/api/receipt/{v['receipt_id']}?country=ID", headers=sid).json()
    assert d["image_data"] is None            # -> le front affiche l'espace réservé


def test_mode_demo_aucune_image_stockee():
    sid = {"X-Session-Id": "demoimg"}
    client.post("/api/settings/demo", json={"enabled": True}, headers=sid)
    d = client.get("/api/receipt/0?country=ID", headers=sid).json()
    assert d["image_data"] is None            # aucun stockage d'image CORD


def test_update_conserve_image_si_non_renvoyee():
    sid = {"X-Session-Id": "updimg"}
    du = "data:image/jpeg;base64,/9j/AAAA"
    v = client.post("/api/validate", json={"items": [{"name": "x", "line_price": 1000}],
        "subtotal": 1000, "total": 1000, "category": "food", "country": "ID",
        "image_data": du, "persist": True}, headers=sid).json()
    u = client.put(f"/api/receipt/{v['receipt_id']}", json={"items": [{"name": "x", "line_price": 2000}],
        "subtotal": 2000, "total": 2000, "category": "food", "country": "ID"}, headers=sid).json()
    assert u["image_data"] == du              # image conservée malgré la modif


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


def test_extract_image_trop_basse_resolution_rejetee(monkeypatch):
    """Garde-fou E10 : une image 100x100 est rejetee proprement, SANS tenter
    l'extraction (le modele ne doit pas halluciner sur du flou)."""
    def _boom():
        raise AssertionError("Donut ne doit pas etre appele sur une image rejetee")
    monkeypatch.setattr(api, "get_donut", _boom)
    monkeypatch.setattr(api, "extract",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("pas d'extraction")))

    r = client.post("/api/extract",
                    files={"file": ("vignette.png", png_bytes((100, 100)), "image/png")},
                    data={"country": "ID"})
    assert r.status_code != 500
    body = r.json()
    assert body["success"] is False
    assert "résolution" in (body["error"] + body["detail"]).lower()
    assert body["resolution"]["ok"] is False
    assert body["resolution"]["width"] == 100 and body["resolution"]["height"] == 100


def test_extract_image_modeste_non_bloquee(monkeypatch):
    """Une image legitimement modeste (800x600 ~0.48 Mpx) PASSE le garde-fou."""
    monkeypatch.setattr(api, "get_donut", lambda: (None, None, "cpu"))
    monkeypatch.setattr(api, "extract",
                        lambda *a, **k: {"menu": [{"nm": "Article", "price": "1000"}],
                                          "total": {"total_price": "1000"}})
    r = client.post("/api/extract",
                    files={"file": ("recu.png", png_bytes((800, 600)), "image/png")},
                    data={"country": "ID"})
    assert r.status_code == 200 and r.json()["success"] is True


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


def test_env_est_un_defaut_que_la_session_remplace(clean_keys, monkeypatch):
    """La cle de session l'emporte sur l'env (l'utilisateur garde la main) ;
    l'env sert de defaut quand aucune cle de session n'est configuree."""
    monkeypatch.setenv("GROQ_API_KEY", "gsk_env_key_abcdefgh")
    assert client.get("/api/settings/status").json()["groq"]["source"] == "env"

    # une cle saisie dans l'UI REMPLACE l'env (plus de verrou lecture seule)
    r = client.post("/api/settings/apikey", json={"provider": "groq", "key": "gsk_session_override_1"})
    assert r.status_code == 200 and r.json()["source"] == "session"
    assert client.get("/api/settings/status").json()["groq"]["source"] == "session"

    # « Effacer » retire la cle de session -> retour au defaut d'environnement
    client.delete("/api/settings/apikey?provider=groq")
    assert client.get("/api/settings/status").json()["groq"]["source"] == "env"


def test_apikey_changer_puis_effacer_puis_reconfigurer(clean_keys):
    """Regression du bug "clé non modifiable/effaçable" (sans env) :
    POST A -> DELETE -> POST B : le status reflete B, jamais A ni un etat bloque."""
    client.post("/api/settings/apikey", json={"provider": "groq", "key": "gsk_key_A_1234567890"})
    assert client.get("/api/settings/status").json()["groq"]["source"] == "session"

    assert client.delete("/api/settings/apikey?provider=groq").status_code == 200
    assert client.get("/api/settings/status").json()["groq"] == {"source": "none", "configured": False}

    client.post("/api/settings/apikey", json={"provider": "groq", "key": "gsk_key_B_1234567890"})
    st = client.get("/api/settings/status").json()["groq"]
    assert st == {"source": "session", "configured": True}   # reflete B, pas d'etat bloque


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


def test_accounting_expose_receipts_avec_motif_tva():
    """Chantier 2.3b : la compta expose une liste de reçus + motif TVA, pour
    filtrer par motif côté front."""
    sid = {"X-Session-Id": "compta"}
    payload = {"items": [{"name": "x", "line_price": 5000, "category": "food"}],
               "subtotal": 5000, "total": 5000, "category": "food",
               "country": "CI", "persist": True}
    client.post("/api/validate", json=payload, headers=sid)
    d = client.get("/api/accounting", headers=sid).json()
    assert d["empty"] is False
    assert isinstance(d["receipts"], list) and len(d["receipts"]) == 1
    r = d["receipts"][0]
    assert r["receipt_id"] == 0 and "identifi" in r["vat_reason"].lower()


def test_chip_taxe_coherent_dashboard_et_detail():
    """Non-régression : un reçu indonésien (TVA 11%) doit donner le MÊME verdict
    de chip taxe vu depuis le dashboard (flag stocké, ID) et depuis le détail
    (recalculé). Le défaut serveur ID garantit la cohérence ; l'ancien défaut
    CI (18%) produisait la contradiction."""
    sid = {"X-Session-Id": "coherence-tax"}
    payload = {"items": [{"name": "x", "line_price": 10000, "category": "food"}],
               "subtotal": 10000, "tax": 1100, "total": 11100, "category": "food",
               "country": "ID", "payment_mode": "cash", "persist": True}
    v = client.post("/api/validate", json=payload, headers=sid).json()
    stored = v["audit"]["tax_ok"]                       # ce que reflète le dashboard (ID)
    assert stored is True                               # 11% ~ seuil ID 11%

    # détail SANS country -> défaut serveur ID -> cohérent
    assert client.get("/api/receipt/0", headers=sid).json()["audit"]["tax_ok"] == stored
    # détail AVEC country=ID (ce que le front envoie en démo) -> cohérent
    assert client.get("/api/receipt/0?country=ID", headers=sid).json()["audit"]["tax_ok"] == stored
    # preuve du bug d'origine : CI (18%) se serait contredit
    assert client.get("/api/receipt/0?country=CI", headers=sid).json()["audit"]["tax_ok"] != stored


def test_recu_0_demo_ecriture_multi_comptes():
    """Reçu #0 du corpus CORD (démo) -> détail avec écriture multi-comptes."""
    sid = {"X-Session-Id": "demo-multi"}
    client.post("/api/settings/demo", json={"enabled": True}, headers=sid)
    d = client.get("/api/receipt/0?country=ID", headers=sid).json()
    charge = [l for l in d["journal"] if l["debit"] > 0]
    assert {"601", "605", "638"}.issubset({l["account"] for l in charge})
    assert d["balanced"] is True


def test_receipt_detail_multi_comptes_apres_validation():
    """Chantier 1+2 : un reçu validé multi-catégories -> détail à écriture
    multi-comptes (cohérence entre validation et détail persisté)."""
    sid = {"X-Session-Id": "multi2"}
    payload = {"items": [{"name": "papier", "line_price": 30000, "category": "supplies"},
                         {"name": "taxi", "line_price": 20000, "category": "transport"}],
               "subtotal": 50000, "total": 50000, "category": "supplies",
               "country": "CI", "persist": True}
    client.post("/api/validate", json=payload, headers=sid)
    d = client.get("/api/receipt/0", headers=sid).json()
    charge = [l for l in d["journal"] if l["debit"] > 0]
    assert {l["account"] for l in charge} == {"605", "6181"}   # 2 comptes distincts
    assert d["balanced"] is True


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
