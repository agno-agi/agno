"""Unit tests for the Runcrate model class.

Runcrate is an OpenAI-compatible model provider, so the class is a thin OpenAILike
subclass. These tests pin the defaults and the missing-key behavior without any
network access.
"""

import pytest

from agno.exceptions import ModelAuthenticationError
from agno.models.openai.like import OpenAILike
from agno.models.runcrate import Runcrate
from agno.models.utils import get_model, get_model_from_dict


def test_runcrate_defaults():
    """Defaults match the Runcrate OpenAI-compatible endpoint."""
    model = Runcrate(api_key="test-key")
    assert isinstance(model, OpenAILike)
    assert model.id == "deepseek-ai/DeepSeek-V4.1-Flash"
    assert model.name == "Runcrate"
    assert model.provider == "Runcrate"
    assert model.base_url == "https://api.runcrate.com/v1"


def test_runcrate_initialization_with_api_key():
    model = Runcrate(id="deepseek-ai/DeepSeek-V4.1-Flash", api_key="test-api-key")
    assert model.id == "deepseek-ai/DeepSeek-V4.1-Flash"
    assert model.api_key == "test-api-key"
    assert model.base_url == "https://api.runcrate.com/v1"


def test_runcrate_api_key_from_env(monkeypatch):
    """The API key is read from RUNCRATE_API_KEY when not passed explicitly."""
    monkeypatch.setenv("RUNCRATE_API_KEY", "env-key")
    model = Runcrate()
    assert model.api_key == "env-key"
    client_params = model._get_client_params()
    assert client_params["api_key"] == "env-key"
    assert client_params["base_url"] == "https://api.runcrate.com/v1"


def test_runcrate_client_params():
    """Client params carry the configured key and base URL through to the SDK."""
    model = Runcrate(id="deepseek-ai/DeepSeek-V4.1-Flash", api_key="test-api-key")
    client_params = model._get_client_params()
    assert client_params["api_key"] == "test-api-key"
    assert client_params["base_url"] == "https://api.runcrate.com/v1"


def test_runcrate_missing_api_key_raises(monkeypatch):
    """A missing API key raises ModelAuthenticationError."""
    monkeypatch.delenv("RUNCRATE_API_KEY", raising=False)
    model = Runcrate(api_key=None)
    with pytest.raises(ModelAuthenticationError) as exc_info:
        model._get_client_params()
    assert "RUNCRATE_API_KEY not set" in str(exc_info.value.message)


def test_runcrate_resolves_from_string_syntax():
    model = get_model("runcrate:deepseek-ai/DeepSeek-V4.1-Flash")
    assert isinstance(model, Runcrate)
    assert model.id == "deepseek-ai/DeepSeek-V4.1-Flash"


def test_runcrate_round_trips_through_dict():
    model = Runcrate(id="deepseek-ai/DeepSeek-V4.1-Flash", api_key="test-api-key")
    rebuilt = get_model_from_dict(model.to_dict())
    assert isinstance(rebuilt, Runcrate)
    assert rebuilt.id == "deepseek-ai/DeepSeek-V4.1-Flash"
