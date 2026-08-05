"""session_store.py : cache Redis partagé (init_redis) contre un VRAI Redis
(pas un mock) -- c'est la pièce qui permet à deux instances de voir la même
session. Ignoré automatiquement si aucun Redis n'est joignable (voir
TEST_REDIS_URL / pytest.importorskip)."""
import os

import pytest

redis = pytest.importorskip("redis")

from src import session_store  # noqa: E402
from src.receipt import Receipt  # noqa: E402

TEST_REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://127.0.0.1:6390")
FLAGS = {"line_sum_ok": True, "total_ok": True, "tax_ok": None, "anomaly": False}


def _redis_available():
    try:
        client = redis.from_url(TEST_REDIS_URL, socket_connect_timeout=1)
        client.ping()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _redis_available(), reason="Redis de test non joignable")


def _receipt(name="Café", price=1000):
    return Receipt(items=[{"name": name, "quantity": 1, "unit_price": price, "line_price": price}],
                   subtotal=price, tax=None, total=price)


@pytest.fixture(autouse=True)
def _isolate():
    session_store.reset_all()
    session_store.disable_persistence()
    session_store.init_redis(TEST_REDIS_URL)
    yield
    session_store.reset_all()
    session_store.close_redis()


def test_redis_configure_devient_la_source_de_verite():
    assert session_store._redis is not None


def test_recu_visible_sans_partager_le_dict_local():
    """Simule DEUX instances : une session écrite, puis le dict _sessions
    LOCAL vidé (simule un process B qui n'a jamais vu cette session) --
    get_session() doit quand même la retrouver, via Redis."""
    s = session_store.get_session("cross-instance-1")
    s.add_receipt(_receipt(), "food", FLAGS)

    session_store._sessions.clear()   # simule "une autre instance" : rien en mémoire locale

    s2 = session_store.get_session("cross-instance-1")
    assert len(s2.receipts) == 1
    assert s2.receipts[0]["total"] == 1000


def test_modification_propagee_entre_deux_lectures():
    s = session_store.get_session("propag-1")
    s.add_receipt(_receipt("A", 100), "food", FLAGS)
    session_store._sessions.clear()

    s2 = session_store.get_session("propag-1")
    s2.add_receipt(_receipt("B", 200), "food", FLAGS)
    session_store._sessions.clear()

    s3 = session_store.get_session("propag-1")
    assert len(s3.receipts) == 2
    noms = {r["receipt_id"] for r in s3.receipts}
    assert noms == {0, 1}


def test_mode_demo_partage_entre_instances():
    """Le mode démo DOIT être partagé via Redis (contrairement à SQLite qui
    ne le persiste jamais) -- sinon il casse dès qu'une requête suivante
    atterrit sur une autre instance."""
    s = session_store.get_session("demo-cross")
    s.load_demo([{"receipt_id": 0, "n_items": 1, "items_sum": 100, "subtotal": 100,
                  "tax": None, "total": 100, "line_sum_ok": True, "total_ok": True,
                  "tax_ok": None, "anomaly": False, "category": "food", "merchant": None}], [])
    session_store._sessions.clear()

    s2 = session_store.get_session("demo-cross")
    assert s2.demo_mode is True
    assert len(s2.receipts) == 1


def test_suppression_propagee():
    s = session_store.get_session("del-cross")
    s.add_receipt(_receipt(), "food", FLAGS)
    session_store._sessions.clear()

    s2 = session_store.get_session("del-cross")
    assert s2.delete_receipt(0) is True
    session_store._sessions.clear()

    s3 = session_store.get_session("del-cross")
    assert s3.is_empty() is True


def test_drop_session_retire_de_redis():
    session_store.get_session("drop-1").add_receipt(_receipt(), "food", FLAGS)
    session_store.drop_session("drop-1")
    session_store._sessions.clear()
    s = session_store.get_session("drop-1")
    assert s.is_empty() is True   # recréée vide, pas les données d'avant


def test_repli_memoire_locale_si_redis_indisponible():
    """init_redis avec une URL invalide -> repli silencieux, comportement
    historique préservé (jamais une exception qui casse le démarrage)."""
    session_store.init_redis("redis://127.0.0.1:1")   # port fermé
    assert session_store._redis is None
    s = session_store.get_session("repli-1")
    s.add_receipt(_receipt(), "food", FLAGS)
    assert len(session_store.get_session("repli-1").receipts) == 1
