"""Tests des regles metier. Lancer avec : pytest tests/ -q"""
from src.receipt import Receipt, filter_invoice_headers, find_invoice_number
from src.rules import check_line_sum, check_total, check_tax_rate, check_magnitude, audit
from src.accounting import journal_entry, is_balanced


# --- Post-traitement FACTURE : filtre des lignes d'en-tete (mode facture) ---

# Sortie Donut RÉELLE sur test_images/06_facture_francaise_design.webp (9 lignes).
_FACTURE_ITEMS = [
    {"name": "Facture n 12345", "quantity": None, "unit_price": None, "line_price": None},
    {"name": "CELIA NAUDIN", "quantity": None, "unit_price": None, "line_price": None},
    {"name": "hello@reallygreatsite.com", "quantity": None, "unit_price": None, "line_price": None},
    {"name": "123 Anywhere St., Any City DESCRIPTION PRX", "quantity": None, "unit_price": None, "line_price": 900.0},
    {"name": "Creation de logo", "quantity": None, "unit_price": None, "line_price": 900.0},
    {"name": "Conception d'un flyer", "quantity": None, "unit_price": None, "line_price": 300.0},
    {"name": "Carte de visite", "quantity": None, "unit_price": None, "line_price": 900.0},
    {"name": "Illustration personalisee", "quantity": None, "unit_price": None, "line_price": 1500.0},
    {"name": "Banniere publicitaire", "quantity": None, "unit_price": None, "line_price": 250.0},
]


def test_filter_facture_retire_entetes_sans_montant():
    kept = filter_invoice_headers(_FACTURE_ITEMS)
    names = [it["name"] for it in kept]
    # en-têtes du 1er tiers SANS montant -> retirés
    assert "CELIA NAUDIN" not in names
    assert "hello@reallygreatsite.com" not in names
    assert "Facture n 12345" not in names
    # les vrais articles (avec prix) restent
    for art in ["Creation de logo", "Conception d'un flyer", "Carte de visite",
                "Illustration personalisee", "Banniere publicitaire"]:
        assert art in names
    assert len(kept) == 6   # 3 en-têtes sans montant retirés sur 9


def test_filter_ticket_avec_prix_ne_retire_rien():
    """Un ticket normal (articles avec prix) n'est jamais amputé, même si la
    fonction est appelée : tout item du 1er tiers a un montant -> conservé."""
    items = [{"name": f"a{i}", "quantity": 1, "unit_price": 1000, "line_price": 1000} for i in range(5)]
    assert filter_invoice_headers(items) == items


def test_filter_liste_vide_ne_plante_pas():
    assert filter_invoice_headers([]) == []


def test_find_invoice_number():
    assert find_invoice_number("Facture n 12345") == "12345"      # sortie Donut RÉELLE
    assert find_invoice_number("Facture n°12345") == "12345"
    assert find_invoice_number("INVOICE #007") == "007"
    assert find_invoice_number("Numéro : 2024-88") == "2024-88"
    assert find_invoice_number("Nasi Goreng Ayam") is None        # pas de faux positif
    assert find_invoice_number("") is None
    assert find_invoice_number(None) is None


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


# --- R9 : plausibilite de MAGNITUDE (bug E11) ---

def test_magnitude_normale_ok():
    """Total coherent avec la somme des lignes : conforme."""
    r = make([10000, 15000], subtotal=25000, tax=2750, total=27750)
    assert check_magnitude(r) is True
    assert audit(r)["magnitude_ok"] is True


def test_magnitude_x100_detectee():
    """Total 100x la somme des lignes : hallucination probable -> anomalie.
    Reproduit le total 234 295 700 lu sur une vignette floue."""
    r = make([2000], subtotal=None, tax=None, total=234_295_700)
    assert check_magnitude(r) is False
    assert audit(r)["magnitude_ok"] is False
    assert audit(r)["anomaly"] is True        # l'audit global le signale


def test_magnitude_total_minuscule_detectee():
    """Total 100x plus petit que la somme des lignes : aussi une anomalie."""
    r = make([50000, 50000], subtotal=None, tax=None, total=100)
    assert check_magnitude(r) is False


def test_magnitude_donnees_manquantes_none():
    """Total OU somme des lignes absent -> None (logique 3 etats)."""
    sans_total = make([10000], subtotal=10000, tax=None, total=None)
    assert check_magnitude(sans_total) is None
    sans_lignes = Receipt(items=[], subtotal=10000, tax=None, total=11800)
    assert check_magnitude(sans_lignes) is None
