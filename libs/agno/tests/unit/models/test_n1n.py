import os
from unittest.mock import patch

import pytest

from agno.exceptions import ModelAuthenticationError
from agno.models.n1n import N1N


def test_n1n_initialization_with_api_key():
    model = N1N(id="gpt-4o", api_key="test-api-key")
    assert model.id == "gpt-4o"
    assert model.api_key == "test-api-key"
    assert model.base_url == "https://api.n1n.ai/v1"


def test_n1n_initialization_without_api_key():
    with patch.dict(os.environ, {}, clear=True):
        model = N1N(id="gpt-4o")
        client_params = None
        with pytest.raises(ModelAuthenticationError):
            client_params = model._get_client_params()
        assert client_params is None


def test_n1n_initialization_with_env_api_key():
    with patch.dict(os.environ, {"N1N_API_KEY": "env-api-key"}):
        model = N1N(id="gpt-4o")
        assert model.api_key == "env-api-key"


def test_n1n_client_params():
    model = N1N(id="gpt-4o", api_key="test-api-key")
    client_params = model._get_client_params()
    assert client_params["api_key"] == "test-api-key"
    assert client_params["base_url"] == "https://api.n1n.ai/v1"
