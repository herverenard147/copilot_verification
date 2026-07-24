"""Le controleur comptable.

LOGIQUE A TROIS ETATS, essentielle :
  True  = conforme
  False = anomalie
  None  = information insuffisante pour juger
Confondre "pas d'info" et "anomalie" produirait des faux positifs massifs :
beaucoup de recus CORD n'ont pas de champ taxe.
"""

TAX_RATES = {"ID": 0.11, "CI": 0.18}   # Indonesie (PPN), Cote d'Ivoire (TVA)


def check_line_sum(receipt, tolerance=0.02):
    """R1 : la somme des lignes doit valoir le sous-total (a 2% pres)."""
    s, sub = receipt.items_sum(), receipt.subtotal
    if s is None or sub in (None, 0):
        return None
    return abs(s - sub) / sub <= tolerance


def check_total(receipt, tolerance=0.02):
    """R2 : sous-total + taxe doit valoir le total."""
    if receipt.subtotal is None or receipt.total in (None, 0):
        return None
    expected = receipt.subtotal + (receipt.tax or 0)
    return abs(expected - receipt.total) / receipt.total <= tolerance


def check_tax_rate(receipt, country="ID", band=0.05):
    """R3 : le taux de taxe doit etre plausible pour le pays."""
    if not receipt.tax or not receipt.subtotal:
        return None
    rate = receipt.tax / receipt.subtotal
    return abs(rate - TAX_RATES[country]) <= band


def check_magnitude(receipt, factor=50):
    """R9 : plausibilite de MAGNITUDE. Le total et la somme des lignes doivent
    rester dans un rapport raisonnable (facteur 50 par defaut).

    Anomalie si total > factor * somme_lignes OU total < somme_lignes / factor.
    Un total 100x superieur a la somme des lignes ne traduit pas un arrondi
    mais une HALLUCINATION (ex. total 234 295 700 Rp lu sur une vignette floue)
    ou une erreur d'OCR grossiere. Complementaire de R1/R2, qui comparent des
    ecarts fins : R9 attrape les ecarts d'ordre de grandeur.

    Retourne None si le total OU la somme des lignes manque (logique 3 etats).
    """
    total = receipt.total
    line_sum = receipt.items_sum()
    if total is None or line_sum is None or line_sum <= 0:
        return None
    return (line_sum / factor) <= total <= (factor * line_sum)


def audit(receipt, country="ID"):
    """Passe toutes les regles et retourne les drapeaux."""
    results = {
        "line_sum_ok": check_line_sum(receipt),
        "total_ok": check_total(receipt),
        "tax_ok": check_tax_rate(receipt, country),
        "magnitude_ok": check_magnitude(receipt),
    }
    results["anomaly"] = any(v is False for v in results.values())
    return results
