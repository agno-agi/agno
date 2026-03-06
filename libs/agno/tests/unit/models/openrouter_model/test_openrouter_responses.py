from unittest.mock import patch

import pytest

from agno.exceptions import ModelAuthenticationError
from agno.models.openrouter import OpenRouterResponses


def test_openrouter_responses_default_config():
    """Test OpenRouterResponses default configuration."""
    with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
        model = OpenRouterResponses()

        assert model.id == "openai/gpt-oss-20b"
        assert model.name == "OpenRouterResponses"
        assert model.provider == "OpenRouter"
        assert model.base_url == "https://openrouter.ai/api/v1"
        assert model.store is False  # Stateless by default


def test_openrouter_responses_requires_api_key():
    """Test OpenRouterResponses raises error when no API key is provided."""
    model = OpenRouterResponses()

    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(ModelAuthenticationError, match="OPENROUTER_API_KEY not set"):
            model._get_client_params()


def test_openrouter_responses_api_key_from_env():
    """Test OpenRouterResponses uses API key from environment."""
    model = OpenRouterResponses()

    with patch.dict("os.environ", {"OPENROUTER_API_KEY": "env-api-key"}):
        params = model._get_client_params()
        assert params["api_key"] == "env-api-key"


def test_openrouter_responses_api_key_explicit():
    """Test OpenRouterResponses uses explicit API key over environment."""
    model = OpenRouterResponses(api_key="explicit-key")

    with patch.dict("os.environ", {"OPENROUTER_API_KEY": "env-key"}):
        params = model._get_client_params()
        assert params["api_key"] == "explicit-key"


def test_openrouter_responses_fallback_models():
    """Test OpenRouterResponses with fallback models configuration."""
    model = OpenRouterResponses(
        api_key="test-key",
        models=["anthropic/claude-sonnet-4", "google/gemini-2.0-flash"],
    )

    request_params = model.get_request_params()

    assert "extra_body" in request_params
    assert request_params["extra_body"]["models"] == [
        "anthropic/claude-sonnet-4",
        "google/gemini-2.0-flash",
    ]


def test_openrouter_responses_reasoning_model_detection():
    """Test OpenRouterResponses reasoning model detection."""
    # Non-reasoning model
    model = OpenRouterResponses(id="anthropic/claude-sonnet-4", api_key="test-key")
    assert model._using_reasoning_model() is False

    # OpenAI o3 model via OpenRouter
    model = OpenRouterResponses(id="openai/o3-mini", api_key="test-key")
    assert model._using_reasoning_model() is True

    # OpenAI o4 model via OpenRouter
    model = OpenRouterResponses(id="openai/o4-mini", api_key="test-key")
    assert model._using_reasoning_model() is True


def test_openrouter_responses_client_params():
    """Test OpenRouterResponses client parameters."""
    model = OpenRouterResponses(
        id="anthropic/claude-sonnet-4",
        api_key="test-key",
        timeout=30.0,
        max_retries=3,
    )

    params = model._get_client_params()

    assert params["api_key"] == "test-key"
    assert params["base_url"] == "https://openrouter.ai/api/v1"
    assert params["timeout"] == 30.0
    assert params["max_retries"] == 3
