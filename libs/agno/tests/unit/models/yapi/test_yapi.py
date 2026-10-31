import os
from unittest.mock import patch

import pytest

from agno.exceptions import ModelAuthenticationError
from agno.models.utils import get_model, get_model_from_dict
from agno.models.yapi import YAPI


def test_yapi_initialization_with_api_key():
    model = YAPI(id="deepseek/deepseek-v4-flash", api_key="test-api-key")
    assert model.id == "deepseek/deepseek-v4-flash"
    assert model.api_key == "test-api-key"
    assert model.base_url == "https://api.y-api.bestvirtualgoods.com/v1"


def test_yapi_initialization_without_api_key():
    with patch.dict(os.environ, {}, clear=True):
        model = YAPI(id="deepseek/deepseek-v4-flash")
        client_params = None
        with pytest.raises(ModelAuthenticationError):
            client_params = model._get_client_params()
        assert client_params is None


def test_yapi_initialization_with_env_api_key():
    with patch.dict(os.environ, {"YAPI_API_KEY": "env-api-key"}):
        model = YAPI(id="deepseek/deepseek-v4-flash")
        assert model.api_key == "env-api-key"


def test_yapi_client_params():
    model = YAPI(id="deepseek/deepseek-v4-flash", api_key="test-api-key")
    client_params = model._get_client_params()
    assert client_params["api_key"] == "test-api-key"
    assert client_params["base_url"] == "https://api.y-api.bestvirtualgoods.com/v1"


def test_yapi_default_values():
    model = YAPI(api_key="test-api-key")
    assert model.id == "deepseek/deepseek-v4-flash"
    assert model.name == "YAPI"
    assert model.provider == "YAPI"


def test_yapi_resolves_from_string_syntax():
    model = get_model("yapi:deepseek/deepseek-v4-flash")
    assert isinstance(model, YAPI)
    assert model.id == "deepseek/deepseek-v4-flash"


def test_yapi_round_trips_through_dict():
    model = YAPI(id="z-ai/glm-5.3", api_key="test-api-key")
    rebuilt = get_model_from_dict(model.to_dict())
    assert isinstance(rebuilt, YAPI)
    assert rebuilt.id == "z-ai/glm-5.3"
