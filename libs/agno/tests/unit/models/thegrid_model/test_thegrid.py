"""Unit tests for The Grid model class.

The Grid is an OpenAI-compatible inference market, so the class is a thin
OpenAILike subclass. These tests pin the defaults and the missing-key behavior
without any network access. (The to_dict/from_dict round-trip is covered
generically by ``test_provider_resolution.py`` via the provider registry.)
"""

import pytest

from agno.exceptions import ModelAuthenticationError
from agno.models.openai.like import OpenAILike
from agno.models.thegrid import TheGrid


def test_defaults():
    """Defaults match The Grid OpenAI-compatible endpoint."""
    model = TheGrid(api_key="test-key")
    assert isinstance(model, OpenAILike)
    assert model.id == "text-standard"
    assert model.name == "TheGrid"
    assert model.provider == "TheGrid"
    assert model.base_url == "https://api.thegrid.ai/v1"


def test_api_key_from_env(monkeypatch):
    """The API key is read from THEGRID_API_KEY when not passed explicitly."""
    monkeypatch.setenv("THEGRID_API_KEY", "env-key")
    assert TheGrid().api_key == "env-key"


def test_client_params_include_base_url():
    """Client params carry the configured key and base URL through to the SDK."""
    params = TheGrid(api_key="test-key")._get_client_params()
    assert params["api_key"] == "test-key"
    assert params["base_url"] == "https://api.thegrid.ai/v1"


def test_instrument_id_is_configurable():
    """Any instrument can be selected; ids name a market, not a fixed model."""
    model = TheGrid(id="agent-max", api_key="test-key")
    assert model.id == "agent-max"


def test_missing_api_key_raises(monkeypatch):
    """A missing API key raises ModelAuthenticationError rather than a client error."""
    monkeypatch.delenv("THEGRID_API_KEY", raising=False)
    with pytest.raises(ModelAuthenticationError):
        TheGrid(api_key=None)._get_client_params()
