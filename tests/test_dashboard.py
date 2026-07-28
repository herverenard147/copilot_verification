"""Graphiques du Tableau de bord : depenses par categorie et repartition des
totaux. Regressions du rendu casse observe sur donnees reelles (1 recu, 6
articles) : cadre categorie vide + 10 tranches quasi identiques.
"""
from src.receipt import Receipt
from src.session_store import UserSession

FLAGS = {"line_sum_ok": True, "total_ok": True, "tax_ok": True, "anomaly": False}


def _session_with(receipts):
    s = UserSession("test")
    for r, cat in receipts:
        s.add_receipt(r, category=cat, flags=FLAGS)
    return s


def test_categorie_unique_donne_une_barre():
    """Un recu dont les articles portent une categorie -> une barre par
    categorie reelle (pas de cadre vide)."""
    items = [{"name": "a", "quantity": 1, "unit_price": 1, "line_price": 100, "category": "Food"}]
    d = _session_with([(Receipt(items, total=100), "Food")]).get_dashboard_data()
    assert d["by_category"] == [{"category": "Food", "total": 100.0}]


def test_articles_sans_categorie_regroupes_non_categorise():
    """Articles sans categorie ET recu sans categorie : au lieu d'un cadre
    vide (groupby dropna qui supprimait le groupe None), on regroupe sous
    'Non categorise' -> une barre reste affichee."""
    items = [{"name": "X", "quantity": 1, "unit_price": 100, "line_price": 5580}]
    d = _session_with([(Receipt(items, total=5580), None)]).get_dashboard_data()
    assert d["by_category"] == [{"category": "Non catégorisé", "total": 5580.0}]


def test_total_unique_donne_une_seule_tranche():
    """Un seul montant distinct -> une seule tranche affichant CE montant,
    pas 10 tranches quasi identiques nees du binning force de numpy."""
    items = [{"name": "X", "quantity": 1, "unit_price": 1, "line_price": 5580, "category": "Food"}]
    d = _session_with([(Receipt(items, total=5580), "Food")]).get_dashboard_data()
    assert d["distribution"] == [{"range": "5 580", "count": 1}]


def test_peu_de_totaux_distincts_limite_les_tranches():
    """Le nombre de tranches ne depasse jamais le nombre de valeurs
    distinctes (min(10, n_distinct))."""
    recs = []
    for i, t in enumerate((100, 200, 300)):
        recs.append((Receipt([{"name": "x", "quantity": 1, "unit_price": 1,
                               "line_price": t, "category": "Food"}], total=t), "Food"))
    d = _session_with(recs).get_dashboard_data()
    assert len(d["distribution"]) == 3
    assert sum(x["count"] for x in d["distribution"]) == 3


def test_beaucoup_de_totaux_plafonne_a_dix_tranches():
    """A l'echelle demo (nombreux totaux distincts), on plafonne a 10
    tranches et tous les recus sont comptes."""
    recs = [(Receipt([{"name": "x", "quantity": 1, "unit_price": 1,
                       "line_price": t, "category": "Food"}], total=t), "Food")
            for t in range(1000, 1000 + 50 * 137, 137)]
    d = _session_with(recs).get_dashboard_data()
    assert len(d["distribution"]) == 10
    assert sum(x["count"] for x in d["distribution"]) == 50
