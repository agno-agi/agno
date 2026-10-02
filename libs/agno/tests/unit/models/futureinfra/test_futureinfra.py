import os
from unittest.mock import patch

import pytest

from agno.exceptions import ModelAuthenticationError
from agno.models.futureinfra import FutureInfra
from agno.models.utils import get_model, get_model_from_dict


def test_futureinfra_initialization_with_api_key():
    model = FutureInfra(id="openai/gpt-4o-mini", api_key="test-api-key")
    assert model.id == "openai/gpt-4o-mini"
    assert model.api_key == "test-api-key"
    assert model.base_url == "https://futureinfra.ai/v1/ai"


def test_futureinfra_initialization_without_api_key():
    with patch.dict(os.environ, {}, clear=True):
        model = FutureInfra(id="openai/gpt-4o-mini")
        client_params = None
        with pytest.raises(ModelAuthenticationError):
            client_params = model._get_client_params()
        assert client_params is None


def test_futureinfra_initialization_with_env_api_key():
    with patch.dict(os.environ, {"FUTUREINFRA_API_KEY": "env-api-key"}):
        model = FutureInfra(id="openai/gpt-4o-mini")
        assert model.api_key == "env-api-key"


def test_futureinfra_client_params():
    model = FutureInfra(id="openai/gpt-4o-mini", api_key="test-api-key")
    client_params = model._get_client_params()
    assert client_params["api_key"] == "test-api-key"
    assert client_params["base_url"] == "https://futureinfra.ai/v1/ai"


def test_futureinfra_default_values():
    model = FutureInfra(api_key="test-api-key")
    assert model.id == "openai/gpt-4o-mini"
    assert model.name == "FutureInfra"
    assert model.provider == "FutureInfra"


def test_futureinfra_resolves_from_string_syntax():
    model = get_model("futureinfra:openai/gpt-4o-mini")
    assert isinstance(model, FutureInfra)
    assert model.id == "openai/gpt-4o-mini"


def test_futureinfra_round_trips_through_dict():
    model = FutureInfra(id="deepseek/deepseek-chat", api_key="test-api-key")
    rebuilt = get_model_from_dict(model.to_dict())
    assert isinstance(rebuilt, FutureInfra)
    assert rebuilt.id == "deepseek/deepseek-chat"
