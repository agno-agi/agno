import os
from unittest.mock import patch

import pytest

from agno.exceptions import ModelAuthenticationError
from agno.models.tzafon import Tzafon


def test_tzafon_initialization_with_api_key():
    model = Tzafon(id="tzafon.northstar-cua-fast", api_key="test-api-key")
    assert model.id == "tzafon.northstar-cua-fast"
    assert model.api_key == "test-api-key"
    assert model.base_url == "https://api.tzafon.ai/v1"


def test_tzafon_default_id():
    model = Tzafon(api_key="test-api-key")
    assert model.id == "tzafon.sm-1"
    assert model.name == "Tzafon"
    assert model.provider == "Tzafon"


def test_tzafon_initialization_without_api_key():
    with patch.dict(os.environ, {}, clear=True):
        model = Tzafon(id="tzafon.northstar-cua-fast")
        client_params = None
        with pytest.raises(ModelAuthenticationError):
            client_params = model._get_client_params()
        assert client_params is None


def test_tzafon_initialization_with_env_api_key():
    with patch.dict(os.environ, {"TZAFON_API_KEY": "env-api-key"}):
        model = Tzafon(id="tzafon.northstar-cua-fast")
        model._get_client_params()
        assert model.api_key == "env-api-key"


def test_tzafon_client_params():
    model = Tzafon(id="tzafon.northstar-cua-fast", api_key="test-api-key")
    client_params = model._get_client_params()
    assert client_params["api_key"] == "test-api-key"
    assert client_params["base_url"] == "https://api.tzafon.ai/v1"
