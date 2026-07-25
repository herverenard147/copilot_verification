"""Persistance legere des sessions (hors depot). Lancer : pytest tests/ -q

On verifie : aller-retour sauvegarde/rechargement, robustesse (fichier absent/
corrompu -> etat vide), mode demo NON persiste, et surtout que data/*.csv
n'est JAMAIS touche (comparaison par hash avant/apres)."""
import hashlib
import json
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


def test_aller_retour_survit_a_un_redemarrage(tmp_path):
    f = tmp_path / "sessions.json"
    session_store.init_persistence(str(f))
    session_store.get_session("sA").add_receipt(_receipt("ZORGLUB"), "food", FLAGS)
    assert f.exists()                                  # sauvegarde immediate

    # simule un redemarrage : on vide la memoire puis on recharge depuis le fichier
    session_store.reset_all()
    session_store.init_persistence(str(f))
    reloaded = session_store.get_session("sA")
    assert len(reloaded.receipts) == 1
    assert reloaded.items[0]["name"] == "ZORGLUB"


def test_fichier_absent_demarre_vide(tmp_path):
    session_store.init_persistence(str(tmp_path / "n_existe_pas.json"))  # ne plante pas
    assert session_store.get_session("neuve").is_empty()


def test_fichier_corrompu_demarre_vide(tmp_path):
    f = tmp_path / "sessions.json"
    f.write_text("{ ceci n'est pas du JSON valide", encoding="utf-8")
    session_store.init_persistence(str(f))              # ne doit PAS lever
    assert session_store.get_session("neuve").is_empty()


def test_mode_demo_non_persiste(tmp_path):
    f = tmp_path / "sessions.json"
    session_store.init_persistence(str(f))
    session_store.get_session("real").add_receipt(_receipt(), "food", FLAGS)   # vrai reçu
    session_store.get_session("demo").load_demo(
        [{"receipt_id": 0, "total": 100, "n_items": 0}], [])                   # demo
    session_store._save()
    saved = json.loads(f.read_text(encoding="utf-8"))
    assert "real" in saved and "demo" not in saved      # demo exclu, vrai reçu gardé


def test_data_csv_jamais_touche(tmp_path):
    csvs = sorted(Path("data").glob("*.csv"))
    before = {p.name: hashlib.md5(p.read_bytes()).hexdigest() for p in csvs}

    f = tmp_path / "sessions.json"
    session_store.init_persistence(str(f))
    s = session_store.get_session("sB")
    for _ in range(3):                                   # plusieurs cycles d'ecriture
        s.add_receipt(_receipt(), "food", FLAGS)
    s.clear()

    after = {p.name: hashlib.md5(p.read_bytes()).hexdigest() for p in csvs}
    assert before == after                               # aucun CSV du corpus modifie
