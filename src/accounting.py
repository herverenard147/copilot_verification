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
    # Comptes de bilan (classes 1/2/3/4/7) : jamais produits par un recu
    # d'achat seul (voir src/bilan.py), mais necessaires pour interpreter un
    # import externe (src/import_ledger.py) ou une saisie manuelle -- capital,
    # immobilisations, ventes... tout ce qu'un reçu ne peut pas fournir.
    "101": "Capital",
    "106": "Reserves",
    "120": "Resultat de l'exercice",
    "16": "Emprunts et dettes financieres",
    "21": "Immobilisations corporelles",
    "27": "Immobilisations financieres",
    "31": "Stocks de marchandises",
    "411": "Clients",
    "4457": "TVA collectee",
    "701": "Ventes de marchandises",
    "706": "Prestations de services",
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
    # Labels reels des clusters KMeans du corpus CORD (nommes d'apres un article
    # representatif). Sans ces cles, 100% des recus tombaient sur 638 (fallback)
    # et l'ecriture n'avait qu'une ligne. "autre" reste volontairement en 638.
    "autre": "638",
    "6001-plastic bag s": "605",        # emballage -> autres achats
    "twist donut": "601", "original hugarian": "601", "nasi putih": "601",
    "tripple cheese": "601", "iced tea": "601", "gong gibab": "601",
    "mineral water": "601",
}

PAYMENT_ACCOUNTS = {"cash": "571", "bank": "521", "credit": "401"}

# Cote du bilan pour les comptes qui n'appartiennent clairement qu'a un seul
# cote (necessaire pour les comptes de tiers, classe 4, qui melange creances
# ET dettes selon le compte precis -- 401 fournisseur est une dette, 411
# client est une creance, la classe seule ne suffit pas a trancher).
ACCOUNT_SIDE = {
    "101": "passif", "106": "passif", "120": "passif", "16": "passif",
    "401": "passif", "4457": "passif",
    "21": "actif", "27": "actif", "31": "actif",
    "411": "actif", "4452": "actif", "521": "actif", "571": "actif",
}


def classify_account(account):
    """Cote du bilan pour un compte : "actif", "passif", "resultat_charge"
    (classe 6) ou "resultat_produit" (classe 7, alimente le resultat, jamais
    directement une ligne du bilan). Compte connu -> ACCOUNT_SIDE (gere les
    exceptions comme 401/411 en classe 4). Compte inconnu (import externe,
    compte non repertorie) -> repli sur le 1er chiffre du numero, jamais un
    echec : mieux vaut une classification prudente qu'un import qui plante."""
    if account in ACCOUNT_SIDE:
        return ACCOUNT_SIDE[account]
    first = (str(account) or "")[:1]
    if first == "1":
        return "passif"
    if first in ("2", "3", "5"):
        return "actif"
    if first == "6":
        return "resultat_charge"
    if first == "7":
        return "resultat_produit"
    return "actif"   # classe 4 inconnue ou compte non reconnu : creance par defaut


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


def _charge_line(account, merchant_label, amount):
    return {
        "account": account,
        "label": f"{CHART_OF_ACCOUNTS.get(account, 'Charge')} — {merchant_label}",
        "debit": round(amount, 2),
        "credit": 0.0,
    }


def _charge_lines(receipt, receipt_category, charge_amount, merchant_label, category_account_map=None):
    """Repartit le montant de charge en UNE ligne PAR COMPTE distinct.

    Chaque article est mappe vers un compte via SA categorie individuelle
    (`item["category"]`), avec repli sur la categorie globale du recu si
    l'article n'en a pas. `category_account_map` (optionnel) surcharge
    DEFAULT_CATEGORY_ACCOUNTS -- typiquement les preferences apprises d'un
    utilisateur (voir src/account_preferences.py). Le montant de charge est
    ventile entre les comptes au PRORATA des prix de ligne, la derniere ligne
    absorbant l'arrondi pour que la somme des debits egale exactement
    `charge_amount` (is_balanced preserve).

    Chaque ligne porte aussi "categories" (les categories qui y contribuent) :
    permet a l'appelant, si l'utilisateur surcharge manuellement le compte
    d'une ligne, de retenir "categorie -> compte" pour la prochaine fois
    (voir api.py, _capture_account_preference).

    Repli historique : si aucun article chiffre (pas de line_price), une seule
    ligne sur la categorie globale du recu -- ancien comportement, ne plante pas.
    """
    # FUSION, pas remplacement : category_account_map({} pour un anonyme)
    # ne doit JAMAIS eclipser DEFAULT_CATEGORY_ACCOUNTS -- map_category_to_account
    # utilise `mapping` tel quel des qu'il n'est pas None, donc un dict vide
    # desactiverait silencieusement tout le mapping par defaut.
    mapping = {**DEFAULT_CATEGORY_ACCOUNTS, **(category_account_map or {})}

    priced = [(it.get("category") or receipt_category, it["line_price"])
              for it in receipt.items if it.get("line_price") is not None]
    items_sum = sum(lp for _, lp in priced)

    if not priced or items_sum <= 0:
        line = _charge_line(map_category_to_account(receipt_category, mapping=mapping),
                            merchant_label, charge_amount)
        line["categories"] = [receipt_category] if receipt_category else []
        return [line]

    by_account = {}
    by_account_categories = {}
    for category, line_price in priced:
        account = map_category_to_account(category, mapping=mapping)
        by_account[account] = by_account.get(account, 0.0) + line_price
        by_account_categories.setdefault(account, set()).add(category)

    lines, allocated = [], 0.0
    accounts = sorted(by_account)                      # ordre stable et deterministe
    for i, account in enumerate(accounts):
        if i < len(accounts) - 1:
            amount = round(charge_amount * by_account[account] / items_sum, 2)
            allocated += amount
        else:
            amount = round(charge_amount - allocated, 2)   # derniere ligne : absorbe l'arrondi
        line = _charge_line(account, merchant_label, amount)
        line["categories"] = sorted(by_account_categories[account])
        lines.append(line)
    return lines


def journal_entry(receipt, category, payment_mode="cash", country="CI", merchant=None,
                  category_account_map=None):
    """Construit l'ecriture comptable d'un recu -> liste de lignes
    {account, label, debit, credit, categories}.

    Debit charge 6xx (HT si TVA recuperable, TTC sinon car la TVA non
    recuperable est REINTEGREE dans la charge), debit 4452 si TVA
    recuperable, credit 571/521/401 selon le mode de paiement, pour le TTC.
    L'ecriture reste equilibree par construction (voir is_balanced).

    `category_account_map` (optionnel) : {categorie: compte} qui prend le pas
    sur DEFAULT_CATEGORY_ACCOUNTS pour les lignes de charge -- typiquement les
    preferences apprises d'un utilisateur a partir de ses surcharges passees.
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

    merchant_label = merchant or "fournisseur non identifie"

    # Une ligne de charge PAR COMPTE distinct : chaque article part sur le compte
    # de SA categorie (un reçu peut melanger marchandises et transport).
    lines = _charge_lines(receipt, category, charge_amount, merchant_label, category_account_map)

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


# Comptes de charge modifiables manuellement (les seuls : la contrepartie
# 571/521/401 et la TVA 4452 restent des consequences automatiques).
CHARGE_ACCOUNTS = ["601", "605", "6181", "627", "628", "638"]


def apply_account_overrides(entry, overrides):
    """SURCHARGE MANUELLE du compte d'une ligne de charge (Tache 4).

    `overrides` : {index_ligne_de_charge (str): compte}. On ne change QUE le
    compte, jamais le montant -> l'equilibre debit/credit est preserve
    mecaniquement (is_balanced reste vrai). Les lignes touchees sont marquees
    'manual' pour la tracabilite. N'affecte PAS map_category_to_account : c'est
    une surcharge par recu, pas un changement du comportement par defaut.
    Modifie et renvoie `entry`."""
    if not overrides:
        return entry
    charge_i = 0
    for line in entry:
        if line["debit"] > 0 and line["account"] != "4452":
            new_account = overrides.get(str(charge_i))
            if new_account and new_account in CHART_OF_ACCOUNTS and new_account != line["account"]:
                parts = line["label"].split(" — ", 1)
                merchant_label = parts[1] if len(parts) > 1 else "fournisseur non identifie"
                line["account"] = new_account
                line["label"] = f"{CHART_OF_ACCOUNTS[new_account]} — {merchant_label}"
                line["manual"] = True
            charge_i += 1
    return entry


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
