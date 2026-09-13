import os
from unittest.mock import patch

import pytest

from agno.exceptions import ModelAuthenticationError
from agno.models.tuning_engines import TuningEngines


def test_tuning_engines_initialization_with_api_key():
    model = TuningEngines(id="gpt-4o", api_key="test-api-key")
    assert model.id == "gpt-4o"
    assert model.api_key == "test-api-key"
    assert model.base_url == "https://api.tuningengines.com/v1"


def test_tuning_engines_initialization_without_api_key():
    with patch.dict(os.environ, {}, clear=True):
        model = TuningEngines(id="gpt-4o")
        client_params = None
        with pytest.raises(ModelAuthenticationError):
            client_params = model._get_client_params()
        assert client_params is None


def test_tuning_engines_initialization_with_env_api_key():
    with patch.dict(os.environ, {"TUNING_ENGINES_API_KEY": "env-api-key"}):
        model = TuningEngines(id="gpt-4o")
        assert model.api_key == "env-api-key"


def test_tuning_engines_does_not_fall_back_to_openai_api_key():
    # A missing TUNING_ENGINES_API_KEY must NOT silently use OPENAI_API_KEY,
    # otherwise an OpenAI key would be sent to the Tuning Engines endpoint.
    with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-should-not-leak"}, clear=True):
        model = TuningEngines(id="gpt-4o")
        with pytest.raises(ModelAuthenticationError):
            model._get_client_params()
        assert model.api_key != "sk-should-not-leak"


def test_tuning_engines_client_params():
    model = TuningEngines(id="gpt-4o", api_key="test-api-key")
    client_params = model._get_client_params()
    assert client_params["api_key"] == "test-api-key"
    assert client_params["base_url"] == "https://api.tuningengines.com/v1"


def test_tuning_engines_default_model():
    with patch.dict(os.environ, {"TUNING_ENGINES_API_KEY": "test-key"}):
        model = TuningEngines()
        assert model.id == "gpt-4o"
        assert model.name == "Tuning Engines"
        assert model.provider == "Tuning Engines"


def test_tuning_engines_custom_model_alias():
    model = TuningEngines(id="gpt-4o-mini", api_key="test-api-key")
    assert model.id == "gpt-4o-mini"
    client_params = model._get_client_params()
    assert client_params["api_key"] == "test-api-key"


def test_tuning_engines_custom_base_url():
    model = TuningEngines(
        id="gpt-4o",
        api_key="test-api-key",
        base_url="https://your-host.example.com/v1",
    )
    assert model.base_url == "https://your-host.example.com/v1"
    client_params = model._get_client_params()
    assert client_params["base_url"] == "https://your-host.example.com/v1"


def test_tuning_engines_base_url_from_env():
    with patch.dict(
        os.environ,
        {
            "TUNING_ENGINES_API_KEY": "test-key",
            "TUNING_ENGINES_BASE_URL": "https://gateway.example.com/v1",
        },
    ):
        model = TuningEngines()
        assert model.base_url == "https://gateway.example.com/v1"
