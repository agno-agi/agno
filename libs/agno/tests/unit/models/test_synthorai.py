import os
from unittest.mock import patch

import pytest

from agno.exceptions import ModelAuthenticationError
from agno.models.synthorai import Synthorai


def test_synthorai_initialization_with_api_key():
    model = Synthorai(id="claude-opus-5", api_key="test-api-key")
    assert model.id == "claude-opus-5"
    assert model.api_key == "test-api-key"
    assert model.base_url == "https://synthorai.io/v1"


def test_synthorai_initialization_without_api_key():
    with patch.dict(os.environ, {}, clear=True):
        model = Synthorai(id="claude-opus-5")
        client_params = None
        with pytest.raises(ModelAuthenticationError):
            client_params = model._get_client_params()
        assert client_params is None


def test_synthorai_initialization_with_env_api_key():
    with patch.dict(os.environ, {"SYNTHORAI_API_KEY": "env-api-key"}):
        model = Synthorai(id="claude-opus-5")
        assert model.api_key == "env-api-key"


def test_synthorai_client_params():
    model = Synthorai(id="claude-opus-5", api_key="test-api-key")
    client_params = model._get_client_params()
    assert client_params["api_key"] == "test-api-key"
    assert client_params["base_url"] == "https://synthorai.io/v1"
