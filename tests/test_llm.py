"""src/llm.py : selection du modele vision Groq a partir des modalites REELLES
renvoyees par l'API (input_modalities), jamais d'un nom fige -- la gamme Groq
change regulierement, un nom code en dur a deja provoque des 404
model_not_found silencieux en production (voir select_vision_model)."""
import src.llm as llm


def _fake_models(*specs):
    """specs : [(id, modalities), ...] -> forme de list_available_models()."""
    return [{"id": i, "input_modalities": list(m)} for i, m in specs]


def test_select_vision_model_prefere_un_modele_connu(monkeypatch):
    monkeypatch.setattr(llm, "list_available_models", lambda provider="groq": _fake_models(
        ("meta-llama/llama-4-scout-17b-16e-instruct", ["text", "image"]),
        ("qwen/qwen3.8-27b", ["text", "image"]),
        ("llama-3.3-70b-versatile", ["text"]),
    ))
    assert llm.select_vision_model("groq") == "meta-llama/llama-4-scout-17b-16e-instruct"


def test_select_vision_model_bascule_sur_nouveau_modele_inconnu(monkeypatch):
    """La gamme Groq a change : aucun des modeles PREFERES (noms fige) n'est
    plus present, mais un tout autre modele vision existe -- il doit quand
    meme etre choisi, jamais None juste parce que son nom est inconnu."""
    monkeypatch.setattr(llm, "list_available_models", lambda provider="groq": _fake_models(
        ("qwen/qwen3.8-27b", ["text", "image"]),
        ("llama-3.3-70b-versatile", ["text"]),
    ))
    assert llm.select_vision_model("groq") == "qwen/qwen3.8-27b"


def test_select_vision_model_none_sans_aucun_modele_vision(monkeypatch):
    monkeypatch.setattr(llm, "list_available_models", lambda provider="groq": _fake_models(
        ("llama-3.3-70b-versatile", ["text"]),
        ("whisper-large-v3", ["audio"]),
    ))
    assert llm.select_vision_model("groq") is None


def test_select_vision_model_respecte_la_surcharge_env(monkeypatch):
    monkeypatch.setattr(llm, "list_available_models", lambda provider="groq": _fake_models(
        ("meta-llama/llama-4-scout-17b-16e-instruct", ["text", "image"]),
        ("mon-modele-prefere", ["text", "image"]),
    ))
    monkeypatch.setenv("GROQ_VISION_MODEL", "mon-modele-prefere")
    assert llm.select_vision_model("groq") == "mon-modele-prefere"


def test_classify_models_separe_vision_et_texte(monkeypatch):
    monkeypatch.setattr(llm, "list_available_models", lambda provider="groq": _fake_models(
        ("qwen/qwen3.8-27b", ["text", "image"]),
        ("llama-3.3-70b-versatile", ["text"]),
        ("whisper-large-v3", ["audio"]),
    ))
    groups = llm.classify_models("groq")
    assert groups["vision"] == ["qwen/qwen3.8-27b"]
    assert set(groups["text"]) == {"llama-3.3-70b-versatile", "whisper-large-v3"}
