import os
from unittest.mock import patch

import pytest

from agno.exceptions import ModelAuthenticationError
from agno.models.inception import Inception


def test_inception_initialization_with_api_key():
    model = Inception(id="mercury-2", api_key="test-api-key")
    assert model.id == "mercury-2"
    assert model.api_key == "test-api-key"
    assert model.base_url == "https://api.inceptionlabs.ai/v1"


def test_inception_initialization_without_api_key():
    with patch.dict(os.environ, {}, clear=True):
        model = Inception(id="mercury-2")
        client_params = None
        with pytest.raises(ModelAuthenticationError):
            client_params = model._get_client_params()
        assert client_params is None


def test_inception_initialization_with_env_api_key():
    with patch.dict(os.environ, {"INCEPTION_API_KEY": "env-api-key"}):
        model = Inception(id="mercury-2")
        assert model.api_key == "env-api-key"


def test_inception_does_not_fall_back_to_openai_api_key():
    # A missing INCEPTION_API_KEY must NOT silently use OPENAI_API_KEY, otherwise
    # an OpenAI key would be sent to the Inception endpoint.
    with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-should-not-leak"}, clear=True):
        model = Inception(id="mercury-2")
        with pytest.raises(ModelAuthenticationError):
            model._get_client_params()
        assert model.api_key != "sk-should-not-leak"


def test_inception_client_params():
    model = Inception(id="mercury-2", api_key="test-api-key")
    client_params = model._get_client_params()
    assert client_params["api_key"] == "test-api-key"
    assert client_params["base_url"] == "https://api.inceptionlabs.ai/v1"


def test_inception_default_model():
    with patch.dict(os.environ, {"INCEPTION_API_KEY": "test-key"}):
        model = Inception()
        assert model.id == "mercury-2"
        assert model.name == "Inception"
        assert model.provider == "InceptionLabs"


def test_inception_coder_model():
    model = Inception(id="mercury-coder-small", api_key="test-api-key")
    assert model.id == "mercury-coder-small"
    client_params = model._get_client_params()
    assert client_params["api_key"] == "test-api-key"


def test_inception_custom_base_url():
    model = Inception(
        id="mercury-2",
        api_key="test-api-key",
        base_url="https://your-host.example.com/v1",
    )
    assert model.base_url == "https://your-host.example.com/v1"
    client_params = model._get_client_params()
    assert client_params["base_url"] == "https://your-host.example.com/v1"


def test_inception_does_not_support_native_structured_outputs():
    model = Inception(api_key="test-api-key")
    assert model.supports_native_structured_outputs is False
