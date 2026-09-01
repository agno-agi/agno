"""Unit tests for the TrustedRouter model class.

TrustedRouter is an OpenAI-compatible router, so the class is a thin OpenAILike
subclass. These tests pin the defaults and the missing-key behavior without any
network access. (The to_dict/from_dict round-trip is covered generically by
``test_provider_resolution.py`` via the provider registry.)
"""

import pytest

from agno.exceptions import ModelAuthenticationError
from agno.models.openai.like import OpenAILike
from agno.models.trustedrouter import TrustedRouter


def test_defaults():
    """Defaults match the TrustedRouter OpenAI-compatible endpoint."""
    model = TrustedRouter(api_key="test-key")
    assert isinstance(model, OpenAILike)
    assert model.id == "trustedrouter/zdr"
    assert model.name == "TrustedRouter"
    assert model.provider == "TrustedRouter"
    assert model.base_url == "https://api.trustedrouter.com/v1"


def test_api_key_from_env(monkeypatch):
    """The API key is read from TRUSTEDROUTER_API_KEY when not passed explicitly."""
    monkeypatch.setenv("TRUSTEDROUTER_API_KEY", "env-key")
    assert TrustedRouter().api_key == "env-key"


def test_client_params_include_base_url():
    """Client params carry the configured key and base URL through to the SDK."""
    params = TrustedRouter(api_key="test-key")._get_client_params()
    assert params["api_key"] == "test-key"
    assert params["base_url"] == "https://api.trustedrouter.com/v1"


def test_missing_api_key_raises(monkeypatch):
    """A missing API key raises ModelAuthenticationError rather than a client error."""
    monkeypatch.delenv("TRUSTEDROUTER_API_KEY", raising=False)
    with pytest.raises(ModelAuthenticationError):
        TrustedRouter(api_key=None)._get_client_params()
