import os
from unittest.mock import MagicMock, patch

import pytest

from agno.exceptions import ModelAuthenticationError
from agno.models.apiroute import ApiRoute


def test_apiroute_initialization_with_api_key():
    model = ApiRoute(id="claude-3-7-sonnet-20250219", api_key="test-api-key")
    assert model.id == "claude-3-7-sonnet-20250219"
    assert model.name == "ApiRoute"
    assert model.provider == "ApiRoute"
    assert model.api_key == "test-api-key"
    assert model.base_url == "https://global.api-route.com/v1"


def test_apiroute_initialization_without_api_key():
    with patch.dict(os.environ, {}, clear=True):
        model = ApiRoute(id="claude-3-7-sonnet-20250219")
        client_params = None
        with pytest.raises(ModelAuthenticationError):
            client_params = model._get_client_params()
        assert client_params is None


def test_apiroute_initialization_with_env_api_key():
    with patch.dict(os.environ, {"APIROUTE_API_KEY": "env-api-key"}):
        model = ApiRoute(id="claude-3-7-sonnet-20250219")
        assert model.api_key == "env-api-key"


def test_apiroute_client_params():
    model = ApiRoute(id="claude-3-7-sonnet-20250219", api_key="test-api-key")
    client_params = model._get_client_params()
    assert client_params["api_key"] == "test-api-key"
    assert client_params["base_url"] == "https://global.api-route.com/v1"


def test_apiroute_get_available_models_without_key():
    with patch.dict(os.environ, {}, clear=True):
        model = ApiRoute(id="claude-3-7-sonnet-20250219")
        assert model.get_available_models() == []


def test_apiroute_get_available_models_mocked():
    model = ApiRoute(id="claude-3-7-sonnet-20250219", api_key="test-api-key")
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "data": [
            {"id": "claude-3-7-sonnet-20250219"},
            {"id": "gpt-4o"},
            {"id": "deepseek-chat"},
        ]
    }
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.Client.get", return_value=mock_response):
        models = model.get_available_models()
        assert "claude-3-7-sonnet-20250219" in models
        assert "gpt-4o" in models
        assert "deepseek-chat" in models
