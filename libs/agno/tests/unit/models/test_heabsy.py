import os
from unittest.mock import patch

import pytest

from agno.exceptions import ModelAuthenticationError
from agno.models.heabsy import Heabsy
from agno.models.utils import get_model, get_model_from_dict


def test_heabsy_initialization_with_api_key():
    model = Heabsy(id="qwen38", api_key="test-api-key")
    assert model.id == "qwen38"
    assert model.api_key == "test-api-key"
    assert model.base_url == "https://api.heabsy.com/v1"


def test_heabsy_initialization_without_api_key():
    with patch.dict(os.environ, {}, clear=True):
        model = Heabsy(id="qwen38")
        client_params = None
        with pytest.raises(ModelAuthenticationError):
            client_params = model._get_client_params()
        assert client_params is None


def test_heabsy_initialization_with_env_api_key():
    with patch.dict(os.environ, {"HEABSY_API_KEY": "env-api-key"}):
        model = Heabsy(id="qwen38")
        assert model.api_key == "env-api-key"


def test_heabsy_client_params():
    model = Heabsy(id="qwen38", api_key="test-api-key")
    client_params = model._get_client_params()
    assert client_params["api_key"] == "test-api-key"
    assert client_params["base_url"] == "https://api.heabsy.com/v1"


def test_heabsy_default_values():
    model = Heabsy(api_key="test-api-key")
    assert model.id == "qwen38"
    assert model.name == "Heabsy"
    assert model.provider == "Heabsy"


def test_heabsy_resolves_from_string_syntax():
    model = get_model("heabsy:qwen38")
    assert isinstance(model, Heabsy)
    assert model.id == "qwen38"


def test_heabsy_round_trips_through_dict():
    model = Heabsy(id="qwen38", api_key="test-api-key")
    rebuilt = get_model_from_dict(model.to_dict())
    assert isinstance(rebuilt, Heabsy)
    assert rebuilt.id == "qwen38"
