import os
from unittest.mock import patch

import pytest

from agno.exceptions import ModelAuthenticationError
from agno.models.cheaperinference import CheaperInference
from agno.models.utils import get_model, get_model_from_dict


def test_cheaperinference_initialization_with_api_key():
    model = CheaperInference(id="gpt-5.4-mini", api_key="test-api-key")
    assert model.id == "gpt-5.4-mini"
    assert model.api_key == "test-api-key"
    assert model.base_url == "https://api.cheaperinference.com/v1"


def test_cheaperinference_initialization_without_api_key():
    with patch.dict(os.environ, {}, clear=True):
        model = CheaperInference(id="gpt-5.4-mini")
        client_params = None
        with pytest.raises(ModelAuthenticationError):
            client_params = model._get_client_params()
        assert client_params is None


def test_cheaperinference_initialization_with_env_api_key():
    with patch.dict(os.environ, {"CHEAPER_INFERENCE_API_KEY": "env-api-key"}):
        model = CheaperInference(id="gpt-5.4-mini")
        assert model.api_key == "env-api-key"


def test_cheaperinference_client_params():
    model = CheaperInference(id="gpt-5.4-mini", api_key="test-api-key")
    client_params = model._get_client_params()
    assert client_params["api_key"] == "test-api-key"
    assert client_params["base_url"] == "https://api.cheaperinference.com/v1"


def test_cheaperinference_default_values():
    model = CheaperInference(api_key="test-api-key")
    assert model.id == "gpt-5.4-mini"
    assert model.name == "CheaperInference"
    assert model.provider == "CheaperInference"


def test_cheaperinference_resolves_from_string_syntax():
    model = get_model("cheaperinference:gpt-5.4-mini")
    assert isinstance(model, CheaperInference)
    assert model.id == "gpt-5.4-mini"


def test_cheaperinference_round_trips_through_dict():
    model = CheaperInference(id="gpt-5.4", api_key="test-api-key")
    rebuilt = get_model_from_dict(model.to_dict())
    assert isinstance(rebuilt, CheaperInference)
    assert rebuilt.id == "gpt-5.4"
