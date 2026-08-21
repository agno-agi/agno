"""Unit tests for the Speko model class.

Speko is an OpenAI-compatible voice router, so the class is a thin OpenAILike
subclass. These tests pin the defaults and the missing-key behavior without any
network access. (The to_dict/from_dict round-trip is covered generically by
``test_provider_resolution.py`` via the provider registry.)
"""

from unittest.mock import patch

import pytest

from agno.exceptions import ModelAuthenticationError
from agno.models.openai.like import OpenAILike
from agno.models.speko import Speko


def test_defaults():
    """Defaults match the Speko OpenAI-compatible endpoint with benchmark routing."""
    model = Speko(api_key="test-key")
    assert isinstance(model, OpenAILike)
    assert model.id == "auto"
    assert model.name == "Speko"
    assert model.provider == "Speko"
    assert model.base_url == "https://api.speko.ai/v1"


def test_api_key_from_env(monkeypatch):
    """The API key is read from SPEKO_API_KEY when not passed explicitly."""
    monkeypatch.setenv("SPEKO_API_KEY", "env-key")
    model = Speko()
    params = model._get_client_params()
    assert model.api_key == "env-key"
    assert params["api_key"] == "env-key"


def test_pinned_model_id():
    """A pinned provider:model ID is kept verbatim instead of being re-parsed."""
    model = Speko(id="openai:gpt-4.1-mini", api_key="test-key")
    assert model.id == "openai:gpt-4.1-mini"


def test_client_params_include_base_url():
    """Client params carry the configured key and base URL through to the SDK."""
    params = Speko(api_key="test-key")._get_client_params()
    assert params["api_key"] == "test-key"
    assert params["base_url"] == "https://api.speko.ai/v1"


def test_missing_api_key_raises():
    """A missing API key raises ModelAuthenticationError rather than a client error."""
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(ModelAuthenticationError, match="SPEKO_API_KEY not set"):
            Speko(api_key=None)._get_client_params()
