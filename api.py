"""API FastAPI du Copilote de recus.

Endpoints MINCES : ils appellent le backend existant (src/) et renvoient du
JSON. Aucune logique metier n'est reecrite ici -- extraction (Donut), regles,
comptabilite, recherche vivent dans src/. L'API ne fait qu'exposer, orchestrer
le fallback vision, et servir le front statique de web/.

Lancer :  uvicorn api:app --reload
"""
import contextlib
import functools
import io
import logging
import math
import os
import re
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

from src.receipt import Receipt, filter_invoice_headers, find_invoice_number
from src.rules import audit, TAX_RATES
from src.accounting import (
    journal_entry, is_balanced, vat_recoverable, vat_summary, expense_report,
    apply_account_overrides, DISCLAIMER, CHART_OF_ACCOUNTS, PAYMENT_ACCOUNTS, CHARGE_ACCOUNTS,
)
from src.preprocess import preprocess_image, resolution_info, image_to_thumbnail_datauri
from src.extractor import extract
from src.llm import (
    extract_receipt_via_vision, VisionUnavailable,
    resolve_key, key_source, set_session_key, clear_session_key,
    classify_models, select_vision_model,
)
from src import session_store
from src import auth as auth_mod
from src import corrections as corrections_mod
from src import account_preferences as account_prefs_mod
from src import db as db_mod
from src import bilan as bilan_mod
from src import import_ledger
from src.models import Consent, Correction, LedgerEntry, User

DATA = Path("data")
WEB = Path("web")
WEB_REACT_DIST = Path("web-react/dist")

# Deux instances de l'app cohabitent : "demo" (accès libre, corpus CORD
# activable, onglet Technique visible -- inchangé) et "prod" (connexion
# obligatoire, chaque reçu rattaché au compte, pas de corpus de démo, pas
# d'onglet Technique). Une seule base de code, le mode choisit le comportement.
APP_MODE = os.environ.get("APP_MODE", "demo").strip().lower()
if APP_MODE not in ("prod", "demo"):
    APP_MODE = "demo"   # valeur inattendue -> comportement le moins risque

# Persistance legere des sessions, HORS DEPOT (jamais data/*.csv). Activee au
# demarrage d'un vrai serveur uniquement : TestClient (sans context manager)
# ne declenche pas le lifespan -> aucune I/O disque pendant les tests.
# Chemin par defaut deja specifique au mode -> deux instances (prod/demo)
# lancees avec des APP_MODE differents ne partagent jamais de fichier, meme
# sans configurer COPILOTE_STATE_FILE explicitement.
STATE_FILE = os.environ.get("COPILOTE_STATE_FILE", f".local_state/sessions_{APP_MODE}.db")

# Base comptes/corrections (src/models.py), fichier separe de sessions.db :
# schema different, cycle de vie different (les comptes ne sont jamais purges
# au vidage d'une session anonyme). Meme logique de chemin par defaut specifique
# au mode.
AUTH_DB_FILE = os.environ.get("COPILOTE_AUTH_DB_FILE", f".local_state/app_{APP_MODE}.db")

# Cookies "secure" (HTTPS uniquement) : desactive par defaut pour le dev local
# en http. A positionner a "true" via COOKIE_SECURE des que le service est
# expose en ligne (HTTPS obligatoire, voir analyse RGPD/securite du projet).
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "false").lower() == "true"


@contextlib.asynccontextmanager
async def _lifespan(app):
    session_store.init_persistence(STATE_FILE)   # ouvre SQLite + recharge l'etat
    db_mod.init_db(AUTH_DB_FILE)                  # comptes / recus lies / corrections
    try:
        yield
    finally:
        session_store.close_persistence()        # ferme proprement la connexion
        db_mod.close_db()


app = FastAPI(title="Copilote de reçus — API", lifespan=_lifespan)


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
    # Anti-obsolescence du front (bug E12) : StaticFiles ne pose aucun
    # Cache-Control, si bien qu'un navigateur peut resservir un vieux app.js/
    # api.js apres une modif -> reponses "d'un ancien etat". On force la
    # revalidation : "no-cache" laisse le cache mais oblige a verifier l'ETag
    # (304 si inchange, 200+contenu neuf sinon). Rapide ET jamais perime.
    if not request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "no-cache"
    return response


def _session(request):
    """La session utilisateur courante (creee a la volee si besoin).

    En mode demo : cookie de session anonyme, comportement historique
    inchange (corpus CORD activable, pas de compte requis).

    En mode prod : PAS d'acces anonyme. La session est clee sur le compte
    (user_id) plutot que sur le cookie -- session_store.py etait deja prevu
    pour ca ("AUTH FUTURE" dans son commentaire). Renvoie None si personne
    n'est connecte ; l'appelant doit alors renvoyer une erreur (voir
    _require_session)."""
    if APP_MODE == "prod":
        user_id = _current_user(request)
        if user_id is None:
            return None
        return session_store.get_session(f"user:{user_id}", user_id=user_id)
    return session_store.get_session(request.state.sid)


def _require_session(request):
    """Comme _session(), mais renvoie une reponse d'erreur prete a l'emploi
    si l'acces est refuse (mode prod sans connexion) -- meme forme que
    _require_user, pour rester coherent avec le reste de l'API."""
    session = _session(request)
    if session is None:
        return None, fail("Connexion requise.",
                          detail="Cette instance nécessite un compte connecté.",
                          status=401, engine="auth",
                          suggestions=["Se connecter", "Créer un compte"])
    return session, None


def _current_user(request):
    """user_id si un cookie d'auth valide (non expire, non altere) est
    present, sinon None. Distinct du cookie de session anonyme `sid`."""
    token = request.cookies.get(auth_mod.AUTH_COOKIE)
    return auth_mod.verify_token(token)


def _category_account_map(request):
    """Preferences de compte par categorie de l'utilisateur connecte
    (vide si anonyme) -- voir src/account_preferences.py."""
    user_id = _current_user(request)
    if user_id is None:
        return {}
    return account_prefs_mod.get_account_overrides_map(user_id)


# ---------------------------------------------------------------------------
# Ressources lourdes en chargement PARESSEUX (jamais au demarrage)
# ---------------------------------------------------------------------------
_donut = None            # (processor, model, device)
_search = None           # (encoder, index, summaries)
_reference = None        # (receipts_ref, items_ref) — corpus CORD pour le mode demo


def get_donut():
    """Charge Donut (~800 Mo) une seule fois, au premier /api/extract.

    model.eval() est OBLIGATOIRE, pas cosmetique : from_pretrained() ne le
    fait PAS tout seul (un nn.Module PyTorch nait en mode .training=True).
    Sans ca, le dropout du decodeur reste actif pendant la generation :
    calcul gaspille ET extraction non deterministe (le meme reçu peut donner
    un resultat different d'un appel a l'autre -- pas juste plus lent, moins
    fiable)."""
    global _donut
    if _donut is None:
        import torch
        from transformers import DonutProcessor, VisionEncoderDecoderModel
        name = "naver-clova-ix/donut-base-finetuned-cord-v2"
        processor = DonutProcessor.from_pretrained(name)
        model = VisionEncoderDecoderModel.from_pretrained(name)
        model.eval()
        device = "cuda" if torch.cuda.is_available() else "cpu"
        model = model.to(device)
        if os.environ.get("DONUT_QUANTIZE", "false").lower() == "true" and device == "cpu":
            model = _quantize_donut(model)
        _donut = (processor, model, device)
    return _donut


def _quantize_donut(model):
    """Quantization dynamique int8 (CPU uniquement) : accelere l'inference en
    reduisant la precision des couches Linear (majorite du calcul dans un
    transformer). Gain typique x1.5-3 sur CPU, au prix d'une precision
    numerique moindre -- pour un modele GENERATIF token-par-token comme
    Donut, un ecart de precision peut faire diverger la sequence produite
    (contrairement a un classifieur, une petite difference de logits peut
    changer le token choisi, qui influence tous les suivants). Desactive par
    defaut (DONUT_QUANTIZE=true pour activer) : a valider sur de vrais reçus
    avant d'activer en production, jamais suppose sans verification.
    N'echoue JAMAIS l'extraction : repli sur le modele non quantifie si la
    quantization elle-meme leve une exception (ce qui couvre aussi le jour
    ou torch.quantization, deja marquee deprecated au profit de torchao,
    sera retiree -- le repli reste valable sans rien changer ici)."""
    try:
        import torch
        quantized = torch.quantization.quantize_dynamic(
            model, {torch.nn.Linear}, dtype=torch.qint8)
        logger.info("Donut quantifie (int8 dynamique, CPU).")
        return quantized
    except Exception:
        logger.exception("Quantization Donut échouée, repli sur le modèle non quantifié.")
        return model


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


MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 Mo : large marge sur une vraie photo/un vrai tableur


def _read_upload_bounded(upload_file, max_bytes=MAX_UPLOAD_BYTES):
    """Lit un UploadFile en memoire, BORNE a max_bytes -- lit par blocs et
    s'arrete des que la limite est depassee, plutot que .read() sans
    argument qui chargerait un fichier arbitrairement gros en RAM avant
    tout controle (DoS par epuisement memoire). Leve ValueError si depasse."""
    chunks, total = [], 0
    while True:
        chunk = upload_file.file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise ValueError(f"fichier trop volumineux (> {max_bytes // (1024 * 1024)} Mo)")
        chunks.append(chunk)
    return b"".join(chunks)


def to_jsonable(obj):
    """Rend un objet serialisable en JSON STRICT : NaN/Infinity/NaT -> null,
    types numpy -> types Python. Sans ca, JSONResponse (allow_nan=False cote
    Starlette) leve une ValueError non geree des qu'un Infinity/NaN traine
    dans les donnees -- ex. un client qui poste `"total": Infinity` (JSON
    standard n'autorise pas ce token, mais json.loads l'accepte par defaut,
    donc ca arrive vraiment cote serveur)."""
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
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if obj is pd.NaT or (obj is not None and obj is pd.NA):
        return None
    return obj


def ok(payload):
    data = {"success": True}
    data.update(payload)
    return JSONResponse(to_jsonable(data))


def fail(error_msg, detail="", status=422, engine="donut", suggestions=None, extra=None):
    """Erreur JSON propre et STRUCTUREE. Le message est humain et court ; le
    traceback complet part dans les logs serveur, JAMAIS dans la reponse HTTP.
    Statut != 500 : une image inattendue ne doit pas casser la demo.
    `extra` : champs supplementaires a fusionner (ex. {"resolution": {...}})."""
    payload = {
        "success": False,
        "error": error_msg,
        "detail": detail,
        "engine": engine,
        "suggestions": suggestions or ["Réessayer avec une photo plus nette",
                                        "Saisir les données manuellement"],
    }
    if extra:
        payload.update(extra)
    return JSONResponse(to_jsonable(payload), status_code=status)


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


# ---------------------------------------------------------------------------
# AUTHENTIFICATION (comptes reels, src/auth.py + src/models.py)
# ---------------------------------------------------------------------------
class RegisterPayload(BaseModel):
    email: str
    password: str


class LoginPayload(BaseModel):
    email: str
    password: str


def _set_auth_cookie(response, user_id):
    token = auth_mod.issue_token(user_id)
    response.set_cookie(auth_mod.AUTH_COOKIE, token, httponly=True,
                        samesite="lax", secure=COOKIE_SECURE,
                        max_age=auth_mod.SESSION_MAX_AGE)


@app.post("/api/auth/register")
@safe
def api_auth_register(payload: RegisterPayload):
    try:
        user_id = auth_mod.register_user(payload.email, payload.password)
    except ValueError as exc:
        return fail(str(exc), status=422, engine="auth")
    response = ok({"user_id": user_id, "email": payload.email.strip().lower()})
    _set_auth_cookie(response, user_id)
    return response


@app.post("/api/auth/login")
@safe
def api_auth_login(payload: LoginPayload):
    user_id = auth_mod.authenticate(payload.email, payload.password)
    if user_id is None:
        return fail("Email ou mot de passe incorrect.", status=401, engine="auth",
                    suggestions=["Vérifier l'email et le mot de passe",
                                 "Réessayer dans quelques minutes en cas d'échecs répétés"])
    response = ok({"user_id": user_id})
    _set_auth_cookie(response, user_id)
    return response


@app.post("/api/auth/logout")
@safe
def api_auth_logout():
    response = ok({"logged_out": True})
    response.delete_cookie(auth_mod.AUTH_COOKIE)
    return response


@app.get("/api/auth/me")
@safe
def api_auth_me(request: Request):
    user_id = _current_user(request)
    if user_id is None:
        return fail("Non connecté.", status=401, engine="auth",
                    suggestions=["Se connecter", "Créer un compte"])
    return ok({"user_id": user_id})


class ConsentPayload(BaseModel):
    consent_type: str = "training_data"
    granted: bool = True


def _require_user(request):
    """user_id ou reponse d'erreur 401 prete a renvoyer (pas d'exception :
    les appelants restent de simples fonctions FastAPI, cf. le reste de l'API)."""
    user_id = _current_user(request)
    if user_id is None:
        return None, fail("Non connecté.", status=401, engine="auth",
                          suggestions=["Se connecter", "Créer un compte"])
    return user_id, None


@app.post("/api/auth/consent")
@safe
def api_auth_consent_set(payload: ConsentPayload, request: Request):
    user_id, error = _require_user(request)
    if error:
        return error
    corrections_mod.set_consent(user_id, payload.consent_type, payload.granted)
    return ok({"consent_type": payload.consent_type, "granted": payload.granted})


@app.get("/api/auth/consent")
@safe
def api_auth_consent_get(request: Request, consent_type: str = "training_data"):
    user_id, error = _require_user(request)
    if error:
        return error
    return ok({"consent_type": consent_type,
              "granted": corrections_mod.has_consent(user_id, consent_type)})


@app.get("/api/auth/export")
@safe
def api_auth_export(request: Request):
    """Droit a la portabilite (RGPD) : toutes les donnees personnelles
    rattachees au compte, en JSON -- y compris les reçus (session_store,
    cle sur le compte en mode prod, voir _session()). En mode demo, les
    reçus restent anonymes par session (jamais rattaches a un compte), donc
    naturellement absents ici meme si le compte existe."""
    user_id, error = _require_user(request)
    if error:
        return error
    account_session = session_store.get_session(f"user:{user_id}")
    with db_mod.get_db() as s:
        user = s.get(User, user_id)
        consents = (s.query(Consent).filter_by(user_id=user_id)
                   .order_by(Consent.created_at).all())
        corrs = (s.query(Correction).filter_by(user_id=user_id)
                .order_by(Correction.created_at).all())
        ledger = (s.query(LedgerEntry).filter_by(user_id=user_id)
                 .order_by(LedgerEntry.created_at).all())
        data = {
            "account": {"email": user.email, "created_at": user.created_at.isoformat()},
            "receipts": account_session.receipts,
            "ledger_entries": [{"account": e.account, "label": e.label, "debit": e.debit,
                               "credit": e.credit, "source": e.source,
                               "imported_from": e.imported_from,
                               "created_at": e.created_at.isoformat()} for e in ledger],
            "consents": [{"consent_type": c.consent_type, "granted": c.granted,
                         "created_at": c.created_at.isoformat()} for c in consents],
            "corrections": [{"receipt_id": c.receipt_id, "raw_json": c.raw_json,
                            "corrected_json": c.corrected_json, "engine": c.engine,
                            "country": c.country, "created_at": c.created_at.isoformat()}
                           for c in corrs],
            "note": ("« receipts » liste les reçus rattachés à votre compte (mode "
                     "production uniquement). En mode démonstration, les reçus restent "
                     "anonymes par session, jamais rattachés à un compte."),
        }
    return ok(data)


class DeleteAccountPayload(BaseModel):
    password: str


@app.delete("/api/auth/account")
@safe
def api_auth_delete_account(payload: DeleteAccountPayload, request: Request):
    """Droit a l'effacement (RGPD) : supprime le compte (cascade SQL sur
    corrections/consents, voir src/models.py) ET les reçus rattaches au
    compte dans session_store.py (pas couverts par la cascade SQL, table
    differente -- purges explicitement ici). Mot de passe requis pour
    confirmer -- un cookie vole ne doit pas suffire a effacer un compte."""
    user_id, error = _require_user(request)
    if error:
        return error
    if not auth_mod.verify_user_password(user_id, payload.password):
        return fail("Mot de passe incorrect.", status=401, engine="auth",
                    suggestions=["Vérifier le mot de passe"])
    with db_mod.get_db() as s:
        user = s.get(User, user_id)
        if user is not None:
            s.delete(user)
    session_store.drop_session(f"user:{user_id}")
    response = ok({"deleted": True})
    response.delete_cookie(auth_mod.AUTH_COOKIE)
    return response


def _nan(value):
    """Case CSV vide (NaN pandas) -> None (NaN est truthy et casse la logique
    a 3 etats des regles)."""
    return None if value is None or (isinstance(value, float) and math.isnan(value)) else value


def _merge_overrides(payload):
    """Fusionne l'ancien champ `account` (selecteur unique historique) dans le
    nouveau dict `account_overrides` (surcharge par ligne, Tache 4). L'ancien
    devient la surcharge de la ligne de charge 0."""
    overrides = dict(payload.account_overrides or {})
    if getattr(payload, "account", None) and "0" not in overrides:
        overrides["0"] = payload.account
    return overrides or None


def _capture_correction(request, payload, receipt_id):
    """Best-effort : capture (prediction brute, valeur corrigee) si connecte
    ET consentant (verifie a nouveau dans corrections_mod, pas de confiance
    aveugle ici) ET qu'un raw_json a ete fourni. N'a JAMAIS le droit de faire
    echouer la validation/mise a jour du recu -- c'est une consequence
    secondaire de la requete, pas son but."""
    if not payload.raw_json:
        return
    user_id = _current_user(request)
    if user_id is None:
        return
    corrected = {"items": payload.items, "subtotal": payload.subtotal, "tax": payload.tax,
                "total": payload.total, "category": payload.category,
                "merchant": _nan(payload.merchant)}
    try:
        corrections_mod.record_correction(user_id, receipt_id, payload.raw_json, corrected,
                                          engine=payload.engine, country=payload.country)
    except Exception:
        logger.exception("Capture de correction échouée (non bloquant)")


def _capture_account_preference(request, bundle):
    """Best-effort : quand l'utilisateur connecte surcharge manuellement le
    compte d'une ligne de charge, retient categorie -> compte pour la
    prochaine fois (voir src/account_preferences.py). PAS lie au consentement
    RGPD (ce n'est pas une donnee d'entrainement, juste une preference d'UI).
    N'a jamais le droit de faire echouer la requete."""
    user_id = _current_user(request)
    if user_id is None:
        return
    journal = bundle.get("journal") or []
    try:
        for line in journal:
            if line.get("manual") and line.get("categories"):
                for cat in line["categories"]:
                    account_prefs_mod.remember_account(user_id, cat, line["account"])
    except Exception:
        logger.exception("Mémorisation de préférence de compte échouée (non bloquant)")


def build_receipt_bundle(receipt, country, payment_mode, merchant, category=None,
                         account_overrides=None, category_account_map=None):
    """audit + ecriture + TVA a partir d'un Receipt. Coeur partage par
    /api/extract, /api/validate et PUT /api/receipt.

    `category_account_map` (optionnel) : preferences apprises de l'utilisateur
    connecte (voir src/account_preferences.py) -- prend le pas sur le mapping
    par defaut pour proposer directement le bon compte, sans que l'utilisateur
    ait a recorriger la meme categorie a chaque reçu."""
    flags = audit(receipt, country=country)
    try:
        entry = journal_entry(receipt, category=category, payment_mode=payment_mode,
                              country=country, merchant=merchant,
                              category_account_map=category_account_map)
        # surcharge manuelle des comptes de charge (Tache 4) : compte seul,
        # montant inchange -> equilibre preserve.
        apply_account_overrides(entry, account_overrides)
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
def api_extract(request: Request, file: UploadFile = File(...), country: str = Form("ID"),
                payment_mode: str = Form("cash"), merchant: str = Form(None),
                doc_type: str = Form("ticket")):
    try:
        raw = _read_upload_bounded(file)
    except ValueError:
        return fail("Fichier trop volumineux.",
                    detail=f"Taille maximale acceptée : {MAX_UPLOAD_BYTES // (1024 * 1024)} Mo.",
                    status=422)
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

    # Garde-fou de resolution (bug E10) : trop peu de pixels -> le modele
    # hallucine du texte sur du flou. On rejette AVANT toute extraction.
    res = resolution_info(image)
    if not res["ok"]:
        return fail(
            "Image trop basse résolution",
            detail=(f"Cette image fait {res['width']}x{res['height']} px "
                    f"(~{res['megapixels']} Mpx). Une extraction fiable nécessite au "
                    f"moins ~{res['min_megapixels']} Mpx pour éviter que le modèle "
                    f"invente du texte sur du flou."),
            status=422, engine="resolution",
            suggestions=["Prendre une nouvelle photo, nette et de près",
                         "Saisir les données manuellement"],
            extra={"resolution": res},
        )

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

    # Post-traitement FACTURE (regles simples) : retire les lignes d'en-tete
    # (nom/adresse/email captes comme 'articles' sans montant, en tete de liste).
    # Le mode 'ticket' ne touche a rien -> comportement identique a avant.
    invoice_number = None
    if doc_type == "facture":
        # numero cherche AVANT le filtre (la ligne "Facture n°..." est un en-tete
        # sans montant qui sera justement retiree). Texte deja extrait, pas Donut.
        invoice_number = find_invoice_number(
            " ".join(str(it.get("name") or "") for it in receipt.items))
        receipt.items = filter_invoice_headers(receipt.items)

    # Miniature (~800px) de l'image d'origine, pour l'AFFICHER plus tard dans le
    # détail. Encodée en base64 ; le front la renvoie à la validation pour la
    # stocker avec le reçu. Jamais la pleine résolution (poids maîtrisé).
    try:
        image_data = image_to_thumbnail_datauri(image)
    except Exception:
        image_data = None

    bundle = build_receipt_bundle(receipt, country, payment_mode, _nan(merchant),
                                  category_account_map=_category_account_map(request))
    bundle.update({
        "engine": engine,
        "fallback_note": fallback_note,
        "raw_json": prediction,
        "preprocess": pre_info,
        "country": country,
        "payment_mode": payment_mode,
        "doc_type": doc_type,
        "invoice_number": invoice_number,
        "image_data": image_data,
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
    country: str = "ID"                 # defaut ID : le corpus CORD est indonesien
    payment_mode: str = "cash"
    doc_type: str = "ticket"            # 'ticket' ou 'facture' (contexte du recu)
    invoice_number: str | None = None   # numero de facture trouve a l'extraction
    account_overrides: dict | None = None  # {index_ligne_charge: compte} surcharge manuelle
    image_data: str | None = None       # miniature base64 du recu (affichage detail)
    persist: bool = True
    raw_json: dict | None = None        # sortie brute du modele (renvoyee par /api/extract) :
                                         # presente => capture d'une correction si l'utilisateur
                                         # est connecte ET a consenti (voir _capture_correction)
    engine: str | None = None           # donut / llm_fallback... (contexte de raw_json)


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
            "category": it.get("category"),   # categorie par article (si fournie) -> compte
        })
    receipt = Receipt(items=items, subtotal=payload.subtotal, tax=payload.tax,
                      total=payload.total)
    overrides = _merge_overrides(payload)
    bundle = build_receipt_bundle(receipt, payload.country, payload.payment_mode,
                                  _nan(payload.merchant), category=payload.category,
                                  account_overrides=overrides,
                                  category_account_map=_category_account_map(request))
    bundle["account_overrides"] = overrides
    bundle["persisted"] = False

    # Persistance = ajout aux depenses de CETTE session (memoire seule, jamais
    # sur disque : un correcteur qui clone n'herite pas des recus d'un autre).
    if payload.persist:
        session, error = _require_session(request)
        if error:
            return error
        _capture_account_preference(request, bundle)
        new_id = session.add_receipt(receipt, payload.category, bundle["audit"],
                                     merchant=_nan(payload.merchant), doc_type=payload.doc_type,
                                     invoice_number=_nan(payload.invoice_number),
                                     account_overrides=overrides,
                                     image_data=_nan(payload.image_data))
        bundle["persisted"] = True
        bundle["receipt_id"] = new_id
        bundle["demo_mode"] = session.demo_mode
    bundle["doc_type"] = payload.doc_type
    bundle["invoice_number"] = _nan(payload.invoice_number)
    _capture_correction(request, payload, bundle.get("receipt_id"))
    return ok(bundle)


# ---------------------------------------------------------------------------
# GET /api/dashboard
# ---------------------------------------------------------------------------
@app.get("/api/dashboard")
@safe
def api_dashboard(request: Request):
    # Donnees de CETTE session, PAS le corpus CORD de data/.
    session, error = _require_session(request)
    if error:
        return error
    data = session.get_dashboard_data()
    data["demo_mode"] = session.demo_mode
    return ok(data)


@app.get("/api/receipt/{receipt_id}")
@safe
def api_receipt(receipt_id: int, request: Request, country: str = "ID",
                payment_mode: str = "cash"):
    """Detail complet d'un recu de la session : articles, montants, 4 controles,
    ecriture comptable. Reutilise build_receipt_bundle (aucune logique dupliquee)."""
    session, error = _require_session(request)
    if error:
        return error
    row, items = session.get_receipt(receipt_id)
    if row is None:
        return fail("Reçu introuvable.",
                    detail="Ce reçu n'existe pas dans votre session.",
                    status=404, engine="session",
                    suggestions=["Revenir au tableau de bord"])
    receipt = Receipt(
        items=[{"name": it.get("name"), "quantity": it.get("quantity"),
                "unit_price": it.get("unit_price"), "line_price": it.get("line_price"),
                "category": _nan(it.get("category"))}   # categorie par article -> compte
               for it in items],
        subtotal=_nan(row.get("subtotal")), tax=_nan(row.get("tax")),
        total=_nan(row.get("total")), receipt_id=receipt_id)
    overrides = _nan(row.get("account_overrides"))
    bundle = build_receipt_bundle(receipt, country, payment_mode,
                                  _nan(row.get("merchant")), category=_nan(row.get("category")),
                                  account_overrides=overrides,
                                  category_account_map=_category_account_map(request))
    bundle["receipt_id"] = receipt_id
    bundle["category"] = _nan(row.get("category"))
    bundle["doc_type"] = _nan(row.get("doc_type")) or "ticket"
    bundle["invoice_number"] = _nan(row.get("invoice_number"))
    bundle["account_overrides"] = overrides or {}
    bundle["image_data"] = _nan(row.get("image_data"))   # None si démo/ancien reçu
    bundle["demo_mode"] = session.demo_mode
    return ok(bundle)


@app.put("/api/receipt/{receipt_id}")
@safe
def api_receipt_update(receipt_id: int, payload: ValidatePayload, request: Request):
    """Modifie un recu deja valide (Tache 2). Recalcule audit + ecriture via
    build_receipt_bundle, puis remplace le recu dans la session."""
    session, error = _require_session(request)
    if error:
        return error
    row, _ = session.get_receipt(receipt_id)
    if row is None:
        return fail("Reçu introuvable.", detail="Ce reçu n'existe pas dans votre session.",
                    status=404, engine="session", suggestions=["Revenir au tableau de bord"])
    items = [{"name": it.get("name"), "quantity": it.get("quantity"),
              "unit_price": it.get("unit_price"), "line_price": it.get("line_price"),
              "category": it.get("category")} for it in payload.items]
    receipt = Receipt(items=items, subtotal=payload.subtotal, tax=payload.tax, total=payload.total)
    overrides = _merge_overrides(payload)
    bundle = build_receipt_bundle(receipt, payload.country, payload.payment_mode,
                                  _nan(payload.merchant), category=payload.category,
                                  account_overrides=overrides,
                                  category_account_map=_category_account_map(request))
    _capture_account_preference(request, bundle)
    session.update_receipt(receipt_id, receipt, payload.category, bundle["audit"],
                           merchant=_nan(payload.merchant), doc_type=payload.doc_type,
                           invoice_number=_nan(payload.invoice_number), account_overrides=overrides,
                           image_data=_nan(payload.image_data))
    # image conservée si non renvoyée : on relit la ligne à jour pour l'exposer
    updated_row, _ = session.get_receipt(receipt_id)
    bundle.update({"receipt_id": receipt_id, "category": payload.category,
                   "doc_type": payload.doc_type, "invoice_number": _nan(payload.invoice_number),
                   "account_overrides": overrides or {}, "updated": True,
                   "image_data": _nan(updated_row.get("image_data")) if updated_row else None,
                   "demo_mode": session.demo_mode})
    _capture_correction(request, payload, receipt_id)
    return ok(bundle)


@app.delete("/api/receipt/{receipt_id}")
@safe
def api_receipt_delete(receipt_id: int, request: Request):
    """Supprime un recu valide (Tache 2) : disparait de toutes les vues."""
    session, error = _require_session(request)
    if error:
        return error
    if not session.delete_receipt(receipt_id):
        return fail("Reçu introuvable.", detail="Ce reçu n'existe pas dans votre session.",
                    status=404, engine="session", suggestions=["Revenir au tableau de bord"])
    return ok({"deleted": True, "receipt_id": receipt_id})


# ---------------------------------------------------------------------------
# GET /api/accounting?period=
# ---------------------------------------------------------------------------
@app.get("/api/accounting")
@safe
def api_accounting(request: Request, period: str = "Mois en cours",
                   payment_mode: str = "cash", country: str = "ID"):
    # Comptabilise les recus de CETTE session, PAS le corpus CORD.
    session, error = _require_session(request)
    if error:
        return error
    data = session.get_accounting_data(period, payment_mode, country,
                                       category_account_map=_category_account_map(request))
    data["demo_mode"] = session.demo_mode
    return ok(data)


# ---------------------------------------------------------------------------
# GET /api/bilan, POST /api/bilan/import, POST /api/bilan/entry,
# DELETE /api/bilan/entries
# ---------------------------------------------------------------------------
def _receipt_journal_lines(session, payment_mode, country, category_account_map):
    """Toutes les lignes de journal des reçus valides de la session, a plat
    (le bilan porte sur l'ensemble des reçus, pas une periode -- voir
    src/accounting.py:expense_report, "period" y est deja un simple libelle
    d'affichage, jamais un filtre)."""
    data = session.get_accounting_data("Bilan", payment_mode, country,
                                       category_account_map=category_account_map)
    if data.get("empty"):
        return []
    lines = []
    for group in data["journal"]:
        lines.extend(group["lines"])
    return lines


@app.get("/api/bilan")
@safe
def api_bilan(request: Request, payment_mode: str = "cash", country: str = "ID"):
    """Bilan comptable (Actif/Passif) : lignes issues des reçus valides de la
    session + écritures importées/manuelles du compte (LedgerEntry, si
    connecté -- sinon uniquement ce que les reçus permettent de calculer)."""
    session, error = _require_session(request)
    if error:
        return error
    receipt_lines = _receipt_journal_lines(session, payment_mode, country,
                                           _category_account_map(request))
    user_id = _current_user(request)
    ledger_entries = []
    if user_id is not None:
        with db_mod.get_db() as s:
            rows = s.query(LedgerEntry).filter_by(user_id=user_id).all()
            ledger_entries = [{"account": e.account, "debit": e.debit, "credit": e.credit}
                              for e in rows]
    result = bilan_mod.compute_bilan(receipt_lines, ledger_entries)
    result["disclaimer"] = DISCLAIMER
    result["has_imported_entries"] = bool(ledger_entries)
    return ok(result)


@app.post("/api/bilan/import")
@safe
def api_bilan_import(request: Request, file: UploadFile = File(...)):
    """Import d'un fichier d'écritures/bilan externe (.xlsx/.csv/.docx) dans
    le compte de l'utilisateur connecté -- alimente le bilan (LedgerEntry)."""
    user_id, error = _require_user(request)
    if error:
        return error
    try:
        raw = _read_upload_bounded(file)
    except ValueError:
        return fail("Fichier trop volumineux.",
                    detail=f"Taille maximale acceptée : {MAX_UPLOAD_BYTES // (1024 * 1024)} Mo.",
                    status=422, engine="import")
    except Exception:
        return fail("Fichier illisible.", status=422, engine="import")
    if not raw:
        return fail("Fichier vide.", status=422, engine="import")
    try:
        rows, parse_errors = import_ledger.parse_ledger_file(file.filename, raw)
    except ValueError as exc:
        return fail("Import impossible.", detail=str(exc), status=422, engine="import",
                    suggestions=["Vérifier les colonnes (Compte, Libellé, Débit, Crédit)",
                                 "Formats acceptés : .xlsx, .csv, .docx"])
    if not rows:
        return fail("Aucune ligne exploitable dans ce fichier.", status=422, engine="import",
                    detail=f"{len(parse_errors)} ligne(s) ignorée(s).", extra={"errors": parse_errors})

    total_debit = round(sum(r["debit"] for r in rows), 2)
    total_credit = round(sum(r["credit"] for r in rows), 2)
    with db_mod.get_db() as s:
        for r in rows:
            s.add(LedgerEntry(user_id=user_id, account=r["account"], label=r["label"],
                              debit=r["debit"], credit=r["credit"],
                              source="import", imported_from=file.filename))
    return ok({
        "imported": len(rows),
        "skipped": len(parse_errors),
        "errors": parse_errors,
        "total_debit": total_debit,
        "total_credit": total_credit,
        "balanced": abs(total_debit - total_credit) <= 0.01,
    })


class LedgerEntryPayload(BaseModel):
    account: str
    label: str | None = None
    debit: float = 0.0
    credit: float = 0.0


@app.post("/api/bilan/entry")
@safe
def api_bilan_entry_add(payload: LedgerEntryPayload, request: Request):
    """Saisie manuelle d'une écriture de bilan (capital, immobilisation...)."""
    user_id, error = _require_user(request)
    if error:
        return error
    if not payload.account:
        return fail("Compte requis.", status=422, engine="import")
    if payload.debit == 0 and payload.credit == 0:
        return fail("Débit et crédit ne peuvent pas être tous les deux à zéro.",
                    status=422, engine="import")
    with db_mod.get_db() as s:
        entry = LedgerEntry(user_id=user_id, account=payload.account, label=payload.label,
                            debit=payload.debit, credit=payload.credit, source="manual")
        s.add(entry)
        s.flush()
        return ok({"id": entry.id})


@app.delete("/api/bilan/entries")
@safe
def api_bilan_entries_clear(request: Request):
    """Efface toutes les écritures importées/manuelles du compte (repartir
    d'un bilan propre après un import raté, par ex.). Ne touche pas aux
    reçus."""
    user_id, error = _require_user(request)
    if error:
        return error
    with db_mod.get_db() as s:
        deleted = s.query(LedgerEntry).filter_by(user_id=user_id).delete()
    return ok({"deleted": deleted})


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
    session, error = _require_session(request)
    if error:
        return error

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

    # receipt_id resolu depuis le texte ("Reçu #N" ou "Reçu N :") UNIQUEMENT si
    # ce reçu existe dans la session -> source cliquable vers son détail. Les
    # sources du corpus de référence (session vide) ne pointent sur rien.
    session_ids = {int(r["receipt_id"]) for r in session.receipts}

    def _source_id(text):
        m = re.match(r"Reçu\s*#?(\d+)", text)
        if not m:
            return None
        rid = int(m.group(1))
        return rid if rid in session_ids else None

    sources = [{"text": t, "score": float(s), "receipt_id": _source_id(t)} for t, s in results]

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
    session, error = _require_session(request)
    if error:
        return error
    return ok({"demo_mode": session.demo_mode,
               "n_receipts": len(session.receipts),
               "empty": session.is_empty()})


@app.delete("/api/session")
@safe
def api_session_clear(request: Request):
    """Vide les données de la session (reçus + mode démo)."""
    session, error = _require_session(request)
    if error:
        return error
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
    bandeau permanent.

    Indisponible en mode prod : un vrai compte ne doit jamais pouvoir charger
    le corpus de démonstration dans ses données (voir APP_MODE)."""
    if APP_MODE == "prod":
        return fail("Le mode démonstration n'est pas disponible sur cette instance.",
                    status=403, engine="config",
                    suggestions=["Analyser un reçu réel"])
    session, error = _require_session(request)
    if error:
        return error
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
        "charge_accounts": CHARGE_ACCOUNTS,   # comptes de charge modifiables (Tache 4)
        "groq_configured": groq != "none",
        "groq_source": groq,
        "disclaimer": DISCLAIMER,
        "app_mode": APP_MODE,
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
    # La cle de session l'emporte sur l'env (voir resolve_key) : on la stocke
    # meme si GROQ_API_KEY est definie, pour que l'utilisateur garde la main.
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
# Le nouveau front React (web-react/, build Vite) prend le pas s'il a été
# buildé (npm run build -> web-react/dist) ; sinon on retombe sur l'ancien
# front vanilla (web/), qui reste fonctionnel intact -- migration progressive,
# jamais d'app cassée si le build React est absent.
# ---------------------------------------------------------------------------
if WEB_REACT_DIST.exists():
    app.mount("/", StaticFiles(directory=str(WEB_REACT_DIST), html=True), name="web-react")
elif WEB.exists():
    app.mount("/", StaticFiles(directory=str(WEB), html=True), name="web")
