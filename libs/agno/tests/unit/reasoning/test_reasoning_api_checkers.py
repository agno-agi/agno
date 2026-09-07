"""Unit tests for API-based reasoning capability detection (Anthropic, Gemini, Ollama, OpenRouter, Moonshot).

These detectors query the provider API and fall back to substring/config checks when the API call
fails. The provider clients are mocked here so no network access is required.
"""

import agno.reasoning.moonshot as moonshot_mod
import agno.reasoning.ollama as ollama_mod
import agno.reasoning.openrouter as openrouter_mod
from agno.reasoning.anthropic import is_anthropic_reasoning_model
from agno.reasoning.gemini import is_gemini_reasoning_model
from agno.reasoning.moonshot import is_moonshot_reasoning_model
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
    model = ApiModel("Claude", "claude-opus-4-6", provider="Anthropic", client=client, thinking={"type": "enabled"})
    assert is_anthropic_reasoning_model(model) is True


def test_anthropic_thinking_supported_but_not_configured():
    """Thinking support alone is not enough: the reasoning agent never enables thinking itself, so
    an unconfigured model would stream back an empty thinking block."""
    client = _Client(models=_Models(retrieve=_Obj(capabilities={"thinking": {"supported": True}})))
    model = ApiModel("Claude", "claude-opus-4-6", provider="Anthropic", client=client)
    assert is_anthropic_reasoning_model(model) is False


def test_anthropic_api_thinking_not_supported():
    """The API can veto a model that was configured for thinking but cannot do it."""
    client = _Client(models=_Models(retrieve=_Obj(capabilities={"thinking": {"supported": False}})))
    model = ApiModel("Claude", "claude-haiku-legacy", provider="Anthropic", client=client, thinking={"type": "enabled"})
    assert is_anthropic_reasoning_model(model) is False


def test_anthropic_api_failure_falls_back_to_config():
    # Client raises -> fall back to "is thinking set on the instance".
    model_set = ApiModel("Claude", "claude-x", provider="Anthropic", raises=True, thinking={"type": "enabled"})
    assert is_anthropic_reasoning_model(model_set) is True
    model_unset = ApiModel("Claude", "claude-x", provider="Anthropic", raises=True)
    assert is_anthropic_reasoning_model(model_unset) is False


def test_anthropic_missing_capabilities_falls_back_to_config():
    """An SDK/response without the capabilities field must leave the configured value standing."""
    client = _Client(models=_Models(retrieve=_Obj(id="claude-x")))
    model = ApiModel("Claude", "claude-x", provider="Anthropic", client=client, thinking={"type": "enabled"})
    assert is_anthropic_reasoning_model(model) is True


def test_anthropic_unconfigured_skips_the_api_call():
    """Thinking is the cheap gate, so an unconfigured model must not pay for a network round-trip."""
    retrieved = []

    class _CountingModels:
        def retrieve(self, model_id):
            retrieved.append(model_id)
            return _Obj(capabilities={"thinking": {"supported": True}})

    model = ApiModel("Claude", "claude-x", provider="Anthropic", client=_Client(models=_CountingModels()))
    assert is_anthropic_reasoning_model(model) is False
    assert retrieved == []


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


# ============================================================================
# Moonshot (supports_reasoning on GET /v1/models)
# ============================================================================


def test_moonshot_api_reasoning_supported(monkeypatch):
    monkeypatch.setattr(
        moonshot_mod,
        "_fetch_moonshot_models",
        lambda model: {"kimi-k3": True, "kimi-k2.5": False},
    )
    assert is_moonshot_reasoning_model(ApiModel("MoonShot", "kimi-k3")) is True


def test_moonshot_api_reasoning_not_supported(monkeypatch):
    monkeypatch.setattr(
        moonshot_mod,
        "_fetch_moonshot_models",
        lambda model: {"kimi-k3": True, "kimi-k2.5": False},
    )
    # Present in catalog with supports_reasoning False -> False.
    assert is_moonshot_reasoning_model(ApiModel("MoonShot", "kimi-k2.5")) is False


def test_moonshot_catalog_empty_falls_back_to_substring(monkeypatch):
    # Empty catalog (fetch failed) -> substring fallback.
    monkeypatch.setattr(moonshot_mod, "_fetch_moonshot_models", lambda model: {})
    assert is_moonshot_reasoning_model(ApiModel("MoonShot", "kimi-k3")) is True
    assert is_moonshot_reasoning_model(ApiModel("MoonShot", "kimi-k2-thinking")) is True
    assert is_moonshot_reasoning_model(ApiModel("MoonShot", "kimi-k2.5")) is False


def test_moonshot_non_moonshot_model():
    assert is_moonshot_reasoning_model(ApiModel("OpenAIChat", "kimi-k3")) is False


# ============================================================================
# Detection caching and async detection
# ============================================================================


def _counting_manager(monkeypatch, model_id="openai/o3"):
    """Build a manager over an OpenRouter model, counting catalog fetches."""
    from agno.reasoning.manager import ReasoningConfig, ReasoningManager

    calls = []

    def _fetch(model):
        calls.append(model.id)
        return {"openai/o3": ["reasoning"], "openai/gpt-4o": []}

    monkeypatch.setattr(openrouter_mod, "_fetch_openrouter_models", _fetch)
    model = ApiModel("OpenRouter", model_id)
    return ReasoningManager(ReasoningConfig(reasoning_model=model)), model, calls


def test_detection_is_cached_across_calls(monkeypatch):
    """Detection hits the provider API, so repeated entry points must reuse the first result."""
    manager, model, calls = _counting_manager(monkeypatch)

    assert manager.is_native_reasoning_model(model) is True
    assert manager.is_native_reasoning_model(model) is True
    assert manager._detect_model_type(model) == "openrouter"

    assert len(calls) == 1


def test_detection_cache_is_keyed_by_model(monkeypatch):
    """A different model must not reuse the previous model's detection result."""
    manager, model, calls = _counting_manager(monkeypatch)

    assert manager._detect_model_type(model) == "openrouter"
    other = ApiModel("OpenRouter", "openai/gpt-4o")
    assert manager._detect_model_type(other) is None

    assert len(calls) == 2


async def test_async_detection_matches_sync_and_caches(monkeypatch):
    """The async variant returns the same answer and shares the cache with the sync path."""
    manager, model, calls = _counting_manager(monkeypatch)

    assert await manager.ais_native_reasoning_model(model) is True
    assert await manager._adetect_model_type(model) == "openrouter"
    assert manager.is_native_reasoning_model(model) is True

    assert len(calls) == 1


async def test_async_detection_does_not_block_event_loop(monkeypatch):
    """A slow provider lookup must not stall other coroutines on the loop."""
    import asyncio
    import time

    from agno.reasoning.manager import ReasoningConfig, ReasoningManager

    def _slow_fetch(model):
        time.sleep(0.5)
        return {}

    monkeypatch.setattr(openrouter_mod, "_fetch_openrouter_models", _slow_fetch)
    model = ApiModel("OpenRouter", "openai/o3")
    manager = ReasoningManager(ReasoningConfig(reasoning_model=model))

    ticks = 0

    async def heartbeat():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.05)
            ticks += 1

    beat = asyncio.create_task(heartbeat())
    await manager.ais_native_reasoning_model(model)
    beat.cancel()

    # A blocking call would leave the loop starved with zero heartbeats.
    assert ticks > 3


# ============================================================================
# Credential resolution for the catalog lookups
#
# These exercise the real _fetch_* functions and stub httpx instead. Mocking the fetch
# helpers away is what let a missing Authorization header go unnoticed: the Moonshot
# catalog endpoint rejects unauthenticated calls, so the lookup could never succeed.
# ============================================================================


def _capture_catalog_request(monkeypatch, module, payload):
    """Stub httpx.get inside `module` and record the headers the catalog lookup sends."""
    sent = {}

    def _fake_get(url, headers=None, timeout=None, **kwargs):
        sent["url"] = url
        sent["headers"] = headers or {}

        class _Response:
            def raise_for_status(self):
                return None

            def json(self):
                return payload

        return _Response()

    monkeypatch.setattr(module.httpx, "get", _fake_get)
    return sent


def test_moonshot_catalog_lookup_authenticates_from_env(monkeypatch):
    """MoonShot resolves its key lazily, so the detector must fall back to the environment."""
    monkeypatch.setenv("MOONSHOT_API_KEY", "sk-moonshot-env")
    payload = {"data": [{"id": "kimi-k2.5", "supports_reasoning": False}]}
    sent = _capture_catalog_request(monkeypatch, moonshot_mod, payload)

    model = ApiModel("MoonShot", "kimi-k2.5", base_url="https://api.moonshot.ai/v1", api_key=None)
    assert is_moonshot_reasoning_model(model) is False

    assert sent["headers"].get("Authorization") == "Bearer sk-moonshot-env"


def test_moonshot_explicit_api_key_wins_over_env(monkeypatch):
    monkeypatch.setenv("MOONSHOT_API_KEY", "sk-from-env")
    payload = {"data": [{"id": "kimi-k3", "supports_reasoning": True}]}
    sent = _capture_catalog_request(monkeypatch, moonshot_mod, payload)

    model = ApiModel("MoonShot", "kimi-k3", base_url="https://api.moonshot.ai/v1", api_key="sk-explicit")
    assert is_moonshot_reasoning_model(model) is True

    assert sent["headers"].get("Authorization") == "Bearer sk-explicit"


def test_openrouter_catalog_lookup_authenticates_from_env(monkeypatch):
    """OpenRouter resolves its key lazily too; its catalog is public, but send the key anyway."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-openrouter-env")
    payload = {"data": [{"id": "openai/o3", "supported_parameters": ["reasoning"]}]}
    sent = _capture_catalog_request(monkeypatch, openrouter_mod, payload)

    model = ApiModel("OpenRouter", "openai/o3", base_url="https://openrouter.ai/api/v1", api_key=None)
    assert is_openrouter_reasoning_model(model) is True

    assert sent["headers"].get("Authorization") == "Bearer sk-openrouter-env"


def test_catalog_lookup_sends_no_header_without_any_key(monkeypatch):
    """With no key anywhere, the public OpenRouter catalog is still queried unauthenticated."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    payload = {"data": [{"id": "openai/o3", "supported_parameters": ["reasoning"]}]}
    sent = _capture_catalog_request(monkeypatch, openrouter_mod, payload)

    model = ApiModel("OpenRouter", "openai/o3", base_url="https://openrouter.ai/api/v1", api_key=None)
    assert is_openrouter_reasoning_model(model) is True

    assert "Authorization" not in sent["headers"]
