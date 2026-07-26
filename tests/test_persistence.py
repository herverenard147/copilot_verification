"""Persistance des sessions via SQLite (hors depot). Lancer : pytest tests/ -q

On verifie : aller-retour sauvegarde/rechargement (donc redemarrage), robustesse
(base absente/corrompue -> etat vide, pas de crash), mode demo JAMAIS persiste,
update/delete persistes (survivent au redemarrage), et surtout que data/*.csv
n'est JAMAIS touche (comparaison par hash)."""
import hashlib
from pathlib import Path

import pytest

from src import session_store
from src.receipt import Receipt

FLAGS = {"line_sum_ok": True, "total_ok": True, "tax_ok": None, "anomaly": False}


def _receipt(name="Café", price=1000, category="food"):
    return Receipt(items=[{"name": name, "quantity": 1, "unit_price": price,
                           "line_price": price, "category": category}],
                   subtotal=price, tax=None, total=price)


@pytest.fixture(autouse=True)
def _isolate():
    session_store.reset_all()
    session_store.disable_persistence()
    yield
    session_store.reset_all()
    session_store.disable_persistence()


def _restart(db_path):
    """Simule un redemarrage du process : vide la memoire, rouvre la base."""
    session_store.reset_all()
    session_store.init_persistence(str(db_path))


def test_aller_retour_survit_a_un_redemarrage(tmp_path):
    f = tmp_path / "sessions.db"
    session_store.init_persistence(str(f))
    session_store.get_session("sA").add_receipt(_receipt("ZORGLUB"), "food", FLAGS)
    assert f.exists()                                   # base creee, sauvegarde immediate

    _restart(f)
    reloaded = session_store.get_session("sA")
    assert len(reloaded.receipts) == 1
    assert reloaded.items[0]["name"] == "ZORGLUB"


def test_base_absente_demarre_vide(tmp_path):
    session_store.init_persistence(str(tmp_path / "pas_encore.db"))   # creee, ne plante pas
    assert session_store.get_session("neuve").is_empty()


def test_base_corrompue_demarre_vide(tmp_path):
    f = tmp_path / "sessions.db"
    f.write_bytes(b"ceci n'est pas une base SQLite du tout \x00\x01\x02")
    session_store.init_persistence(str(f))              # ne doit PAS lever
    assert session_store.get_session("neuve").is_empty()
    # la base recreee reste fonctionnelle apres coup
    session_store.get_session("neuve").add_receipt(_receipt("APRES_CORRUPTION"), "food", FLAGS)
    _restart(f)
    assert session_store.get_session("neuve").items[0]["name"] == "APRES_CORRUPTION"


def test_mode_demo_jamais_persiste(tmp_path):
    f = tmp_path / "sessions.db"
    session_store.init_persistence(str(f))
    session_store.get_session("real").add_receipt(_receipt(), "food", FLAGS)      # vrai reçu
    session_store.get_session("demo").load_demo(
        [{"receipt_id": 0, "total": 100, "n_items": 0}], [])                      # mode demo
    session_store._save()

    _restart(f)
    assert not session_store.get_session("real").is_empty()   # vrai reçu conserve
    assert session_store.get_session("demo").is_empty()       # demo NON persiste


def test_update_et_delete_survivent_au_redemarrage(tmp_path):
    f = tmp_path / "sessions.db"
    session_store.init_persistence(str(f))
    s = session_store.get_session("sB")
    rid_a = s.add_receipt(_receipt("A", 1000), "food", FLAGS)
    rid_b = s.add_receipt(_receipt("B", 2000), "food", FLAGS)
    s.update_receipt(rid_a, _receipt("A", 5000), "food", FLAGS)   # A : 1000 -> 5000
    s.delete_receipt(rid_b)                                        # B supprime

    _restart(f)
    s2 = session_store.get_session("sB")
    assert len(s2.receipts) == 1                                  # B bien parti
    assert int(s2.receipts[0]["receipt_id"]) == rid_a
    assert s2.receipts[0]["total"] == 5000                        # update persiste
    assert all(int(r["receipt_id"]) != rid_b for r in s2.receipts)


def test_data_csv_jamais_touche(tmp_path):
    csvs = sorted(Path("data").glob("*.csv"))
    before = {p.name: hashlib.md5(p.read_bytes()).hexdigest() for p in csvs}

    f = tmp_path / "sessions.db"
    session_store.init_persistence(str(f))
    s = session_store.get_session("sC")
    for _ in range(3):                                   # plusieurs cycles d'ecriture
        s.add_receipt(_receipt(), "food", FLAGS)
    s.update_receipt(0, _receipt("X", 9000), "food", FLAGS)
    s.delete_receipt(0)
    s.clear()

    after = {p.name: hashlib.md5(p.read_bytes()).hexdigest() for p in csvs}
    assert before == after                               # aucun CSV du corpus modifie
