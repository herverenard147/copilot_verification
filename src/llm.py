"""Prompt engineering : extraction zero-shot et question-reponse RAG.

TROIS BACKENDS INTERCHANGEABLES. Le projet ne depend d'aucun fournisseur en
particulier : si l'un est indisponible (quota, region, panne), on bascule sans
toucher au reste du code. Cette abstraction existe parce que le quota gratuit
Gemini s'est revele indisponible en cours de projet.
"""
import json
import re

_backend = None
_client = None
_model_name = None


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
