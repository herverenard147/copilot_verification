"""Memoire des comptes de charge preferes par un utilisateur, categorie par
categorie -- apprise de ses surcharges manuelles (voir api.py, section
"ecriture comptable proposee"). PAS lie au consentement RGPD "training_data" :
ce n'est pas une donnee d'entrainement pour le modele, juste une preference
d'UI qui reste dans le compte de son proprietaire, jamais partagee ni
utilisee pour ameliorer Donut.
"""
import unicodedata

from src.db import get_db
from src.models import AccountPreference


def _normalize(text):
    """Meme normalisation que src/accounting.py:_normalize (minuscules, sans
    accents) pour que les cles correspondent quelle que soit la casse/langue."""
    folded = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    return folded.strip().lower()


def remember_account(user_id, category, account):
    """Enregistre (ou remplace) la preference categorie -> compte pour ce
    compte utilisateur. Categorie vide -> ne fait rien (rien a apprendre)."""
    if not category or not account:
        return
    category = _normalize(category)
    if not category:
        return
    with get_db() as s:
        existing = (s.query(AccountPreference)
                   .filter_by(user_id=user_id, category=category).first())
        if existing:
            existing.account = account
        else:
            s.add(AccountPreference(user_id=user_id, category=category, account=account))


def get_account_overrides_map(user_id):
    """{categorie_normalisee: compte} pour ce compte, {} si aucune preference
    -- pret a etre passe comme category_account_map a journal_entry()."""
    if not user_id:
        return {}
    with get_db() as s:
        prefs = s.query(AccountPreference).filter_by(user_id=user_id).all()
        return {p.category: p.account for p in prefs}
