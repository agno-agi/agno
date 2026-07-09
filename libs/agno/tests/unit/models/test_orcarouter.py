import os
from unittest.mock import patch

import pytest

from agno.exceptions import ModelAuthenticationError
from agno.models.orcarouter import OrcaRouter


def test_orcarouter_defaults():
    model = OrcaRouter(api_key="sk-orca-test")
    assert model.id == "openai/gpt-4o-mini"
    assert model.name == "OrcaRouter"
    assert model.provider == "OrcaRouter"
    assert model.base_url == "https://api.orcarouter.ai/v1"


def test_orcarouter_initialization_with_api_key():
    model = OrcaRouter(id="anthropic/claude-opus-4.8", api_key="sk-orca-test")
    assert model.id == "anthropic/claude-opus-4.8"
    assert model.api_key == "sk-orca-test"


def test_orcarouter_initialization_without_api_key():
    with patch.dict(os.environ, {}, clear=True):
        model = OrcaRouter(id="openai/gpt-4o")
        with pytest.raises(ModelAuthenticationError):
            model._get_client_params()


def test_orcarouter_initialization_with_env_api_key():
    with patch.dict(os.environ, {"ORCAROUTER_API_KEY": "sk-orca-env"}, clear=True):
        model = OrcaRouter(id="openai/gpt-4o")
        client_params = model._get_client_params()
        assert model.api_key == "sk-orca-env"
        assert client_params["api_key"] == "sk-orca-env"
        assert client_params["base_url"] == "https://api.orcarouter.ai/v1"


def test_orcarouter_fallback_models_in_extra_body():
    model = OrcaRouter(
        id="anthropic/claude-opus-4.8",
        api_key="sk-orca-test",
        models=["deepseek/deepseek-v4-pro", "openai/gpt-4o"],
    )
    params = model.get_request_params()
    assert params["extra_body"]["models"] == ["deepseek/deepseek-v4-pro", "openai/gpt-4o"]
    assert params["extra_body"]["route"] == "fallback"


def test_orcarouter_no_fallback_models_omits_route():
    model = OrcaRouter(id="openai/gpt-4o-mini", api_key="sk-orca-test")
    params = model.get_request_params()
    extra_body = params.get("extra_body") or {}
    assert "models" not in extra_body
    assert "route" not in extra_body
