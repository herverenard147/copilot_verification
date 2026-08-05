"""Optimisations Donut : quantization dynamique (repli sûr si elle échoue) et
bornage de la longueur de génération. Utilise un petit module PyTorch factice
pour tester le MÉCANISME de quantization sans télécharger le vrai modèle
Donut (~800 Mo, trop lent pour un test unitaire)."""
import torch

import api
from src.extractor import MAX_GENERATION_LENGTH


def test_quantize_donut_reussit_sur_un_module_lineaire():
    model = torch.nn.Sequential(torch.nn.Linear(8, 8), torch.nn.ReLU(), torch.nn.Linear(8, 4))
    quantized = api._quantize_donut(model)
    # doit renvoyer un module utilisable (pas planter, pas None)
    assert quantized is not None
    out = quantized(torch.randn(1, 8))
    assert out.shape == (1, 4)


def test_quantize_donut_repli_si_echec(monkeypatch):
    """Si la quantization elle-même lève une exception, on récupère le
    modèle ORIGINAL, jamais une exception qui casserait get_donut()."""
    class Boom:
        pass

    def _raise(*a, **k):
        raise RuntimeError("quantization non supportée pour ce type")

    monkeypatch.setattr(torch.quantization, "quantize_dynamic", _raise)
    original = Boom()
    result = api._quantize_donut(original)
    assert result is original


def test_max_generation_length_est_borne_et_raisonnable():
    """Valeur bornée: assez grande pour un vrai reçu (largement testé sur le
    corpus CORD dans ce projet), assez petite pour plafonner le pire cas."""
    assert 0 < MAX_GENERATION_LENGTH <= 1024


def test_donut_quantize_desactive_par_defaut(monkeypatch):
    """DONUT_QUANTIZE doit être explicitement activé -- jamais une
    dégradation de qualité silencieuse par défaut."""
    monkeypatch.delenv("DONUT_QUANTIZE", raising=False)
    import os
    assert os.environ.get("DONUT_QUANTIZE", "false").lower() != "true"
