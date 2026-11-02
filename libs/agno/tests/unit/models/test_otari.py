import os
from unittest.mock import patch

import pytest

from agno.exceptions import ModelAuthenticationError
from agno.models.otari import Otari
from agno.models.utils import get_model, get_model_from_dict


def test_otari_initialization_with_api_key():
    model = Otari(id="openai:gpt-4o", api_key="test-api-key")
    assert model.id == "openai:gpt-4o"
    assert model.api_key == "test-api-key"
    assert model.base_url == "https://api.otari.ai/api/v1"


def test_otari_initialization_without_api_key():
    with patch.dict(os.environ, {}, clear=True):
        model = Otari(id="openai:gpt-4o")
        client_params = None
        with pytest.raises(ModelAuthenticationError):
            client_params = model._get_client_params()
        assert client_params is None


def test_otari_initialization_with_env_api_key():
    with patch.dict(os.environ, {"OTARI_API_KEY": "env-api-key"}):
        model = Otari(id="openai:gpt-4o")
        assert model.api_key == "env-api-key"


def test_otari_base_url_from_env():
    with patch.dict(os.environ, {"OTARI_BASE_URL": "http://localhost:8000/api/v1"}):
        model = Otari(api_key="test-api-key")
        assert model.base_url == "http://localhost:8000/api/v1"


def test_otari_client_params():
    model = Otari(id="openai:gpt-4o", api_key="test-api-key")
    client_params = model._get_client_params()
    assert client_params["api_key"] == "test-api-key"
    assert client_params["base_url"] == "https://api.otari.ai/api/v1"


def test_otari_default_values():
    model = Otari(api_key="test-api-key")
    assert model.id == "openai:gpt-4o"
    assert model.name == "Otari"
    assert model.provider == "Otari"


def test_otari_resolves_from_string_syntax():
    model = get_model("otari:anthropic:claude-sonnet-4-6")
    assert isinstance(model, Otari)
    assert model.id == "anthropic:claude-sonnet-4-6"


def test_otari_round_trips_through_dict():
    model = Otari(id="openai:gpt-4o", api_key="test-api-key")
    rebuilt = get_model_from_dict(model.to_dict())
    assert isinstance(rebuilt, Otari)
    assert rebuilt.id == "openai:gpt-4o"
