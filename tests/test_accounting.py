"""Tests du module comptable. Lancer avec : pytest tests/ -q"""
import pytest

from src.receipt import Receipt
from src.accounting import (
    journal_entry, is_balanced, vat_recoverable, map_category_to_account,
    vat_summary, CHART_OF_ACCOUNTS, PAYMENT_ACCOUNTS, DEFAULT_EXPENSE_ACCOUNT,
)


def make(items_prices, subtotal, tax, total):
    items = [{"name": f"a{i}", "quantity": 1, "unit_price": p, "line_price": p}
              for i, p in enumerate(items_prices)]
    return Receipt(items, subtotal, tax, total)


def make_categorized(items):
    """items : liste de (prix, categorie) -> Receipt avec categorie PAR article."""
    its = [{"name": f"a{i}", "quantity": 1, "unit_price": p, "line_price": p, "category": c}
           for i, (p, c) in enumerate(items)]
    montant = sum(p for p, _ in items)
    return Receipt(its, subtotal=montant, tax=None, total=montant)


def test_ecriture_equilibree():
    r = make([10000], subtotal=10000, tax=1800, total=11800)
    entry = journal_entry(r, category="transport", merchant="Total CI")
    assert is_balanced(entry) is True


# --- Ecriture multi-comptes : une ligne de charge par compte distinct ---

def test_ecriture_multi_categories_deux_lignes_de_charge():
    # 60 000 marchandises (food -> 601) + 40 000 transport (-> 6181), sans TVA
    r = make_categorized([(60000, "food"), (40000, "transport")])
    entry = journal_entry(r, category="food", merchant="Fournisseur X")
    charge = {l["account"]: l["debit"] for l in entry if l["debit"] > 0}
    assert charge["601"] == 60000.0            # marchandises sur leur compte
    assert charge["6181"] == 40000.0           # transport sur le sien
    assert len([l for l in entry if l["account"] in ("601", "6181")]) == 2
    assert is_balanced(entry) is True          # debits == credit malgre la ventilation


def test_ecriture_categorie_unique_reste_une_ligne():
    r = make_categorized([(50000, "transport"), (30000, "transport")])
    entry = journal_entry(r, category="transport", merchant="X")
    charge = [l for l in entry if l["debit"] > 0 and l["account"] != "4452"]
    assert len(charge) == 1                     # un seul compte -> une seule ligne (correct)
    assert charge[0]["account"] == "6181" and charge[0]["debit"] == 80000.0
    assert is_balanced(entry) is True


def test_ecriture_sans_categorie_article_fallback_638():
    # articles sans champ category ET categorie de recu absente -> repli 638
    r = make([50000, 30000], subtotal=80000, tax=None, total=80000)
    entry = journal_entry(r, category=None, merchant="X")   # ne doit PAS planter
    charge = [l for l in entry if l["debit"] > 0]
    assert len(charge) == 1 and charge[0]["account"] == DEFAULT_EXPENSE_ACCOUNT
    assert is_balanced(entry) is True


def test_ecriture_multi_categories_avec_tva_reste_equilibree():
    # meme repartition mais avec TVA recuperable (fournisseur identifie)
    its = [{"name": "m", "quantity": 1, "unit_price": 60000, "line_price": 60000, "category": "food"},
           {"name": "t", "quantity": 1, "unit_price": 40000, "line_price": 40000, "category": "transport"}]
    r = Receipt(its, subtotal=100000, tax=18000, total=118000)
    entry = journal_entry(r, category="food", merchant="Fournisseur X")
    charge = {l["account"]: l["debit"] for l in entry if l["account"] in ("601", "6181")}
    # charge HT (118000 - 18000 = 100000) ventilee 60/40
    assert charge["601"] == 60000.0 and charge["6181"] == 40000.0
    assert [l for l in entry if l["account"] == "4452"][0]["debit"] == 18000.0
    assert is_balanced(entry) is True


def test_ecriture_desequilibree_detectee():
    entry = [
        {"account": "638", "label": "Charge", "debit": 100.0, "credit": 0.0},
        {"account": "571", "label": "Caisse", "debit": 0.0, "credit": 90.0},
    ]
    assert is_balanced(entry) is False


def test_tva_recuperable_avec_fournisseur():
    r = make([10000], subtotal=10000, tax=1800, total=11800)
    montant, raison = vat_recoverable(r, merchant="Total CI")
    assert montant == 1800.0
    assert "recuperable" in raison.lower()

    entry = journal_entry(r, category="transport", merchant="Total CI")
    tva_lines = [l for l in entry if l["account"] == "4452"]
    charge_lines = [l for l in entry if l["account"] == "6181"]
    assert len(tva_lines) == 1
    assert tva_lines[0]["debit"] == 1800.0
    assert charge_lines[0]["debit"] == 10000.0   # HT, la TVA est isolee
    assert is_balanced(entry) is True


def test_tva_non_recuperable_sans_fournisseur_reintegration():
    r = make([10000], subtotal=10000, tax=1800, total=11800)
    montant, raison = vat_recoverable(r, merchant=None)
    assert montant == 0.0
    assert "non identifie" in raison.lower()

    entry = journal_entry(r, category="transport", merchant=None)
    tva_lines = [l for l in entry if l["account"] == "4452"]
    charge_lines = [l for l in entry if l["account"] == "6181"]
    assert tva_lines == []                        # pas de ligne TVA deductible
    assert charge_lines[0]["debit"] == 11800.0     # TTC reintegre dans la charge
    assert is_balanced(entry) is True              # l'ecriture reste equilibree


def test_mapping_categorie_et_fallback():
    assert map_category_to_account("transport") == "6181"
    assert map_category_to_account("categorie totalement inconnue") == DEFAULT_EXPENSE_ACCOUNT
    assert map_category_to_account(None) == DEFAULT_EXPENSE_ACCOUNT


def test_mapping_labels_kmeans_cord():
    """Les 9 labels reels des clusters CORD sont mappes (sinon tout -> 638)."""
    assert map_category_to_account("ICED TEA") == "601"
    assert map_category_to_account("Mineral Water") == "601"
    assert map_category_to_account("TWIST DONUT") == "601"
    assert map_category_to_account("Original Hugarian ") == "601"      # espace final géré
    assert map_category_to_account("6001-Plastic Bag S") == "605"      # emballage
    assert map_category_to_account("autre") == "638"
    assert map_category_to_account("un cluster jamais vu") == DEFAULT_EXPENSE_ACCOUNT  # fallback robuste


def test_recu_0_audit_multi_comptes_601_605_638():
    """Reçu #0 de l'audit (7 catégories) -> écriture à plusieurs comptes."""
    it = [("6001-Plastic Bag S", 100000), ("GONG GIBAB", 50000), ("ICED TEA", 30000),
          ("NASI PUTIH", 40000), ("Original Hugarian ", 20000), ("TWIST DONUT", 60000),
          ("autre", 10000)]
    items = [{"name": n, "quantity": 1, "unit_price": p, "line_price": p, "category": c}
             for i, (c, p) in enumerate(it) for n in [f"a{i}"]]
    total = sum(p for _, p in it)
    r = Receipt(items, subtotal=total, tax=None, total=total)
    entry = journal_entry(r, category="autre", merchant=None)
    accounts = {l["account"] for l in entry if l["debit"] > 0}
    assert {"601", "605", "638"}.issubset(accounts)   # au moins ces 3 comptes de charge
    assert is_balanced(entry) is True

    mapping_perso = {"boissons": "605"}
    assert map_category_to_account("boissons", mapping=mapping_perso) == "605"
    assert map_category_to_account("transport", mapping=mapping_perso) == DEFAULT_EXPENSE_ACCOUNT


def test_recu_sans_tva():
    r = make([10000], subtotal=10000, tax=None, total=10000)
    montant, raison = vat_recoverable(r, merchant="Total CI")
    assert montant == 0.0
    assert "aucune tva" in raison.lower()

    entry = journal_entry(r, category="transport", merchant="Total CI")
    assert [l for l in entry if l["account"] == "4452"] == []
    assert is_balanced(entry) is True


def test_3_modes_de_paiement_creditent_le_bon_compte():
    r = make([10000], subtotal=10000, tax=1800, total=11800)
    for mode, compte_attendu in PAYMENT_ACCOUNTS.items():
        entry = journal_entry(r, category="transport", payment_mode=mode, merchant="Total CI")
        ligne_credit = [l for l in entry if l["credit"] > 0][0]
        assert ligne_credit["account"] == compte_attendu
        assert is_balanced(entry) is True

    with pytest.raises(ValueError):
        journal_entry(r, category="transport", payment_mode="virement_mystere")


def test_vat_summary_agrege_recuperable_et_motifs():
    records = [
        {"tax": 1800, "recoverable": 1800.0, "reason": "TVA recuperable — fournisseur identifie"},
        {"tax": 2000, "recoverable": 0.0, "reason": "Fournisseur non identifie — TVA non recuperable"},
        {"tax": 0, "recoverable": 0.0, "reason": "Aucune TVA identifiee sur ce recu"},
    ]
    summary = vat_summary(records)
    assert summary["recoverable_total"] == 1800.0
    assert summary["non_recoverable_total"] == 2000.0
    assert summary["non_recoverable_count"] == 1
    assert "Fournisseur non identifie — TVA non recuperable" in summary["non_recoverable_reasons"]
