import os
from unittest.mock import patch

import pytest

from agno.exceptions import ModelAuthenticationError
from agno.models.futurmix import FuturMix


def test_futurmix_initialization_with_api_key():
    model = FuturMix(id="claude-sonnet-4-20250514", api_key="test-api-key")
    assert model.id == "claude-sonnet-4-20250514"
    assert model.api_key == "test-api-key"
    assert model.base_url == "https://futurmix.ai/v1"


def test_futurmix_initialization_without_api_key():
    with patch.dict(os.environ, {}, clear=True):
        model = FuturMix(id="claude-sonnet-4-20250514")
        client_params = None
        with pytest.raises(ModelAuthenticationError):
            client_params = model._get_client_params()
        assert client_params is None


def test_futurmix_initialization_with_env_api_key():
    with patch.dict(os.environ, {"FUTURMIX_API_KEY": "env-api-key"}):
        model = FuturMix(id="claude-sonnet-4-20250514")
        model._get_client_params()
        assert model.api_key == "env-api-key"


def test_futurmix_client_params():
    model = FuturMix(id="claude-sonnet-4-20250514", api_key="test-api-key")
    client_params = model._get_client_params()
    assert client_params["api_key"] == "test-api-key"
    assert client_params["base_url"] == "https://futurmix.ai/v1"


def test_futurmix_default_values():
    model = FuturMix(api_key="test-api-key")
    assert model.id == "claude-sonnet-4-20250514"
    assert model.name == "FuturMix"
    assert model.provider == "FuturMix"


def test_futurmix_custom_model_id():
    model = FuturMix(id="gpt-4o", api_key="test-api-key")
    assert model.id == "gpt-4o"
    assert model.name == "FuturMix"
    assert model.provider == "FuturMix"
