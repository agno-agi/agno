import os
from unittest.mock import patch

import pytest

from agno.exceptions import ModelAuthenticationError
from agno.models.minimax import MiniMax


def test_minimax_initialization_with_api_key():
    model = MiniMax(id="MiniMax-M2.5", api_key="test-api-key")
    assert model.id == "MiniMax-M2.5"
    assert model.api_key == "test-api-key"
    assert model.base_url == "https://api.minimax.io/v1"


def test_minimax_initialization_without_api_key():
    with patch.dict(os.environ, {}, clear=True):
        model = MiniMax(id="MiniMax-M2.5")
        client_params = None
        with pytest.raises(ModelAuthenticationError):
            client_params = model._get_client_params()
        assert client_params is None


def test_minimax_initialization_with_env_api_key():
    with patch.dict(os.environ, {"MINIMAX_API_KEY": "env-api-key"}):
        model = MiniMax(id="MiniMax-M2.5")
        assert model.api_key == "env-api-key"


def test_minimax_client_params():
    model = MiniMax(id="MiniMax-M2.5", api_key="test-api-key")
    client_params = model._get_client_params()
    assert client_params["api_key"] == "test-api-key"
    assert client_params["base_url"] == "https://api.minimax.io/v1"


def test_minimax_default_model():
    with patch.dict(os.environ, {"MINIMAX_API_KEY": "test-key"}):
        model = MiniMax()
        assert model.id == "MiniMax-M2.5"
        assert model.name == "MiniMax"
        assert model.provider == "MiniMax"


def test_minimax_highspeed_model():
    model = MiniMax(id="MiniMax-M2.5-highspeed", api_key="test-api-key")
    assert model.id == "MiniMax-M2.5-highspeed"
    client_params = model._get_client_params()
    assert client_params["api_key"] == "test-api-key"


def test_minimax_custom_base_url():
    model = MiniMax(
        id="MiniMax-M2.5",
        api_key="test-api-key",
        base_url="https://api.minimaxi.com/v1",
    )
    assert model.base_url == "https://api.minimaxi.com/v1"
    client_params = model._get_client_params()
    assert client_params["base_url"] == "https://api.minimaxi.com/v1"


def test_minimax_does_not_support_native_structured_outputs():
    model = MiniMax(api_key="test-api-key")
    assert model.supports_native_structured_outputs is False
