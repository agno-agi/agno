import os
from unittest.mock import patch

import pytest

from agno.exceptions import ModelAuthenticationError
from agno.models.edenai import EdenAI


def test_edenai_initialization_with_api_key():
    model = EdenAI(id="openai/gpt-5.5", api_key="test-api-key")
    assert model.id == "openai/gpt-5.5"
    assert model.api_key == "test-api-key"
    assert model.base_url == "https://api.edenai.run/v3"


def test_edenai_initialization_without_api_key():
    with patch.dict(os.environ, {}, clear=True):
        model = EdenAI(id="openai/gpt-5.5", api_key=None)
        client_params = None
        with pytest.raises(ModelAuthenticationError):
            client_params = model._get_client_params()
        assert client_params is None


def test_edenai_initialization_with_env_api_key():
    with patch.dict(os.environ, {"EDENAI_API_KEY": "env-api-key"}):
        model = EdenAI(id="openai/gpt-5.5", api_key=None)
        client_params = model._get_client_params()
        assert model.api_key == "env-api-key"
        assert client_params["api_key"] == "env-api-key"


def test_edenai_client_params():
    model = EdenAI(id="openai/gpt-5.5", api_key="test-api-key")
    client_params = model._get_client_params()
    assert client_params["api_key"] == "test-api-key"
    assert client_params["base_url"] == "https://api.edenai.run/v3"


def test_edenai_default_model():
    model = EdenAI(api_key="test-key")
    assert model.id == "openai/gpt-5.5"
    assert model.name == "EdenAI"
    assert model.provider == "EdenAI"


def test_edenai_anthropic_model():
    model = EdenAI(id="anthropic/claude-haiku-4-5", api_key="test-api-key")
    assert model.id == "anthropic/claude-haiku-4-5"
    client_params = model._get_client_params()
    assert client_params["api_key"] == "test-api-key"


def test_edenai_mistral_model():
    model = EdenAI(id="mistral/mistral-large-latest", api_key="test-api-key")
    assert model.id == "mistral/mistral-large-latest"
    client_params = model._get_client_params()
    assert client_params["api_key"] == "test-api-key"


def test_edenai_custom_base_url():
    model = EdenAI(
        id="openai/gpt-5.5",
        api_key="test-api-key",
        base_url="https://custom.edenai.example/v3",
    )
    assert model.base_url == "https://custom.edenai.example/v3"
    client_params = model._get_client_params()
    assert client_params["base_url"] == "https://custom.edenai.example/v3"
