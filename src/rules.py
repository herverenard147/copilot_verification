"""Le controleur comptable : chaque regle repond OK ou signale une anomalie."""

TAX_RATES = {"ID": 0.11, "CI": 0.18}   # Indonesie (PPN), Cote d'Ivoire (TVA)


def check_line_sum(receipt, tolerance=0.02):
    """R1 : la somme des lignes doit valoir le sous-total (a 2% pres)."""
    s, sub = receipt.items_sum(), receipt.subtotal
    if s is None or sub in (None, 0):
        return None                      # pas assez d'infos pour juger
    return abs(s - sub) / sub <= tolerance


def check_total(receipt, tolerance=0.02):
    """R2 : sous-total + taxe doit valoir le total."""
    if None in (receipt.subtotal, receipt.total):
        return None
    expected = receipt.subtotal + (receipt.tax or 0)
    return abs(expected - receipt.total) / receipt.total <= tolerance


def check_tax_rate(receipt, country="ID", band=0.05):
    """R3 : le taux de taxe doit etre plausible pour le pays."""
    if not receipt.tax or not receipt.subtotal:
        return None
    rate = receipt.tax / receipt.subtotal
    return abs(rate - TAX_RATES[country]) <= band


def audit(receipt, country="ID"):
    """Passe toutes les regles et retourne les drapeaux."""
    results = {
        "line_sum_ok": check_line_sum(receipt),
        "total_ok": check_total(receipt),
        "tax_ok": check_tax_rate(receipt, country),
    }
    results["anomaly"] = any(v is False for v in results.values())
    return results
