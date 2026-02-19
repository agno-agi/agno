import os
from unittest.mock import patch

import pytest

from agno.exceptions import ModelAuthenticationError
from agno.models.neosantara import Neosantara


def test_neosantara_initialization_with_api_key():
    model = Neosantara(id="grok-4.1-fast-non-reasoning", api_key="test-api-key")
    assert model.id == "grok-4.1-fast-non-reasoning"
    assert model.api_key == "test-api-key"
    assert model.base_url == "https://api.neosantara.xyz/v1"


def test_neosantara_initialization_without_api_key():
    with patch.dict(os.environ, {}, clear=True):
        model = Neosantara(id="grok-4.1-fast-non-reasoning")
        client_params = None
        with pytest.raises(ModelAuthenticationError):
            client_params = model._get_client_params()
        assert client_params is None


def test_neosantara_initialization_with_env_api_key():
    with patch.dict(os.environ, {"NEOSANTARA_API_KEY": "env-api-key"}):
        model = Neosantara(id="grok-4.1-fast-non-reasoning")
        model._get_client_params()
        assert model.api_key == "env-api-key"


def test_neosantara_client_params():
    model = Neosantara(id="grok-4.1-fast-non-reasoning", api_key="test-api-key")
    client_params = model._get_client_params()
    assert client_params["api_key"] == "test-api-key"
    assert client_params["base_url"] == "https://api.neosantara.xyz/v1"


def test_neosantara_default_values():
    model = Neosantara(api_key="test-api-key")
    assert model.id == "grok-4.1-fast-non-reasoning"
    assert model.name == "Neosantara"
    assert model.provider == "Neosantara"


def test_neosantara_custom_model_id():
    model = Neosantara(id="custom-model", api_key="test-api-key")
    assert model.id == "custom-model"
    assert model.name == "Neosantara"
    assert model.provider == "Neosantara"
