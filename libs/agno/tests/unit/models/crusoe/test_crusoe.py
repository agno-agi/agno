import os
from unittest.mock import patch

import pytest

from agno.exceptions import ModelAuthenticationError
from agno.models.crusoe import Crusoe
from agno.models.utils import get_model, get_model_from_dict


def test_crusoe_initialization_with_api_key():
    model = Crusoe(id="openai/gpt-oss-120b", api_key="test-api-key")
    assert model.id == "openai/gpt-oss-120b"
    assert model.api_key == "test-api-key"
    assert model.base_url == "https://api.inference.crusoecloud.com/v1"


def test_crusoe_initialization_without_api_key():
    with patch.dict(os.environ, {}, clear=True):
        model = Crusoe(id="openai/gpt-oss-120b")
        client_params = None
        with pytest.raises(ModelAuthenticationError):
            client_params = model._get_client_params()
        assert client_params is None


def test_crusoe_initialization_with_env_api_key():
    with patch.dict(os.environ, {"CRUSOE_API_KEY": "env-api-key"}):
        model = Crusoe(id="openai/gpt-oss-120b")
        assert model.api_key == "env-api-key"


def test_crusoe_client_params():
    model = Crusoe(id="openai/gpt-oss-120b", api_key="test-api-key")
    client_params = model._get_client_params()
    assert client_params["api_key"] == "test-api-key"
    assert client_params["base_url"] == "https://api.inference.crusoecloud.com/v1"


def test_crusoe_default_values():
    model = Crusoe(api_key="test-api-key")
    assert model.id == "openai/gpt-oss-120b"
    assert model.name == "Crusoe"
    assert model.provider == "Crusoe"


def test_crusoe_resolves_from_string_syntax():
    model = get_model("crusoe:openai/gpt-oss-120b")
    assert isinstance(model, Crusoe)
    assert model.id == "openai/gpt-oss-120b"


def test_crusoe_round_trips_through_dict():
    model = Crusoe(id="zai-org/GLM-5.3", api_key="test-api-key")
    rebuilt = get_model_from_dict(model.to_dict())
    assert isinstance(rebuilt, Crusoe)
    assert rebuilt.id == "zai-org/GLM-5.3"
