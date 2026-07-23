"""Tests des regles metier. Lancer avec : pytest tests/ -q"""
from src.receipt import Receipt
from src.rules import check_line_sum, check_total, check_tax_rate, audit
from src.accounting import journal_entry, is_balanced


def make(prices, subtotal, tax, total):
    items = [{"name": f"a{i}", "quantity": 1, "unit_price": p, "line_price": p}
             for i, p in enumerate(prices)]
    return Receipt(items, subtotal, tax, total)


def test_recu_sain():
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
    assert audit(r)["anomaly"] is False


def test_nan_traite_comme_absent():
    """Le NaN de pandas ne doit pas passer pour une vraie valeur."""
    from src.utils import clean_amount
    assert clean_amount(float("nan")) is None


# --- Bug E8 : schema polymorphe a la RACINE (Donut peut renvoyer une liste) ---

def test_from_gt_parse_liste_a_la_racine():
    """token2json peut renvoyer une LISTE a la racine (photo inclinee) :
    on la fusionne au lieu de planter."""
    parse = [
        {"menu": [{"nm": "Nasi", "price": "25000"}]},
        {"total": {"total_price": "25000"}},
    ]
    r = Receipt.from_gt_parse(parse)          # ne doit PAS lever d'exception
    assert len(r.items) == 1
    assert r.items[0]["name"] == "Nasi"
    assert r.total == 25000.0


def test_from_gt_parse_type_inattendu_donne_recu_vide():
    for bad in ("n'importe quoi", 42, 3.14):
        r = Receipt.from_gt_parse(bad)
        assert r.items == []
        assert r.total is None and r.subtotal is None and r.tax is None


def test_from_gt_parse_none_donne_recu_vide():
    r = Receipt.from_gt_parse(None)
    assert r.items == []
    assert r.total is None


def test_audit_recu_vide_tous_none_sans_anomalie():
    r = Receipt.from_gt_parse(None)
    flags = audit(r, country="CI")
    assert flags["line_sum_ok"] is None
    assert flags["total_ok"] is None
    assert flags["tax_ok"] is None
    assert flags["anomaly"] is False          # "non verifiable" n'est PAS une anomalie


def test_journal_entry_recu_vide_ne_plante_pas():
    r = Receipt.from_gt_parse(None)
    entry = journal_entry(r, category=None)   # ne doit PAS lever d'exception
    assert entry == []
    assert is_balanced(entry) is True         # 0 == 0
