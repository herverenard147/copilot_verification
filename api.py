"""API FastAPI du Copilote de recus.

Endpoints MINCES : ils appellent le backend existant (src/) et renvoient du
JSON. Aucune logique metier n'est reecrite ici -- extraction (Donut), regles,
comptabilite, recherche vivent dans src/. L'API ne fait qu'exposer, orchestrer
le fallback vision, et servir le front statique de web/.

Lancer :  uvicorn api:app --reload
"""
import functools
import io
import logging
import math
import os
from pathlib import Path
from uuid import uuid4

import numpy as np
import pandas as pd
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel

logger = logging.getLogger("copilote.api")

from src.receipt import Receipt
from src.rules import audit, TAX_RATES
from src.accounting import (
    journal_entry, is_balanced, vat_recoverable, vat_summary, expense_report,
    DISCLAIMER, CHART_OF_ACCOUNTS, PAYMENT_ACCOUNTS,
)
from src.preprocess import preprocess_image
from src.extractor import extract
from src.llm import (
    extract_receipt_via_vision, VisionUnavailable,
    resolve_key, key_source, set_session_key, clear_session_key,
    classify_models, select_vision_model,
)
from src import session_store

DATA = Path("data")
WEB = Path("web")

app = FastAPI(title="Copilote de reçus — API")


# ---------------------------------------------------------------------------
# Identite de session (cookie httpOnly uuid4, ou header X-Session-Id).
# Aucune auth : une session anonyme suffit. Le jour ou l'auth arrive, on
# resout un user_id ici et session_store.get_session keye dessus -- rien
# d'autre a changer.
# ---------------------------------------------------------------------------
SESSION_COOKIE = "sid"


@app.middleware("http")
async def ensure_session(request: Request, call_next):
    # header prioritaire (clients API / tests), sinon cookie, sinon nouvel id
    sid = request.headers.get("x-session-id") or request.cookies.get(SESSION_COOKIE)
    fresh = None
    if not sid:
        sid = fresh = uuid4().hex
    request.state.sid = sid
    response = await call_next(request)
    if fresh:
        response.set_cookie(SESSION_COOKIE, fresh, httponly=True, samesite="lax")
    return response


def _session(request):
    """La session utilisateur courante (creee a la volee si besoin)."""
    return session_store.get_session(request.state.sid)


# ---------------------------------------------------------------------------
# Ressources lourdes en chargement PARESSEUX (jamais au demarrage)
# ---------------------------------------------------------------------------
_donut = None            # (processor, model, device)
_search = None           # (encoder, index, summaries)
_reference = None        # (receipts_ref, items_ref) — corpus CORD pour le mode demo


def get_donut():
    """Charge Donut (~800 Mo) une seule fois, au premier /api/extract."""
    global _donut
    if _donut is None:
        import torch
        from transformers import DonutProcessor, VisionEncoderDecoderModel
        name = "naver-clova-ix/donut-base-finetuned-cord-v2"
        processor = DonutProcessor.from_pretrained(name)
        model = VisionEncoderDecoderModel.from_pretrained(name)
        device = "cuda" if torch.cuda.is_available() else "cpu"
        _donut = (processor, model.to(device), device)
    return _donut


def get_search():
    """Construit l'index FAISS une fois. Renvoie (None, None, summaries) si
    FAISS / sentence-transformers indisponibles (degradation gracieuse)."""
    global _search
    if _search is None:
        summaries = _load_summaries()
        try:
            from src.semantic import get_encoder, embed, build_index
            encoder = get_encoder()
            index = build_index(embed(summaries, encoder))
            _search = (encoder, index, summaries)
        except Exception:
            _search = (None, None, summaries)
    return _search


# ---------------------------------------------------------------------------
# Donnees (CSV reels) + utilitaires JSON
# ---------------------------------------------------------------------------
def _load_summaries():
    try:
        import json
        with open(DATA / "summaries.json", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return []


def load_items():
    try:
        return pd.read_csv(DATA / "items.csv")
    except FileNotFoundError:
        return pd.DataFrame(columns=["receipt_id", "name", "quantity", "unit_price", "line_price", "category"])


def load_receipts():
    """Charge receipts.csv et enrichit d'une categorie dominante par recu
    (deduite de items.csv) si la colonne n'existe pas -- necessaire au mapping
    categorie -> compte de l'onglet Comptabilite."""
    try:
        receipts = pd.read_csv(DATA / "receipts.csv")
    except FileNotFoundError:
        return pd.DataFrame(columns=["receipt_id", "n_items", "items_sum", "subtotal",
                                      "tax", "total", "line_sum_ok", "total_ok",
                                      "tax_ok", "anomaly", "category"])
    if "category" not in receipts.columns:
        items = load_items()
        if "category" in items.columns:
            dominant = items.groupby("receipt_id")["category"].agg(
                lambda s: s.mode().iat[0] if not s.mode().empty else None)
            receipts = receipts.merge(dominant.rename("category"), on="receipt_id", how="left")
    return receipts


def reference_dataset():
    """Corpus de REFERENCE CORD (receipts + items enrichis), charge une fois.
    Sert au mode demonstration et au repli de recherche -- JAMAIS presente
    comme les depenses de l'utilisateur."""
    global _reference
    if _reference is None:
        receipts = to_jsonable(load_receipts().to_dict("records"))
        items = to_jsonable(load_items().to_dict("records"))
        _reference = (receipts, items)
    return _reference


def to_jsonable(obj):
    """Rend un objet serialisable en JSON STRICT : NaN/NaT -> null, types numpy
    -> types Python. Sans ca, le JSON contiendrait des tokens `NaN` invalides
    que le navigateur refuse de parser."""
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return to_jsonable(obj.tolist())
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        obj = float(obj)
    if isinstance(obj, float):
        return None if math.isnan(obj) else obj
    if obj is pd.NaT or (obj is not None and obj is pd.NA):
        return None
    return obj


def ok(payload):
    data = {"success": True}
    data.update(payload)
    return JSONResponse(to_jsonable(data))


def fail(error_msg, detail="", status=422, engine="donut", suggestions=None):
    """Erreur JSON propre et STRUCTUREE. Le message est humain et court ; le
    traceback complet part dans les logs serveur, JAMAIS dans la reponse HTTP.
    Statut != 500 : une image inattendue ne doit pas casser la demo."""
    return JSONResponse({
        "success": False,
        "error": error_msg,
        "detail": detail,
        "engine": engine,
        "suggestions": suggestions or ["Réessayer avec une photo plus nette",
                                        "Saisir les données manuellement"],
    }, status_code=status)


def safe(fn):
    """Enveloppe un endpoint : toute exception non prevue est journalisee
    (logging.exception) et transformee en JSON propre non-500. functools.wraps
    preserve la signature, donc FastAPI continue d'injecter les parametres."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception:
            logger.exception("Erreur non gérée dans %s", fn.__name__)
            return fail("Une erreur inattendue est survenue.",
                        detail="L'incident a été enregistré côté serveur. Réessayez.",
                        status=400, engine="server",
                        suggestions=["Réessayer", "Recharger la page"])
    return wrapper


def _nan(value):
    """Case CSV vide (NaN pandas) -> None (NaN est truthy et casse la logique
    a 3 etats des regles)."""
    return None if value is None or (isinstance(value, float) and math.isnan(value)) else value


def build_receipt_bundle(receipt, country, payment_mode, merchant, category=None):
    """audit + ecriture + TVA a partir d'un Receipt. Coeur partage par
    /api/extract et /api/validate."""
    flags = audit(receipt, country=country)
    try:
        entry = journal_entry(receipt, category=category, payment_mode=payment_mode,
                              country=country, merchant=merchant)
    except (ValueError, KeyError):
        entry = None
    # journal_entry renvoie [] pour un recu vide : on l'expose comme None pour
    # que le front affiche "écriture impossible" plutôt qu'un tableau vide.
    balanced = is_balanced(entry) if entry else None
    entry = entry or None
    recoverable, reason = vat_recoverable(receipt, merchant=merchant)
    return {
        "receipt": {
            "items": receipt.items,
            "subtotal": receipt.subtotal,
            "tax": receipt.tax,
            "total": receipt.total,
            "items_sum": receipt.items_sum(),
            "merchant": merchant,
        },
        "audit": flags,
        "journal": entry,
        "balanced": balanced,
        "vat": {"recoverable": recoverable, "reason": reason},
    }


# ---------------------------------------------------------------------------
# POST /api/extract
# ---------------------------------------------------------------------------
@app.post("/api/extract")
@safe
def api_extract(file: UploadFile = File(...), country: str = Form("CI"),
                payment_mode: str = Form("cash"), merchant: str = Form(None)):
    try:
        raw = file.file.read()
    except Exception:
        return fail("Fichier illisible.", detail="Le fichier n'a pas pu être lu.", status=422)
    if not raw:
        return fail("Fichier vide.",
                    detail="Le fichier reçu ne contient aucune donnée.", status=422)
    try:
        image = Image.open(io.BytesIO(raw))
        image.load()
    except Exception:
        logger.exception("Ouverture image échouée (%s octets)", len(raw))
        return fail("Impossible de lire ce reçu",
                    detail="Le fichier n'est pas une image valide (JPG ou PNG attendu).",
                    status=422)

    try:
        pre_img, pre_info = preprocess_image(image)
    except Exception:
        pre_img, pre_info = image.convert("RGB"), {"deskewed": False, "clahe": False}

    engine = "donut"
    fallback_note = None

    # 1) Donut (son domaine : reçus indonesiens CORD)
    try:
        processor, model, device = get_donut()
        prediction = extract(pre_img, model, processor, device)
    except Exception:
        prediction = {}
        fallback_note = "Donut indisponible (modèle non chargé)."
    receipt = Receipt.from_gt_parse(prediction)

    # 2) Fallback vision ASSUME : pays CI (hors domaine) OU sortie Donut vide
    donut_incoherent = (not receipt.items) and (not receipt.total)
    want_fallback = (country == "CI") or donut_incoherent
    groq_key = resolve_key("groq")[0]
    if want_fallback and groq_key:
        try:
            vision_pred = extract_receipt_via_vision(pre_img)
            vision_receipt = Receipt.from_gt_parse(vision_pred)
            if vision_receipt.items or vision_receipt.total:
                prediction, receipt, engine = vision_pred, vision_receipt, "llm_fallback"
        except VisionUnavailable:
            # Aucun modele vision accessible : degradation gracieuse EXPLICITE
            # (pas un 404 silencieux). On ne logue pas la cle.
            fallback_note = ("Fallback vision indisponible — modèle non accessible "
                             "avec cette clé.")
            if (not receipt.items) and (not receipt.total):
                engine = "fallback_indisponible"
        except Exception as exc:
            logger.warning("Fallback vision échoué : %s", type(exc).__name__)
            fallback_note = "Fallback vision indisponible (modèle ou quota Groq)."
            if (not receipt.items) and (not receipt.total):
                engine = "fallback_indisponible"
    elif want_fallback:
        fallback_note = "Fallback vision non tenté : aucune clé Groq configurée."

    bundle = build_receipt_bundle(receipt, country, payment_mode, _nan(merchant))
    bundle.update({
        "engine": engine,
        "fallback_note": fallback_note,
        "raw_json": prediction,
        "preprocess": pre_info,
        "country": country,
        "payment_mode": payment_mode,
    })
    return ok(bundle)


# ---------------------------------------------------------------------------
# POST /api/validate  (recalcul live si persist=false, ajout a la SESSION si true)
# ---------------------------------------------------------------------------
class ValidatePayload(BaseModel):
    items: list = []
    subtotal: float | None = None
    tax: float | None = None
    total: float | None = None
    category: str | None = None
    account: str | None = None          # compte choisi manuellement (selectbox du front)
    merchant: str | None = None
    country: str = "CI"
    payment_mode: str = "cash"
    persist: bool = True


@app.post("/api/validate")
@safe
def api_validate(payload: ValidatePayload, request: Request):
    # normalise les articles recus du front
    items = []
    for it in payload.items:
        items.append({
            "name": it.get("name"),
            "quantity": it.get("quantity"),
            "unit_price": it.get("unit_price"),
            "line_price": it.get("line_price"),
        })
    receipt = Receipt(items=items, subtotal=payload.subtotal, tax=payload.tax,
                      total=payload.total)
    bundle = build_receipt_bundle(receipt, payload.country, payload.payment_mode,
                                  _nan(payload.merchant), category=payload.category)

    # compte reassigne manuellement : on remplace le compte de la ligne de charge
    # sans toucher aux montants (l'ecriture reste equilibree).
    if payload.account and bundle["journal"] and bundle["journal"][0]["account"] != payload.account:
        merchant_label = _nan(payload.merchant) or "fournisseur non identifié"
        label_account = CHART_OF_ACCOUNTS.get(payload.account, "Charge")
        bundle["journal"][0]["account"] = payload.account
        bundle["journal"][0]["label"] = f"{label_account} — {merchant_label}"

    bundle["persisted"] = False

    # Persistance = ajout aux depenses de CETTE session (memoire seule, jamais
    # sur disque : un correcteur qui clone n'herite pas des recus d'un autre).
    if payload.persist:
        session = _session(request)
        new_id = session.add_receipt(receipt, payload.category, bundle["audit"],
                                     merchant=_nan(payload.merchant))
        bundle["persisted"] = True
        bundle["receipt_id"] = new_id
        bundle["demo_mode"] = session.demo_mode
    return ok(bundle)


# ---------------------------------------------------------------------------
# GET /api/dashboard
# ---------------------------------------------------------------------------
@app.get("/api/dashboard")
@safe
def api_dashboard(request: Request):
    # Donnees de CETTE session, PAS le corpus CORD de data/.
    session = _session(request)
    data = session.get_dashboard_data()
    data["demo_mode"] = session.demo_mode
    return ok(data)


# ---------------------------------------------------------------------------
# GET /api/accounting?period=
# ---------------------------------------------------------------------------
@app.get("/api/accounting")
@safe
def api_accounting(request: Request, period: str = "Mois en cours",
                   payment_mode: str = "cash", country: str = "CI"):
    # Comptabilise les recus de CETTE session, PAS le corpus CORD.
    session = _session(request)
    data = session.get_accounting_data(period, payment_mode, country)
    data["demo_mode"] = session.demo_mode
    return ok(data)


# ---------------------------------------------------------------------------
# POST /api/search
# ---------------------------------------------------------------------------
class SearchPayload(BaseModel):
    question: str


@app.post("/api/search")
@safe
def api_search(payload: SearchPayload, request: Request):
    question = (payload.question or "").strip()
    if not question:
        return fail("Question vide.", detail="Saisissez une question.", status=422,
                    engine="search", suggestions=["Poser une question"])

    encoder, ref_index, ref_summaries = get_search()
    if encoder is None:
        return ok({"search_available": False, "llm_used": False, "answer": None,
                   "sources": [], "scope": "none", "reference_corpus": False,
                   "note": "Recherche sémantique indisponible "
                   "(FAISS / sentence-transformers non installés)."})

    from src.semantic import search, build_index, embed
    session = _session(request)

    if session.demo_mode:
        # Le mode demo EST le corpus CORD : on reutilise l'index precalcule.
        results = search(question, encoder, ref_index, ref_summaries, k=5)
        scope, reference_corpus, corpus_note = "user", False, None
    elif not session.is_empty():
        # Recherche dans les recus de l'utilisateur (peu nombreux : index a la volee).
        texts = session.search_texts()
        uindex = build_index(embed(texts, encoder))
        results = search(question, encoder, uindex, texts, k=min(5, len(texts)))
        scope, reference_corpus, corpus_note = "user", False, None
    else:
        # Session vide : on cherche dans le CORPUS DE REFERENCE, clairement signale.
        results = search(question, encoder, ref_index, ref_summaries, k=5)
        scope, reference_corpus = "reference", True
        corpus_note = ("Corpus de référence CORD — ce ne sont pas vos dépenses. "
                       "Analysez un reçu pour interroger les vôtres.")

    sources = [{"text": t, "score": float(s)} for t, s in results]

    answer, llm_used = None, False
    groq_key = resolve_key("groq")[0]
    if sources and groq_key:
        try:
            from src.llm import init_llm, answer_question
            init_llm(backend="groq", api_key=groq_key)
            answer = answer_question(question, [s["text"] for s in sources])
            llm_used = True
        except Exception as exc:
            logger.warning("Réponse LLM échouée : %s", type(exc).__name__)
            answer, llm_used = None, False   # degradation : sources seules

    return ok({"search_available": True, "llm_used": llm_used, "answer": answer,
               "sources": sources, "scope": scope, "reference_corpus": reference_corpus,
               "note": corpus_note, "demo_mode": session.demo_mode})


# ---------------------------------------------------------------------------
# Session utilisateur : etat, purge, mode demonstration
# ---------------------------------------------------------------------------
@app.get("/api/session")
@safe
def api_session(request: Request):
    """Etat de la session courante : mode demo + nombre de reçus. Le front
    s'en sert pour afficher (ou non) le bandeau de démonstration."""
    session = _session(request)
    return ok({"demo_mode": session.demo_mode,
               "n_receipts": len(session.receipts),
               "empty": session.is_empty()})


@app.delete("/api/session")
@safe
def api_session_clear(request: Request):
    """Vide les données de la session (reçus + mode démo)."""
    session = _session(request)
    session.clear()
    return ok({"demo_mode": False, "n_receipts": 0, "empty": True})


class DemoPayload(BaseModel):
    enabled: bool = True


@app.post("/api/settings/demo")
@safe
def api_settings_demo(payload: DemoPayload, request: Request):
    """MODE DÉMONSTRATION : peuple la session avec le corpus CORD (pour montrer
    un tableau de bord rempli en soutenance) ou le vide. Toujours signalé,
    jamais silencieux -- la réponse porte demo_mode que le front affiche en
    bandeau permanent."""
    session = _session(request)
    if payload.enabled:
        receipts, items = reference_dataset()
        session.load_demo(receipts, items)
    else:
        session.clear()
    return ok({"demo_mode": session.demo_mode, "n_receipts": len(session.receipts),
               "empty": session.is_empty()})


# ---------------------------------------------------------------------------
# GET /api/technical  (INCHANGE : donnees d'EVALUATION, pas de donnees user)
# ---------------------------------------------------------------------------
def _csv_records(name):
    try:
        return pd.read_csv(DATA / name).to_dict("records")
    except FileNotFoundError:
        return []


@app.get("/api/technical")
@safe
def api_technical():
    return ok({
        "results": _csv_records("results.csv"),
        "overfitting": _csv_records("overfitting.csv"),
        "loss_curve": _csv_records("loss_curve.csv"),
    })


# ---------------------------------------------------------------------------
# GET /api/config  (le front s'auto-configure : pays, comptes, dispo Groq)
# ---------------------------------------------------------------------------
@app.get("/api/config")
@safe
def api_config():
    groq = key_source("groq")
    return ok({
        "countries": {c: TAX_RATES[c] for c in TAX_RATES},
        "payment_modes": list(PAYMENT_ACCOUNTS.keys()),
        "chart_of_accounts": CHART_OF_ACCOUNTS,
        "groq_configured": groq != "none",
        "groq_source": groq,
        "disclaimer": DISCLAIMER,
    })


# ---------------------------------------------------------------------------
# Reglages : cles API (memoire seule, jamais sur disque ni dans les logs)
# ---------------------------------------------------------------------------
_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}
_SUPPORTED_PROVIDERS = {"groq"}   # Gemini prevu dans src/llm mais non expose ici


def _is_local(request):
    """N'autorise que les requetes locales : l'app tourne sur la machine de
    l'utilisateur, la config des cles ne doit pas etre pilotable a distance."""
    client = request.client
    host = client.host if client else None
    if host not in _LOCAL_HOSTS:
        return False
    origin = request.headers.get("origin")
    if origin:
        from urllib.parse import urlparse
        if urlparse(origin).hostname not in {"127.0.0.1", "::1", "localhost"}:
            return False
    return True


def _deny_remote():
    return fail("Configuration accessible en local uniquement.",
                detail="Cette action n'est autorisee que depuis cette machine.",
                status=403, engine="settings",
                suggestions=["Ouvrir l'application en local (localhost)"])


def _provider_of(name):
    return (name or "groq").strip().lower()


class ApiKeyPayload(BaseModel):
    provider: str = "groq"
    key: str = ""


@app.post("/api/settings/apikey")
@safe
def api_set_apikey(payload: ApiKeyPayload, request: Request):
    """Enregistre une cle EN MEMOIRE (session serveur). Ne renvoie JAMAIS la
    valeur, seulement l'etat. La cle d'environnement reste prioritaire."""
    if not _is_local(request):
        return _deny_remote()
    provider = _provider_of(payload.provider)
    if provider not in _SUPPORTED_PROVIDERS:
        return fail("Fournisseur non pris en charge.",
                    detail="Seule la cle Groq est configurable ici.",
                    status=422, engine="settings")
    # Cle d'environnement prioritaire : on ne l'ecrase pas.
    if key_source(provider) == "env":
        return ok({"provider": provider, "source": "env", "configured": True,
                   "note": "Cle fournie par l'environnement (prioritaire) — non modifiable ici."})
    key = (payload.key or "").strip()
    if not key or any(c.isspace() for c in key) or len(key) < 10:
        return fail("Cle vide ou invalide.",
                    detail="Collez une cle non vide, sans espace.",
                    status=422, engine="settings",
                    suggestions=["Copier la cle depuis console.groq.com"])
    set_session_key(provider, key)     # memoire seule, aucune ecriture disque
    return ok({"provider": provider, "source": "session", "configured": True})


@app.delete("/api/settings/apikey")
@safe
def api_clear_apikey(request: Request, provider: str = "groq"):
    """Efface la cle de session. Sans effet sur une cle d'environnement."""
    if not _is_local(request):
        return _deny_remote()
    provider = _provider_of(provider)
    clear_session_key(provider)
    source = key_source(provider)
    return ok({"provider": provider, "source": source, "configured": source != "none"})


@app.get("/api/settings/status")
@safe
def api_settings_status(request: Request):
    """Etat des cles, JAMAIS leur valeur : {source, configured} par fournisseur."""
    if not _is_local(request):
        return _deny_remote()
    providers = {}
    for provider in sorted(_SUPPORTED_PROVIDERS):
        source = key_source(provider)
        providers[provider] = {"source": source, "configured": source != "none"}
    return ok({"providers": providers, "groq": providers["groq"]})


@app.post("/api/settings/test")
@safe
def api_settings_test(request: Request, payload: ApiKeyPayload = ApiKeyPayload()):
    """Appel minimal au LLM pour verifier la cle active (env ou session).
    En cas d'echec, message humain ; on ne journalise NI la cle, NI le
    traceback du SDK (dont les exceptions peuvent embarquer des en-tetes)."""
    if not _is_local(request):
        return _deny_remote()
    provider = _provider_of(payload.provider)
    if provider not in _SUPPORTED_PROVIDERS:
        return fail("Fournisseur non pris en charge.", status=422, engine="settings")

    key, source = resolve_key(provider)
    if not key:
        return fail("Aucune cle a tester.",
                    detail="Configurez d'abord une cle Groq.",
                    status=422, engine="settings",
                    suggestions=["Saisir une cle Groq puis relancer le test"])
    try:
        from groq import Groq
        Groq(api_key=key).models.list()          # requete legere de verification
    except Exception as exc:
        # On ne logue que le TYPE d'exception : ni la cle, ni le message SDK.
        logger.warning("Test cle %s echoue : %s", provider, type(exc).__name__)
        return fail("Connexion Groq echouee.",
                    detail="La cle a ete refusee ou le service est injoignable.",
                    status=422, engine="settings",
                    suggestions=["Verifier la cle sur console.groq.com",
                                 "Verifier la connexion reseau"])
    return ok({"provider": provider, "source": source, "ok": True,
               "message": "Connexion Groq reussie."})


@app.get("/api/settings/models")
@safe
def api_settings_models(request: Request):
    """Modeles disponibles (vision / texte) pour la cle configuree, afin que
    l'utilisateur constate ce qui est utilisable. Corrige le 404 vision : le
    modele n'est plus code en dur, il est choisi parmi les modeles reels."""
    if not _is_local(request):
        return _deny_remote()
    key, source = resolve_key("groq")
    if not key:
        return fail("Aucune cle configuree.",
                    detail="Configurez une cle Groq pour lister les modeles.",
                    status=422, engine="settings",
                    suggestions=["Saisir une cle Groq"])
    try:
        groups = classify_models("groq")
        vision_selected = select_vision_model("groq")
    except Exception as exc:
        logger.warning("Liste des modeles Groq echouee : %s", type(exc).__name__)
        return fail("Impossible de lister les modeles.",
                    detail="La cle a ete refusee ou le service est injoignable.",
                    status=422, engine="settings",
                    suggestions=["Verifier la cle sur console.groq.com"])
    return ok({"source": source, "vision": groups["vision"], "text": groups["text"],
               "vision_selected": vision_selected,
               "vision_available": vision_selected is not None})


# ---------------------------------------------------------------------------
# Filet de securite ULTIME : toute erreur non geree -> JSON structure, JAMAIS
# un 500 avec traceback. Le detail technique part dans les logs.
# ---------------------------------------------------------------------------
@app.exception_handler(Exception)
async def any_error(request, exc):
    logger.exception("Exception non gérée sur %s", request.url.path)
    return JSONResponse({
        "success": False,
        "error": "Une erreur inattendue est survenue.",
        "detail": "L'incident a été enregistré côté serveur.",
        "engine": "server",
        "suggestions": ["Réessayer", "Recharger la page"],
    }, status_code=400)


# ---------------------------------------------------------------------------
# Front statique (monte en DERNIER pour ne pas masquer /api/*)
# ---------------------------------------------------------------------------
if WEB.exists():
    app.mount("/", StaticFiles(directory=str(WEB), html=True), name="web")
