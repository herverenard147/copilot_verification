"""src/rate_limit.py : compteur à fenêtre glissante par (bucket, IP)."""
import pytest

from src import rate_limit


@pytest.fixture(autouse=True)
def _isolate():
    rate_limit.reset_all()
    yield
    rate_limit.reset_all()


def test_autorise_sous_la_limite():
    for _ in range(5):
        assert rate_limit.check("default", "1.2.3.4") is True


def test_refuse_au_dela_de_la_limite():
    max_requests, _ = rate_limit.LIMITS["extract"]
    for _ in range(max_requests):
        assert rate_limit.check("extract", "1.2.3.4") is True
    assert rate_limit.check("extract", "1.2.3.4") is False


def test_ips_isolees():
    max_requests, _ = rate_limit.LIMITS["extract"]
    for _ in range(max_requests):
        rate_limit.check("extract", "1.1.1.1")
    assert rate_limit.check("extract", "1.1.1.1") is False
    assert rate_limit.check("extract", "2.2.2.2") is True   # autre IP, pas affectée


def test_buckets_isoles():
    """Épuiser le bucket 'extract' ne doit pas affecter 'bilan_import'."""
    max_requests, _ = rate_limit.LIMITS["extract"]
    for _ in range(max_requests):
        rate_limit.check("extract", "1.2.3.4")
    assert rate_limit.check("extract", "1.2.3.4") is False
    assert rate_limit.check("bilan_import", "1.2.3.4") is True


def test_fenetre_glissante_expire(monkeypatch):
    import time as time_mod
    t = [1000.0]
    monkeypatch.setattr(time_mod, "time", lambda: t[0])
    max_requests, window = rate_limit.LIMITS["extract"]
    for _ in range(max_requests):
        rate_limit.check("extract", "1.2.3.4")
    assert rate_limit.check("extract", "1.2.3.4") is False
    t[0] += window + 1   # avance le temps au-delà de la fenêtre
    assert rate_limit.check("extract", "1.2.3.4") is True


def test_bucket_inconnu_utilise_default():
    max_requests, _ = rate_limit.LIMITS["default"]
    for _ in range(max_requests):
        assert rate_limit.check("bucket-jamais-vu", "1.2.3.4") is True
    assert rate_limit.check("bucket-jamais-vu", "1.2.3.4") is False
