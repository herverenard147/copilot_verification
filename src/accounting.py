"""Ecritures comptables simplifiees (plan de comptes SYSCOHADA/OHADA).

Le marchand est ABSENT des annotations CORD (retire pour raisons legales) :
sans marchand identifie, on ne peut pas justifier une TVA deductible aupres
d'un fournisseur precis, donc on la considere par defaut comme NON
recuperable et on la reintegre dans la charge. C'est volontaire, pas un bug.
"""
import unicodedata
import pandas as pd

DISCLAIMER = (
    "Affectation comptable indicative, generee automatiquement a partir de "
    "regles simples. A valider par un professionnel (expert-comptable) avant "
    "toute utilisation officielle. Cet outil est une aide a la saisie, ce "
    "n'est PAS un logiciel de comptabilite certifie."
)

CHART_OF_ACCOUNTS = {
    "601": "Achats de marchandises",
    "605": "Autres achats",
    "6181": "Transport",
    "627": "Publicite, publications, relations publiques",
    "628": "Telecommunications",
    "638": "Autres charges externes",
    "4452": "TVA recuperable sur achats",
    "401": "Fournisseurs",
    "571": "Caisse",
    "521": "Banques",
}

DEFAULT_EXPENSE_ACCOUNT = "638"   # compte fourre-tout quand la categorie ne correspond a rien

# Mapping par defaut categorie (issue du clustering KMeans) -> compte 6xx.
# Volontairement editable : voir map_category_to_account(mapping=...).
DEFAULT_CATEGORY_ACCOUNTS = {
    "food": "601", "beverage": "601", "drinks": "601", "merchandise": "601", "grocery": "601",
    "transport": "6181", "fuel": "6181", "taxi": "6181",
    "advertising": "627", "reception": "627", "restaurant": "627", "hotel": "627",
    "telecom": "628", "communication": "628", "internet": "628",
    "supplies": "605", "office": "605", "stationery": "605",
}

PAYMENT_ACCOUNTS = {"cash": "571", "bank": "521", "credit": "401"}


def _normalize(text):
    """Minuscules, sans accents, pour une comparaison de categories robuste."""
    folded = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    return folded.strip().lower()


def map_category_to_account(category, mapping=None):
    """Categorie KMeans (texte libre) -> compte de charge 6xx.

    `mapping` optionnel : table personnalisee {categorie: compte} (ex. celle
    editee depuis l'ecran Reglages). Sans correspondance, retombe sur 638.
    """
    if not category:
        return DEFAULT_EXPENSE_ACCOUNT
    table = mapping if mapping is not None else DEFAULT_CATEGORY_ACCOUNTS
    key = _normalize(category)
    normalized_table = {_normalize(k): v for k, v in table.items()}
    if key in normalized_table:
        return normalized_table[key]
    for cat_key, account in normalized_table.items():
        if cat_key in key or key in cat_key:
            return account
    return DEFAULT_EXPENSE_ACCOUNT


def vat_recoverable(receipt, merchant=None):
    """Determine le montant de TVA deductible et pourquoi.

    Retourne (montant, raison). Cas frequent et VOULU : sans marchand
    identifie (champ absent de CORD), la TVA n'est PAS consideree
    recuperable -> (0.0, motif explicite).
    """
    if not merchant:
        return 0.0, "Fournisseur non identifie — TVA non recuperable"
    if not receipt.tax:
        return 0.0, "Aucune TVA identifiee sur ce recu"
    return float(receipt.tax), "TVA recuperable — fournisseur identifie"


def _resolve_amounts(receipt):
    """(total TTC, taxe) en comblant les trous quand c'est possible."""
    tax = float(receipt.tax) if receipt.tax else 0.0
    total = receipt.total
    if total is None:
        if receipt.subtotal is not None:
            total = receipt.subtotal + tax
        else:
            items_sum = receipt.items_sum()
            if items_sum is None:
                raise ValueError(
                    "Impossible de construire l'ecriture : total, subtotal et "
                    "les lignes d'articles sont tous vides pour ce recu."
                )
            total = items_sum + tax
    return float(total), tax


def journal_entry(receipt, category, payment_mode="cash", country="CI", merchant=None):
    """Construit l'ecriture comptable d'un recu -> liste de lignes
    {account, label, debit, credit}.

    Debit charge 6xx (HT si TVA recuperable, TTC sinon car la TVA non
    recuperable est REINTEGREE dans la charge), debit 4452 si TVA
    recuperable, credit 571/521/401 selon le mode de paiement, pour le TTC.
    L'ecriture reste equilibree par construction (voir is_balanced).
    """
    if payment_mode not in PAYMENT_ACCOUNTS:
        raise ValueError(
            f"Mode de paiement inconnu : {payment_mode!r} "
            f"(attendu : {list(PAYMENT_ACCOUNTS)})"
        )

    # Recu vide (aucun montant exploitable) : on ne construit pas d'ecriture,
    # mais on NE PLANTE PAS -- une liste vide, is_balanced([]) vaut True.
    if receipt.total is None and receipt.subtotal is None and receipt.items_sum() is None:
        return []

    total_ttc, tax = _resolve_amounts(receipt)
    recoverable, reason = vat_recoverable(receipt, merchant=merchant)
    recoverable = min(recoverable, tax)   # jamais plus que la taxe reellement lue
    charge_amount = total_ttc - recoverable   # HT si recuperable, TTC (reintegre) sinon

    account = map_category_to_account(category)
    merchant_label = merchant or "fournisseur non identifie"

    lines = [{
        "account": account,
        "label": f"{CHART_OF_ACCOUNTS.get(account, 'Charge')} — {merchant_label}",
        "debit": round(charge_amount, 2),
        "credit": 0.0,
    }]

    if recoverable > 0:
        lines.append({
            "account": "4452",
            "label": f"{CHART_OF_ACCOUNTS['4452']} — {merchant_label}",
            "debit": round(recoverable, 2),
            "credit": 0.0,
        })
    elif tax > 0:
        # TVA lue mais non recuperable : deja reintegree dans la charge ci-dessus.
        # On ne cree pas de ligne 4452, mais la raison reste tracable via vat_recoverable().
        pass

    credit_account = PAYMENT_ACCOUNTS[payment_mode]
    lines.append({
        "account": credit_account,
        "label": f"{CHART_OF_ACCOUNTS[credit_account]} — {merchant_label}",
        "debit": 0.0,
        "credit": round(total_ttc, 2),
    })

    return lines


def is_balanced(entry, tolerance=0.01):
    """Seule regle EXACTE du projet : total debits == total credits."""
    total_debit = sum(line["debit"] for line in entry)
    total_credit = sum(line["credit"] for line in entry)
    return abs(total_debit - total_credit) <= tolerance


def vat_summary(records):
    """Agrege la TVA sur plusieurs recus pour la carte comptable.

    `records` : liste de dicts {"tax": ..., "recoverable": ..., "reason": ...},
    typiquement construits en appelant vat_recoverable() par recu :
        recoverable, reason = vat_recoverable(r, merchant)
        records.append({"tax": r.tax or 0, "recoverable": recoverable, "reason": reason})

    Retourne le total recuperable, le total non recupere, et le detail des
    motifs de non-recuperation (decompte + montant par motif).
    """
    recoverable_total = 0.0
    non_recoverable_total = 0.0
    non_recoverable_count = 0
    reasons = {}

    for rec in records:
        tax = rec.get("tax") or 0.0
        recov = rec.get("recoverable") or 0.0
        reason = rec.get("reason", "")
        non_recov = tax - recov
        recoverable_total += recov
        if non_recov > 0:
            non_recoverable_total += non_recov
            non_recoverable_count += 1
            bucket = reasons.setdefault(reason, {"count": 0, "amount": 0.0})
            bucket["count"] += 1
            bucket["amount"] += non_recov

    return {
        "recoverable_total": round(recoverable_total, 2),
        "non_recoverable_total": round(non_recoverable_total, 2),
        "non_recoverable_count": non_recoverable_count,
        "non_recoverable_reasons": {
            k: {"count": v["count"], "amount": round(v["amount"], 2)}
            for k, v in reasons.items()
        },
    }


def expense_report(df_receipts, period_label):
    """Note de frais agregee HT/TVA/TTC sur une periode, depuis un
    DataFrame de recus (colonnes subtotal/tax/total, voir expenses.py)."""
    ttc = df_receipts["total"].fillna(0)
    tax = df_receipts["tax"].fillna(0)
    ht = ttc - tax
    return {
        "period": period_label,
        "n_receipts": int(len(df_receipts)),
        "total_ht": round(float(ht.sum()), 2),
        "total_tax": round(float(tax.sum()), 2),
        "total_ttc": round(float(ttc.sum()), 2),
    }


def export_journal_csv(entries, path):
    """Ecrit une liste plate de lignes d'ecriture (concatener plusieurs
    journal_entry() si besoin) dans un CSV pret pour Excel / import compta."""
    pd.DataFrame(entries).to_csv(path, index=False)
