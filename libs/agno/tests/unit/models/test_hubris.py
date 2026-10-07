import os
from unittest.mock import patch

import pytest

from agno.exceptions import ModelAuthenticationError
from agno.models.hubris import Hubris


def test_hubris_initialization_with_api_key():
    model = Hubris(id="anthropic/claude-sonnet-5", api_key="test-api-key")
    assert model.id == "anthropic/claude-sonnet-5"
    assert model.api_key == "test-api-key"
    assert model.base_url == "https://api.hubris.pw/v1"


def test_hubris_initialization_without_api_key():
    with patch.dict(os.environ, {}, clear=True):
        model = Hubris(id="anthropic/claude-sonnet-5")
        client_params = None
        with pytest.raises(ModelAuthenticationError):
            client_params = model._get_client_params()
        assert client_params is None


def test_hubris_initialization_with_env_api_key():
    """The env var is read when the client is built, not at construction.

    This model follows the majority convention here (anthropic, aws, azure,
    cerebras and others): ``api_key`` defaults to None and the environment is
    consulted in ``_get_client_params``. Providers using a ``default_factory``
    resolve it earlier; both patterns are present in this codebase.
    """
    with patch.dict(os.environ, {"HUBRIS_API_KEY": "env-api-key"}):
        model = Hubris(id="anthropic/claude-sonnet-5")
        client_params = model._get_client_params()
        assert client_params["api_key"] == "env-api-key"
        assert model.api_key == "env-api-key"


def test_hubris_client_params():
    model = Hubris(id="anthropic/claude-sonnet-5", api_key="test-api-key")
    client_params = model._get_client_params()
    assert client_params["api_key"] == "test-api-key"
    assert client_params["base_url"] == "https://api.hubris.pw/v1"


def test_hubris_default_id():
    """Model ids carry the vendor prefix and are matched exactly by the gateway."""
    model = Hubris(api_key="test-api-key")
    assert model.id == "anthropic/claude-sonnet-5"
    assert model.name == "Hubris"
    assert model.provider == "Hubris"
