"""Limitation de debit (rate limiting) en memoire, par IP -- frein contre un
flot de requetes (legitime ou non) qui saturerait le serveur. Pas de
nouvelle dependance lourde (pas de Redis/slowapi) : un compteur a fenetre
glissante, meme style que l'anti brute-force de src/auth.py.

LIMITE CONNUE, assumee : etat en memoire du process, comme session_store.py
et src/jobs.py -- pas partage entre plusieurs instances. Suffisant pour une
seule instance (le mode de deploiement actuel) ; deplacer vers un backend
partage (Redis) serait necessaire pour un vrai scaling horizontal.
"""
import threading
import time

_lock = threading.Lock()
_hits = {}   # (bucket, identifiant) -> [timestamps des requetes recentes]

# (requetes max, fenetre en secondes). "default" s'applique a TOUT /api/*
# (borne l'usage global) ; les autres bornent EN PLUS un endpoint couteux
# specifique (verifies tous les deux, voir api.py).
LIMITS = {
    "default": (120, 60),        # 120 requetes/min/IP sur l'API en general
    "extract": (10, 60),         # upload + extraction : couteux CPU/memoire
    "bilan_import": (10, 60),    # parsing de fichier : couteux
}


def check(bucket, identifier):
    """True si la requete est autorisee (et l'enregistre aussitot), False
    si la limite du bucket est deja atteinte pour cet identifiant (IP)."""
    max_requests, window = LIMITS.get(bucket, LIMITS["default"])
    key = (bucket, identifier)
    now = time.time()
    with _lock:
        hits = [t for t in _hits.get(key, []) if now - t < window]
        if len(hits) >= max_requests:
            _hits[key] = hits
            return False
        hits.append(now)
        _hits[key] = hits
        return True


def reset_all():
    """Vide le registre (tests uniquement)."""
    with _lock:
        _hits.clear()
