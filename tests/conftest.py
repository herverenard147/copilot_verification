"""Fixtures partagées par toute la suite. src/rate_limit.py est un état
GLOBAL de process (comme session_store._sessions) : sans reset entre
chaque test, les requêtes cumulées de toute la suite (tous les tests
partagent le même hôte "testclient") finissent par dépasser la limite
"default" et font échouer des tests plus tard dans la suite pour une
raison n'ayant rien à voir avec ce qu'ils testent."""
import pytest

from src import rate_limit


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    rate_limit.reset_all()
    yield
    rate_limit.reset_all()
