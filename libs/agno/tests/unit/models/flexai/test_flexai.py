import os
from unittest.mock import patch

import pytest

from agno.exceptions import ModelAuthenticationError
from agno.models.flexai import FlexAI
from agno.models.utils import get_model, get_model_from_dict


def test_flexai_initialization_with_api_key():
    model = FlexAI(id="DeepSeek-V4-Flash-0731", api_key="test-api-key")
    assert model.id == "DeepSeek-V4-Flash-0731"
    assert model.api_key == "test-api-key"
    assert model.base_url == "https://api.flex.ai/v1"


def test_flexai_initialization_without_api_key():
    with patch.dict(os.environ, {}, clear=True):
        model = FlexAI(id="DeepSeek-V4-Flash-0731")
        client_params = None
        with pytest.raises(ModelAuthenticationError):
            client_params = model._get_client_params()
        assert client_params is None


def test_flexai_initialization_with_env_api_key():
    with patch.dict(os.environ, {"FLEXAI_API_KEY": "env-api-key"}):
        model = FlexAI(id="DeepSeek-V4-Flash-0731")
        assert model.api_key == "env-api-key"


def test_flexai_client_params():
    model = FlexAI(id="DeepSeek-V4-Flash-0731", api_key="test-api-key")
    client_params = model._get_client_params()
    assert client_params["api_key"] == "test-api-key"
    assert client_params["base_url"] == "https://api.flex.ai/v1"


def test_flexai_default_values():
    model = FlexAI(api_key="test-api-key")
    assert model.id == "DeepSeek-V4-Flash-0731"
    assert model.name == "FlexAI"
    assert model.provider == "FlexAI"


def test_flexai_resolves_from_string_syntax():
    model = get_model("flexai:DeepSeek-V4-Flash-0731")
    assert isinstance(model, FlexAI)
    assert model.id == "DeepSeek-V4-Flash-0731"


def test_flexai_round_trips_through_dict():
    model = FlexAI(id="GLM-5.3-Flash", api_key="test-api-key")
    rebuilt = get_model_from_dict(model.to_dict())
    assert isinstance(rebuilt, FlexAI)
    assert rebuilt.id == "GLM-5.3-Flash"
