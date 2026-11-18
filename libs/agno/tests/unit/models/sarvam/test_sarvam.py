import os
from unittest.mock import patch

import pytest

from agno.exceptions import ModelAuthenticationError
from agno.models.sarvam import Sarvam
from agno.models.utils import get_model, get_model_from_dict


def test_sarvam_initialization_with_api_key():
    model = Sarvam(id="sarvam-105b", api_key="test-api-key")
    assert model.id == "sarvam-105b"
    assert model.api_key == "test-api-key"
    assert model.base_url == "https://api.sarvam.ai/v2"


def test_sarvam_initialization_without_api_key():
    with patch.dict(os.environ, {}, clear=True):
        model = Sarvam(id="sarvam-105b")
        client_params = None
        with pytest.raises(ModelAuthenticationError):
            client_params = model._get_client_params()
        assert client_params is None


def test_sarvam_initialization_with_env_api_key():
    with patch.dict(os.environ, {"SARVAM_API_KEY": "env-api-key"}):
        model = Sarvam(id="sarvam-105b")
        assert model.api_key == "env-api-key"


def test_sarvam_client_params():
    model = Sarvam(id="sarvam-105b", api_key="test-api-key")
    client_params = model._get_client_params()
    assert client_params["api_key"] == "test-api-key"
    assert client_params["base_url"] == "https://api.sarvam.ai/v2"


def test_sarvam_default_values():
    model = Sarvam(api_key="test-api-key")
    assert model.id == "sarvam-105b"
    assert model.name == "Sarvam"
    assert model.provider == "Sarvam"


def test_sarvam_passes_reasoning_effort():
    model = Sarvam(api_key="test-api-key", reasoning_effort="high")
    request_params = model.get_request_params()
    assert request_params["reasoning_effort"] == "high"


def test_get_model_parses_sarvam_string():
    model = get_model("sarvam:sarvam-105b")
    assert isinstance(model, Sarvam)
    assert model.id == "sarvam-105b"


def test_sarvam_round_trips_through_dict():
    model = Sarvam(id="sarvam-105b", api_key="test-api-key")
    rebuilt = get_model_from_dict(model.to_dict())
    assert isinstance(rebuilt, Sarvam)
    assert rebuilt.id == "sarvam-105b"


def test_sarvam_accepts_v1_base_url_override():
    model = Sarvam(api_key="test-api-key", base_url="https://api.sarvam.ai/v1")
    assert model.base_url == "https://api.sarvam.ai/v1"
