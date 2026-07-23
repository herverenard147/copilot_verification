"""Petites fonctions partagees par tout le projet."""
import re


def clean_amount(raw):
    """Convertit un montant CORD en nombre.

    Sur les recus indonesiens, virgule et point separent les MILLIERS :
    "25,000" -> 25000.0   |   "Rp 108.900" -> 108900.0
    Retourne None si rien d'exploitable.
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    digits = re.sub(r"[^\d]", "", str(raw))   # on ne garde que les chiffres
    return float(digits) if digits else None


def ensure_list(x):
    """CORD encode 1 article comme un dict, plusieurs comme une liste.
    Cette fonction uniformise : on recoit TOUJOURS une liste."""
    if x is None:
        return []
    return x if isinstance(x, list) else [x]
