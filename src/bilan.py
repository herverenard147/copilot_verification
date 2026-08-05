"""Calcul du bilan comptable (Actif = Passif) a partir de DEUX sources :

1. Les lignes de journal derivees des reçus valides (charges, TVA, contrepartie
   tresorerie/fournisseur -- voir src/accounting.py:journal_entry, deja
   calculees par session_store.get_accounting_data()).
2. Les LedgerEntry importees ou saisies manuellement (src/models.py) :
   capital, immobilisations, stocks, ventes... tout ce qu'un reçu d'ACHAT ne
   peut structurellement pas fournir.

Sans (2), le bilan reste incomplet par construction : un reçu de dépense ne
dit rien du capital ni du chiffre d'affaires d'une entreprise. C'est pourquoi
l'import (src/import_ledger.py) n'est pas une fonctionnalite a part, mais la
piece qui rend ce bilan reellement exploitable au-dela d'un jouet.
"""
from src.accounting import CHART_OF_ACCOUNTS, classify_account


def _line_field(line, key):
    return line[key] if isinstance(line, dict) else getattr(line, key)


def _aggregate(lines):
    """{compte: (debit_total, credit_total)}."""
    balances = {}
    for line in lines:
        account = _line_field(line, "account")
        debit = _line_field(line, "debit") or 0.0
        credit = _line_field(line, "credit") or 0.0
        d, c = balances.get(account, (0.0, 0.0))
        balances[account] = (d + debit, c + credit)
    return balances


def compute_bilan(receipt_lines, ledger_entries):
    """receipt_lines : lignes de journal issues des reçus valides (dicts avec
    account/debit/credit, deja calculees). ledger_entries : LedgerEntry (ou
    tout objet portant .account/.debit/.credit), importees ou saisies
    manuellement. Renvoie un dict pret a etre serialise en JSON."""
    lines = list(receipt_lines) + list(ledger_entries)
    balances = _aggregate(lines)

    actif, passif = [], []
    total_charges = total_produits = 0.0
    for account, (debit, credit) in sorted(balances.items()):
        net = round(debit - credit, 2)
        side = classify_account(account)
        label = CHART_OF_ACCOUNTS.get(account, account)
        if side == "actif":
            if net:
                actif.append({"account": account, "label": label, "amount": net})
        elif side == "passif":
            if net:
                passif.append({"account": account, "label": label, "amount": round(-net, 2)})
        elif side == "resultat_charge":
            total_charges += net
        elif side == "resultat_produit":
            total_produits += -net

    resultat = round(total_produits - total_charges, 2)
    if resultat:
        passif.append({"account": "120", "label": CHART_OF_ACCOUNTS["120"], "amount": resultat})

    total_actif = round(sum(l["amount"] for l in actif), 2)
    total_passif = round(sum(l["amount"] for l in passif), 2)
    return {
        "actif": sorted(actif, key=lambda l: l["account"]),
        "passif": sorted(passif, key=lambda l: l["account"]),
        "total_actif": total_actif,
        "total_passif": total_passif,
        "balanced": abs(total_actif - total_passif) <= 0.01,
        "resultat_exercice": resultat,
        "total_charges": round(total_charges, 2),
        "total_produits": round(total_produits, 2),
    }
