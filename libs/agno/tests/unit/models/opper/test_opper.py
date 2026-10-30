import os
from unittest.mock import patch

import pytest

from agno.exceptions import ModelAuthenticationError
from agno.models.opper import Opper
from agno.models.utils import get_model, get_model_from_dict


def test_opper_initialization_with_api_key():
    model = Opper(id="claude-sonnet-4-6", api_key="test-api-key")
    assert model.id == "claude-sonnet-4-6"
    assert model.api_key == "test-api-key"
    assert model.base_url == "https://api.opper.ai/v3/compat"


def test_opper_initialization_without_api_key():
    with patch.dict(os.environ, {}, clear=True):
        model = Opper(id="claude-sonnet-4-6")
        client_params = None
        with pytest.raises(ModelAuthenticationError):
            client_params = model._get_client_params()
        assert client_params is None


def test_opper_initialization_with_env_api_key():
    with patch.dict(os.environ, {"OPPER_API_KEY": "env-api-key"}):
        model = Opper(id="claude-sonnet-4-6")
        assert model.api_key == "env-api-key"


def test_opper_client_params():
    model = Opper(id="claude-sonnet-4-6", api_key="test-api-key")
    client_params = model._get_client_params()
    assert client_params["api_key"] == "test-api-key"
    assert client_params["base_url"] == "https://api.opper.ai/v3/compat"


def test_opper_default_values():
    model = Opper(api_key="test-api-key")
    assert model.id == "claude-sonnet-4-6"
    assert model.name == "Opper"
    assert model.provider == "Opper"


def test_opper_accepts_route_pinned_id():
    """A provider/model id pins one provider or region instead of the pool."""
    model = Opper(id="azure/gpt-5.5", api_key="test-api-key")
    assert model.id == "azure/gpt-5.5"


def test_opper_resolves_from_string_syntax():
    model = get_model("opper:claude-sonnet-4-6")
    assert isinstance(model, Opper)
    assert model.id == "claude-sonnet-4-6"


def test_opper_round_trips_through_dict():
    model = Opper(id="gpt-5.5", api_key="test-api-key")
    rebuilt = get_model_from_dict(model.to_dict())
    assert isinstance(rebuilt, Opper)
    assert rebuilt.id == "gpt-5.5"
