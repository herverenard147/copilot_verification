"""Tests des regles metier. Lancer avec : pytest tests/ -q"""
from src.receipt import Receipt
from src.rules import check_line_sum, check_total, check_tax_rate, audit


def make(items_prices, subtotal, tax, total):
    items = [{"name": f"a{i}", "quantity": 1, "unit_price": p, "line_price": p}
             for i, p in enumerate(items_prices)]
    return Receipt(items, subtotal, tax, total)


def test_receipt_sain():
    r = make([10000, 15000], subtotal=25000, tax=2750, total=27750)
    assert audit(r)["anomaly"] is False

def test_sous_total_faux():
    r = make([10000, 15000], subtotal=30000, tax=2750, total=32750)
    assert check_line_sum(r) is False

def test_total_faux():
    r = make([10000], subtotal=10000, tax=1100, total=99999)
    assert check_total(r) is False

def test_taxe_ivoirienne():
    r = make([10000], subtotal=10000, tax=1800, total=11800)
    assert check_tax_rate(r, country="CI") is True
    assert check_tax_rate(r, country="ID") is False

def test_champs_manquants():
    r = make([10000], subtotal=None, tax=None, total=None)
    assert check_total(r) is None       # "je ne sais pas", PAS "anomalie"
