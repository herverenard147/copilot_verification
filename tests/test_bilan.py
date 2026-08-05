"""src/bilan.py : calcul Actif/Passif à partir de lignes de journal (reçus)
et d'écritures importées/manuelles (LedgerEntry)."""
from src.bilan import compute_bilan


def L(account, debit=0.0, credit=0.0):
    return {"account": account, "debit": debit, "credit": credit}


def test_bilan_vide():
    b = compute_bilan([], [])
    assert b["actif"] == []
    assert b["passif"] == []
    assert b["total_actif"] == 0
    assert b["total_passif"] == 0
    assert b["balanced"] is True


def test_capital_investi_en_banque_bilan_equilibre():
    """Ecriture d'ouverture minimale : capital 100000 -> banque 100000.
    Aucune charge, aucun produit -> resultat nul, pas de ligne 120."""
    entries = [L("101", credit=100000), L("521", debit=100000)]
    b = compute_bilan([], entries)
    assert b["balanced"] is True
    assert b["total_actif"] == 100000
    assert b["total_passif"] == 100000
    accounts_actif = {l["account"] for l in b["actif"]}
    accounts_passif = {l["account"] for l in b["passif"]}
    assert "521" in accounts_actif
    assert "101" in accounts_passif
    assert "120" not in accounts_passif   # pas de resultat -> pas de ligne


def test_achat_recu_reduit_tresorerie_et_alimente_le_resultat():
    """Un reçu déjà comptabilisé (charge 601 + contrepartie caisse 571) doit
    faire apparaître un résultat négatif (perte) qui équilibre le bilan,
    même sans aucune écriture importée."""
    receipt_lines = [L("601", debit=1000), L("571", credit=1000)]
    b = compute_bilan(receipt_lines, [])
    assert b["total_charges"] == 1000
    assert b["total_produits"] == 0
    assert b["resultat_exercice"] == -1000
    assert b["balanced"] is True
    # la caisse (571) est negative (1000 depenses sans tresorerie de depart) :
    # côté actif avec un montant négatif -- le déséquilibre réel se voit,
    # ce n'est pas masqué.
    passif_120 = next(l for l in b["passif"] if l["account"] == "120")
    assert passif_120["amount"] == -1000


def test_import_deseequilibre_detecte():
    """Une écriture importée à moitié (une seule ligne, pas de contrepartie)
    doit rendre le bilan visiblement déséquilibré -- signal utile, pas caché."""
    entries = [L("101", credit=50000)]   # pas de contrepartie actif
    b = compute_bilan([], entries)
    assert b["balanced"] is False
    assert b["total_actif"] != b["total_passif"]


def test_charges_et_produits_absents_du_bilan_direct():
    """Les comptes 6xx/7xx n'apparaissent jamais tels quels dans actif/passif
    -- ils sont absorbés dans le résultat de l'exercice."""
    receipt_lines = [L("601", debit=500), L("571", credit=500)]
    entries = [L("701", credit=800), L("521", debit=800)]
    b = compute_bilan(receipt_lines, entries)
    accounts = {l["account"] for l in b["actif"]} | {l["account"] for l in b["passif"]}
    assert "601" not in accounts
    assert "701" not in accounts
    assert b["resultat_exercice"] == 300   # 800 produits - 500 charges
    assert b["balanced"] is True


def test_ledger_entries_objets_avec_attributs():
    """compute_bilan doit aussi accepter des objets (LedgerEntry SQLAlchemy),
    pas seulement des dicts."""
    class FakeEntry:
        def __init__(self, account, debit=0.0, credit=0.0):
            self.account, self.debit, self.credit = account, debit, credit

    entries = [FakeEntry("101", credit=1000), FakeEntry("521", debit=1000)]
    b = compute_bilan([], entries)
    assert b["balanced"] is True
    assert b["total_actif"] == 1000
