"""Capture des corrections humaines (apprentissage sur les reçus ivoiriens/
français) et primitives de consentement RGPD associées.

Le consentement est un journal append-only (jamais écrasé, voir
src/models.py:Consent) : seul le dernier enregistrement par (utilisateur,
type) fait foi. record_correction() revérifie TOUJOURS le consentement lui-
même, plutôt que de faire confiance à l'appelant -- ainsi aucun futur appel
ne peut oublier la vérification et capturer des données sans consentement.
"""
from src.db import get_db
from src.models import Consent, Correction


def set_consent(user_id, consent_type, granted):
    with get_db() as s:
        s.add(Consent(user_id=user_id, consent_type=consent_type, granted=bool(granted)))


def has_consent(user_id, consent_type):
    with get_db() as s:
        latest = (s.query(Consent)
                  .filter_by(user_id=user_id, consent_type=consent_type)
                  .order_by(Consent.created_at.desc(), Consent.id.desc())
                  .first())
        return bool(latest and latest.granted)


def record_correction(user_id, receipt_id, raw_json, corrected_json, engine=None, country=None):
    """Enregistre la paire (prédiction brute, valeur corrigée) si et
    seulement si l'utilisateur a consenti à l'usage de ses corrections pour
    l'entraînement. Ne stocke jamais l'image (minimisation, voir Correction).
    Renvoie l'id créé, ou None si rien n'a été enregistré (pas de consentement,
    ou aucune différence entre raw_json et corrected_json -- rien à apprendre)."""
    if not user_id or not has_consent(user_id, "training_data"):
        return None
    if raw_json == corrected_json:
        return None
    with get_db() as s:
        corr = Correction(user_id=user_id, receipt_id=receipt_id,
                          raw_json=raw_json or {}, corrected_json=corrected_json or {},
                          engine=engine, country=country)
        s.add(corr)
        s.flush()
        return corr.id
