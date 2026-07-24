"""Prompt engineering : extraction zero-shot et question-reponse RAG.

TROIS BACKENDS INTERCHANGEABLES. Le projet ne depend d'aucun fournisseur en
particulier : si l'un est indisponible (quota, region, panne), on bascule sans
toucher au reste du code. Cette abstraction existe parce que le quota gratuit
Gemini s'est revele indisponible en cours de projet.

Ce module contient AUSSI le fallback vision hors-domaine (extract_receipt_via_
vision) : quand Donut echoue -- typiquement sur un ticket hors de sa
distribution CORD, ex. un ticket ivoirien -- un LLM vision lit l'image et
renvoie le MEME schema JSON. C'est un fallback ASSUME, jamais cache : l'API
indique toujours quel moteur a produit le resultat.
"""
import base64
import io
import json
import os
import re

_backend = None
_client = None
_model_name = None

# Modeles vision Groq candidats, par ORDRE DE PREFERENCE. On ne code plus un
# nom en dur : la disponibilite des modeles Groq evolue (un nom code en dur a
# provoque des 404 model_not_found). On interroge l'API des modeles et on
# retient le premier candidat REELLEMENT present pour la cle courante. Une
# surcharge explicite reste possible via GROQ_VISION_MODEL (placee en tete).
_VISION_MODEL_CANDIDATES = [
    "meta-llama/llama-4-maverick-17b-128e-instruct",
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "llama-3.2-90b-vision-preview",
    "llama-3.2-11b-vision-preview",
]

# Indices de nom permettant de reconnaitre un modele multimodal dans la liste
# renvoyee par l'API (pour l'affichage GET /api/settings/models).
_VISION_HINTS = ("vision", "scout", "maverick", "llama-4")


class VisionUnavailable(RuntimeError):
    """Le fallback vision ne peut pas s'executer : aucun modele multimodal
    n'est accessible avec la cle courante. Signale a l'appelant pour une
    degradation gracieuse (pas un 404 silencieux)."""


_model_list_cache = {}   # cle -> [ids de modeles], duree du processus

# ---------------------------------------------------------------------------
# Resolution des cles API : SOURCE UNIQUE de verite (env > session > absent).
#
# Les cles de session vivent UNIQUEMENT en memoire du processus (ce dict), le
# temps de la vie de l'app : jamais ecrites sur disque, jamais dans un .env,
# jamais journalisees. La variable d'environnement l'emporte toujours ; quand
# elle est presente, la cle de session est ignoree (et l'UI passe en lecture
# seule). Toute autre partie du code (api.py, app.py) doit passer par
# resolve_key()/key_source() plutot que de relire os.environ, pour ne pas
# dupliquer la priorite.
# ---------------------------------------------------------------------------
_ENV_VARS = {
    "groq": ["GROQ_API_KEY"],
    "gemini": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],   # prevu, non expose dans l'UI
}

_session_keys = {}   # {provider: cle} — memoire volatile, duree du processus


def _env_key(provider):
    for name in _ENV_VARS.get(provider, []):
        value = os.environ.get(name)
        if value:
            return value
    return None


def resolve_key(provider="groq"):
    """Retourne (cle, source) selon la priorite env > session > absent.
    source vaut "env", "session" ou "none". Ne journalise jamais la cle."""
    env = _env_key(provider)
    if env:
        return env, "env"
    session = _session_keys.get(provider)
    if session:
        return session, "session"
    return None, "none"


def key_source(provider="groq"):
    """Etat SEUL (jamais la valeur) : "env" | "session" | "none"."""
    return resolve_key(provider)[1]


def set_session_key(provider, key):
    """Stocke une cle EN MEMOIRE pour la duree du processus. Aucune ecriture
    disque. Leve ValueError si la cle est vide (l'appelant renvoie une erreur
    propre). N'ecrase pas une cle d'environnement : la priorite est geree en
    amont par l'appelant via key_source()."""
    key = (key or "").strip()
    if not key:
        raise ValueError("Cle vide")
    _session_keys[provider] = key


def clear_session_key(provider):
    """Efface la cle de session (aucun effet sur une eventuelle cle d'env)."""
    _session_keys.pop(provider, None)
    _model_list_cache.clear()   # la liste de modeles depend de la cle


# ---------------------------------------------------------------------------
# Modeles disponibles pour la cle courante (interrogation + selection vision)
# ---------------------------------------------------------------------------
def list_available_models(provider="groq", force=False):
    """IDs de modeles disponibles pour la cle courante, en cache pour la duree
    du processus (par valeur de cle). Leve RuntimeError sans cle. Les erreurs
    reseau/SDK remontent a l'appelant."""
    key, _ = resolve_key(provider)
    if not key:
        raise RuntimeError("Aucune cle : impossible de lister les modeles")
    if not force and key in _model_list_cache:
        return _model_list_cache[key]
    from groq import Groq
    response = Groq(api_key=key).models.list()
    ids = sorted(m.id for m in response.data)
    _model_list_cache[key] = ids
    return ids


def select_vision_model(provider="groq"):
    """1er modele vision REELLEMENT disponible selon l'ordre de preference,
    ou None si aucun candidat n'est present pour cette cle. Une surcharge
    GROQ_VISION_MODEL est essayee en priorite."""
    available = set(list_available_models(provider))
    override = os.environ.get("GROQ_VISION_MODEL")
    candidates = ([override] if override else []) + _VISION_MODEL_CANDIDATES
    for name in candidates:
        if name in available:
            return name
    return None


def classify_models(provider="groq"):
    """Separe les modeles disponibles en {vision, text} pour l'affichage
    Reglages. La detection vision s'appuie sur les candidats connus + des
    indices de nom (vision/scout/maverick/llama-4)."""
    ids = list_available_models(provider)
    known = set(_VISION_MODEL_CANDIDATES)
    vision = [m for m in ids if m in known or any(h in m.lower() for h in _VISION_HINTS)]
    text = [m for m in ids if m not in vision]
    return {"vision": vision, "text": text}


def init_llm(backend="groq", api_key=None, model_name=None):
    """backend="groq"   : API gratuite, quota genereux (console.groq.com)
       backend="gemini" : Google AI Studio (SDK google-genai)
       backend="local"  : petit modele instruct sur GPU, AUCUNE API"""
    global _backend, _client, _model_name
    _backend = backend

    if backend == "groq":
        from groq import Groq
        _client = Groq(api_key=api_key)
        _model_name = model_name or "llama-3.3-70b-versatile"

    elif backend == "gemini":
        from google import genai
        _client = genai.Client(api_key=api_key)
        _model_name = model_name or "gemini-2.5-flash"

    elif backend == "local":
        from transformers import pipeline
        _model_name = model_name or "Qwen/Qwen2.5-1.5B-Instruct"
        _client = pipeline("text-generation", model=_model_name,
                           device_map="auto", max_new_tokens=200)
    else:
        raise ValueError(f"Backend inconnu : {backend}")
    return _backend


def _ask(prompt):
    """Envoie un prompt au backend actif."""
    if _client is None:
        raise RuntimeError("LLM non initialise : appeler init_llm() d'abord")

    if _backend == "groq":
        r = _client.chat.completions.create(
            model=_model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,      # deterministe : extraction, pas creativite
        )
        return r.choices[0].message.content

    if _backend == "gemini":
        return _client.models.generate_content(
            model=_model_name, contents=prompt).text

    if _backend == "local":
        out = _client([{"role": "user", "content": prompt}], do_sample=False)
        return out[0]["generated_text"][-1]["content"]


def extract_merchant_date(receipt_text):
    """ZERO-SHOT : aucun exemple fourni, juste des consignes precises.

    Ces champs sont ABSENTS des annotations CORD (retires pour raisons
    legales). Impossible de les apprendre en supervise : le prompting est la
    seule voie.
    """
    prompt = f"""Tu analyses le texte brut d'un reçu de caisse indonésien.

Extrais uniquement deux informations :
- "merchant" : le nom du commerce (souvent en haut du reçu)
- "date" : la date d'achat au format AAAA-MM-JJ si possible

Réponds UNIQUEMENT par un objet JSON, sans texte autour, sans balises.
Si une information est absente, mets null.

Texte du reçu :
{receipt_text[:1500]}"""
    raw = _ask(prompt)
    cleaned = re.sub(r"```json|```", "", raw).strip()
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    try:
        return json.loads(match.group(0) if match else cleaned)
    except (json.JSONDecodeError, AttributeError):
        return {"merchant": None, "date": None, "_raw": raw[:200]}


def answer_question(question, contexts):
    """RAG : on fournit les recus retrouves, le LLM repond A PARTIR D'EUX.
    Sans cela, il inventerait des chiffres."""
    bloc = "\n".join(f"- {c}" for c in contexts)
    prompt = f"""Tu es un assistant de gestion de dépenses.
Réponds à la question en te basant UNIQUEMENT sur les reçus ci-dessous.
Si l'information n'y figure pas, dis-le clairement. Réponds en français,
en deux phrases maximum.

Reçus pertinents :
{bloc}

Question : {question}"""
    return _ask(prompt)


# ---------------------------------------------------------------------------
# Fallback vision hors-domaine
# ---------------------------------------------------------------------------
# Schema cible : EXACTEMENT celui de CORD/Donut, pour que Receipt.from_gt_parse
# fonctionne sans distinction de moteur. Donut pour son domaine (reçus
# indonesiens), le LLM vision au-dela (ex. reçus ivoiriens).
_VISION_SCHEMA_PROMPT = """Tu analyses la PHOTO d'un ticket de caisse. Extrais les informations et
réponds UNIQUEMENT par un objet JSON valide, sans texte autour, sans balises,
respectant EXACTEMENT ce schéma :

{
  "menu": [
    {"nm": "nom de l'article", "cnt": "quantité", "unitprice": "prix unitaire", "price": "prix total ligne"}
  ],
  "sub_total": {"subtotal_price": "sous-total HT", "tax_price": "montant de la taxe"},
  "total": {"total_price": "total TTC"}
}

Règles :
- Les montants sont des chaînes de chiffres, sans symbole monétaire ni espace (ex: "25000").
- Si un champ est absent du ticket, mets-le à null (ou omets la clé).
- N'invente aucun montant : recopie ce qui est lisible sur l'image.
- N'ajoute AUCUN texte hors du JSON."""


def _pil_to_data_uri(image, fmt="JPEG"):
    """Encode une image PIL en data URI base64 (pour l'API vision)."""
    buffer = io.BytesIO()
    if image.mode != "RGB":
        image = image.convert("RGB")
    image.save(buffer, format=fmt)
    b64 = base64.b64encode(buffer.getvalue()).decode("ascii")
    mime = "image/jpeg" if fmt.upper() in ("JPG", "JPEG") else "image/png"
    return f"data:{mime};base64,{b64}"


def extract_receipt_via_vision(image, api_key=None, model=None):
    """FALLBACK VISION : une image PIL -> le meme dict que Donut (schema CORD).

    Utilise un modele vision Groq. Leve une exception si la cle est absente,
    le modele indisponible, ou la reponse non exploitable : c'est a l'appelant
    (l'API) de decider quoi faire -- ici, retomber sur le resultat Donut et le
    signaler. On ne masque jamais l'echec.
    """
    api_key = api_key or resolve_key("groq")[0]
    if not api_key:
        raise RuntimeError("Aucune cle Groq : fallback vision indisponible")

    if model is None:
        model = select_vision_model("groq")
        if model is None:
            raise VisionUnavailable(
                "Aucun modele vision accessible avec cette cle Groq"
            )

    from groq import Groq
    client = Groq(api_key=api_key)
    data_uri = _pil_to_data_uri(image)

    response = client.chat.completions.create(
        model=model,
        temperature=0,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": _VISION_SCHEMA_PROMPT},
                {"type": "image_url", "image_url": {"url": data_uri}},
            ],
        }],
    )
    raw = response.choices[0].message.content
    cleaned = re.sub(r"```json|```", "", raw).strip()
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    parsed = json.loads(match.group(0) if match else cleaned)
    # normalise : garantir les cles attendues par Receipt.from_gt_parse
    parsed.setdefault("menu", [])
    parsed.setdefault("sub_total", {})
    parsed.setdefault("total", {})
    return parsed
