import os
from unittest.mock import patch

import pytest

from agno.exceptions import ModelAuthenticationError
from agno.models.moonshot import MoonShot


def test_moonshot_initialization_with_api_key():
    model = MoonShot(id="kimi-k2-thinking", api_key="test-api-key")
    assert model.id == "kimi-k2-thinking"
    assert model.api_key == "test-api-key"
    assert model.base_url == "https://api.moonshot.ai/v1"


def test_moonshot_initialization_without_api_key():
    with patch.dict(os.environ, {}, clear=True):
        model = MoonShot(id="kimi-k2-thinking")
        client_params = None
        with pytest.raises(ModelAuthenticationError):
            client_params = model._get_client_params()
        assert client_params is None


def test_moonshot_initialization_with_env_api_key():
    with patch.dict(os.environ, {"MOONSHOT_API_KEY": "env-api-key"}):
        model = MoonShot(id="kimi-k2-thinking")
        assert model.api_key == "env-api-key"


def test_moonshot_client_params():
    model = MoonShot(id="kimi-k2-thinking", api_key="test-api-key")
    client_params = model._get_client_params()
    assert client_params["api_key"] == "test-api-key"
    assert client_params["base_url"] == "https://api.moonshot.ai/v1"
