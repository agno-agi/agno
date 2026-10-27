import os
from unittest.mock import patch

import pytest

from agno.exceptions import ModelAuthenticationError
from agno.models.hostinger_router import HostingerRouter
from agno.models.utils import get_model, get_model_from_dict


def test_hostinger_router_initialization_with_api_key():
    model = HostingerRouter(id="gpt-5-mini", api_key="test-api-key")
    assert model.id == "gpt-5-mini"
    assert model.api_key == "test-api-key"
    assert model.base_url == "https://router.hostinger.com/v1"


def test_hostinger_router_initialization_without_api_key():
    with patch.dict(os.environ, {}, clear=True):
        model = HostingerRouter(id="gpt-5-mini")
        client_params = None
        with pytest.raises(ModelAuthenticationError):
            client_params = model._get_client_params()
        assert client_params is None


def test_hostinger_router_initialization_with_env_api_key():
    with patch.dict(os.environ, {"HOSTINGER_ROUTER_API_KEY": "env-api-key"}):
        model = HostingerRouter(id="gpt-5-mini")
        assert model.api_key == "env-api-key"


def test_hostinger_router_client_params():
    model = HostingerRouter(id="gpt-5-mini", api_key="test-api-key")
    client_params = model._get_client_params()
    assert client_params["api_key"] == "test-api-key"
    assert client_params["base_url"] == "https://router.hostinger.com/v1"


def test_hostinger_router_default_values():
    model = HostingerRouter(api_key="test-api-key")
    assert model.id == "gpt-5-mini"
    assert model.name == "HostingerRouter"
    assert model.provider == "HostingerRouter"


def test_hostinger_router_regional_variant_ids_are_passed_through():
    model = HostingerRouter(id="claude-sonnet-5-eu", api_key="test-api-key")
    assert model.id == "claude-sonnet-5-eu"


def test_hostinger_router_resolves_from_string_syntax():
    model = get_model("hostinger-router:gpt-5-mini")
    assert isinstance(model, HostingerRouter)
    assert model.id == "gpt-5-mini"


def test_hostinger_router_round_trips_through_dict():
    model = HostingerRouter(id="gemini-3.5-flash", api_key="test-api-key")
    rebuilt = get_model_from_dict(model.to_dict())
    assert isinstance(rebuilt, HostingerRouter)
    assert rebuilt.id == "gemini-3.5-flash"
