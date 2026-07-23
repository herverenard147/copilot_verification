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


def test_ecriture_equilibree():
    r = make([10000], subtotal=10000, tax=1800, total=11800)
    entry = journal_entry(r, category="transport", merchant="Total CI")
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
