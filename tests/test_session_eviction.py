"""evict_idle_sessions() : purge les sessions abandonnées (mémoire process
qui, sinon, ne se vide jamais tant que le server tourne -- fuite mémoire
lente sous trafic soutenu). Ne doit JAMAIS perdre de vrais reçus."""
import time

import pytest

from src import session_store
from src.receipt import Receipt

FLAGS = {"line_sum_ok": True, "total_ok": True, "tax_ok": None, "anomaly": False}


def _receipt():
    return Receipt(items=[{"name": "x", "quantity": 1, "unit_price": 100, "line_price": 100}],
                   subtotal=100, tax=None, total=100)


@pytest.fixture(autouse=True)
def _isolate():
    session_store.reset_all()
    session_store.disable_persistence()
    yield
    session_store.reset_all()
    session_store.disable_persistence()


def _age(session_id, seconds_ago):
    session_store._sessions[session_id].last_accessed = time.time() - seconds_ago


def test_session_vide_et_inactive_evincee():
    session_store.get_session("empty1")
    _age("empty1", session_store.IDLE_TTL_SECONDS + 10)
    evicted = session_store.evict_idle_sessions()
    assert evicted == 1
    assert "empty1" not in session_store._sessions


def test_session_recente_pas_evincee():
    session_store.get_session("recent1")
    # pas vieillie : last_accessed reste "maintenant"
    evicted = session_store.evict_idle_sessions()
    assert evicted == 0
    assert "recent1" in session_store._sessions


def test_session_demo_inactive_evincee_meme_avec_des_recus():
    s = session_store.get_session("demo1")
    s.load_demo([{"receipt_id": 0, "n_items": 1, "items_sum": 100, "subtotal": 100,
                  "tax": None, "total": 100, "line_sum_ok": True, "total_ok": True,
                  "tax_ok": None, "anomaly": False, "category": "food", "merchant": None}], [])
    assert s.demo_mode is True
    _age("demo1", session_store.IDLE_TTL_SECONDS + 10)
    evicted = session_store.evict_idle_sessions()
    assert evicted == 1


def test_session_avec_vrais_recus_jamais_evincee():
    """Le cas important : une session inactive mais avec de VRAIS reçus
    persistés ne doit jamais être évincée -- il n'y a pas de mécanisme pour
    la recharger à la demande, l'évincer perdrait des données visibles."""
    s = session_store.get_session("real1")
    s.add_receipt(_receipt(), "food", FLAGS)
    assert s.is_empty() is False
    assert s.demo_mode is False
    _age("real1", session_store.IDLE_TTL_SECONDS + 10)
    evicted = session_store.evict_idle_sessions()
    assert evicted == 0
    assert "real1" in session_store._sessions
    assert len(session_store._sessions["real1"].receipts) == 1


def test_get_session_rafraichit_last_accessed():
    session_store.get_session("touch1")
    _age("touch1", session_store.IDLE_TTL_SECONDS + 10)
    session_store.get_session("touch1")   # ré-accès -> ne doit plus être éligible
    evicted = session_store.evict_idle_sessions()
    assert evicted == 0
    assert "touch1" in session_store._sessions


def test_ttl_personnalise():
    session_store.get_session("custom1")
    _age("custom1", 100)
    assert session_store.evict_idle_sessions(ttl_seconds=50) == 1
