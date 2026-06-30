"""Unit tests for API-based reasoning capability detection (Anthropic, Gemini, Ollama, OpenRouter).

These detectors query the provider API and fall back to substring/config checks when the API call
fails. The provider clients are mocked here so no network access is required.
"""

import agno.reasoning.ollama as ollama_mod
import agno.reasoning.openrouter as openrouter_mod
from agno.reasoning.anthropic import is_anthropic_reasoning_model
from agno.reasoning.gemini import is_gemini_reasoning_model
from agno.reasoning.ollama import is_ollama_reasoning_model
from agno.reasoning.openrouter import is_openrouter_reasoning_model


class ApiModel:
    """Mock model whose class name and get_client() return value are configurable."""

    def __init__(self, class_name, model_id="", client=None, raises=False, **kwargs):
        self.__class__.__name__ = class_name
        self.id = model_id
        self._client = client
        self._raises = raises
        for key, value in kwargs.items():
            setattr(self, key, value)

    def get_client(self):
        if self._raises:
            raise RuntimeError("client unavailable")
        return self._client


# ----------------------------------------------------------------------------
# Helpers to build fake provider clients
# ----------------------------------------------------------------------------


class _Models:
    def __init__(self, retrieve=None, get=None):
        self._retrieve = retrieve
        self._get = get

    def retrieve(self, model_id):  # Anthropic
        return self._retrieve

    def get(self, model):  # Gemini
        return self._get


class _Client:
    def __init__(self, models=None, show=None):
        self.models = models
        self._show = show

    def show(self, model_id):  # Ollama
        return self._show


class _Obj:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


# ============================================================================
# Anthropic (capabilities.thinking.supported)
# ============================================================================


def test_anthropic_api_thinking_supported():
    client = _Client(models=_Models(retrieve=_Obj(capabilities={"thinking": {"supported": True}})))
    model = ApiModel("Claude", "claude-opus-4-6", provider="Anthropic", client=client)
    assert is_anthropic_reasoning_model(model) is True


def test_anthropic_api_thinking_not_supported():
    client = _Client(models=_Models(retrieve=_Obj(capabilities={"thinking": {"supported": False}})))
    model = ApiModel("Claude", "claude-haiku-legacy", provider="Anthropic", client=client)
    assert is_anthropic_reasoning_model(model) is False


def test_anthropic_api_failure_falls_back_to_config():
    # Client raises -> fall back to "is thinking set on the instance".
    model_set = ApiModel("Claude", "claude-x", provider="Anthropic", raises=True, thinking={"type": "enabled"})
    assert is_anthropic_reasoning_model(model_set) is True
    model_unset = ApiModel("Claude", "claude-x", provider="Anthropic", raises=True)
    assert is_anthropic_reasoning_model(model_unset) is False


def test_anthropic_non_anthropic_provider_short_circuits():
    model = ApiModel("Claude", "claude-x", provider="VertexAI", raises=True)
    assert is_anthropic_reasoning_model(model) is False


# ============================================================================
# Gemini (thinking field)
# ============================================================================


def test_gemini_api_thinking_true():
    client = _Client(models=_Models(get=_Obj(thinking=True)))
    model = ApiModel("Gemini", "gemini-3-pro", client=client)
    assert is_gemini_reasoning_model(model) is True


def test_gemini_api_thinking_false():
    client = _Client(models=_Models(get=_Obj(thinking=False)))
    model = ApiModel("Gemini", "gemini-some-flash", client=client)
    assert is_gemini_reasoning_model(model) is False


def test_gemini_api_failure_falls_back_to_substring():
    # Client raises -> fall back to version substring check.
    model = ApiModel("Gemini", "gemini-2.5-pro", raises=True)
    assert is_gemini_reasoning_model(model) is True
    model_old = ApiModel("Gemini", "gemini-1.5-pro", raises=True)
    assert is_gemini_reasoning_model(model_old) is False


# ============================================================================
# Ollama ("thinking" in capabilities)
# ============================================================================


def test_ollama_api_thinking_capability(monkeypatch):
    monkeypatch.setattr(ollama_mod, "_fetch_ollama_capabilities", lambda model: ["completion", "tools", "thinking"])
    assert is_ollama_reasoning_model(ApiModel("Ollama", "minimax-m3:cloud")) is True


def test_ollama_api_no_thinking_capability(monkeypatch):
    monkeypatch.setattr(ollama_mod, "_fetch_ollama_capabilities", lambda model: ["completion", "tools"])
    assert is_ollama_reasoning_model(ApiModel("Ollama", "plain-model")) is False


def test_ollama_api_failure_falls_back_to_substring(monkeypatch):
    # Fetch returns None (API/SDK failure) -> substring fallback.
    monkeypatch.setattr(ollama_mod, "_fetch_ollama_capabilities", lambda model: None)
    assert is_ollama_reasoning_model(ApiModel("Ollama", "qwen3:8b")) is True
    assert is_ollama_reasoning_model(ApiModel("Ollama", "llama3.2:3b")) is False


# ============================================================================
# OpenRouter ("reasoning" in supported_parameters)
# ============================================================================


def test_openrouter_api_reasoning_supported(monkeypatch):
    monkeypatch.setattr(
        openrouter_mod,
        "_fetch_openrouter_models",
        lambda model: {"openai/o3": ["reasoning", "tools"], "openai/gpt-4o": ["tools"]},
    )
    assert is_openrouter_reasoning_model(ApiModel("OpenRouter", "openai/o3")) is True


def test_openrouter_api_reasoning_not_supported(monkeypatch):
    monkeypatch.setattr(
        openrouter_mod,
        "_fetch_openrouter_models",
        lambda model: {"openai/gpt-4o": ["tools"]},
    )
    # Present in catalog without "reasoning" -> False.
    assert is_openrouter_reasoning_model(ApiModel("OpenRouter", "openai/gpt-4o")) is False


def test_openrouter_catalog_empty_falls_back_to_substring(monkeypatch):
    # Empty catalog (fetch failed) -> substring fallback.
    monkeypatch.setattr(openrouter_mod, "_fetch_openrouter_models", lambda model: {})
    assert is_openrouter_reasoning_model(ApiModel("OpenRouter", "deepseek/deepseek-r1")) is True
    assert is_openrouter_reasoning_model(ApiModel("OpenRouter", "openai/gpt-4o")) is False


def test_openrouter_non_openrouter_model():
    assert is_openrouter_reasoning_model(ApiModel("OpenAIChat", "openai/o3")) is False
