import os
import platform
from unittest.mock import patch

import pytest

from agno import __version__
from agno.exceptions import ModelAuthenticationError
from agno.models.openai.like import OpenAILike
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


def test_sarvam_default_user_agent():
    model = Sarvam(api_key="test-api-key")

    headers = model._get_client_params()["default_headers"]

    assert headers["User-Agent"] == f"agno/{__version__} Python/{platform.python_version()}"


def test_sarvam_user_agent_field_overrides_default():
    model = Sarvam(api_key="test-api-key", user_agent="my-app/1.0")

    headers = model._get_client_params()["default_headers"]

    assert headers["User-Agent"] == "my-app/1.0"


def test_sarvam_agno_user_agent_env_var():
    with patch.dict(os.environ, {"AGNO_USER_AGENT": "env-app/2.0"}):
        model = Sarvam(api_key="test-api-key")

        headers = model._get_client_params()["default_headers"]

        assert headers["User-Agent"] == "env-app/2.0"


def test_sarvam_default_headers_user_agent_wins():
    model = Sarvam(api_key="test-api-key", default_headers={"User-Agent": "caller/1.0"})

    headers = model._get_client_params()["default_headers"]

    assert headers["User-Agent"] == "caller/1.0"


def test_sarvam_lowercase_user_agent_wins():
    model = Sarvam(api_key="test-api-key", default_headers={"user-agent": "caller/1.0"})

    headers = model._get_client_params()["default_headers"]
    user_agent_keys = [key for key in headers if key.lower() == "user-agent"]

    assert len(user_agent_keys) == 1
    assert headers[user_agent_keys[0]] == "caller/1.0"


def test_sarvam_client_params_user_agent_wins():
    model = Sarvam(
        api_key="test-api-key",
        client_params={"default_headers": {"user-agent": "client/1.0"}},
    )

    headers = model._get_client_params()["default_headers"]
    user_agent_keys = [key for key in headers if key.lower() == "user-agent"]

    assert len(user_agent_keys) == 1
    assert headers[user_agent_keys[0]] == "client/1.0"


def test_sarvam_default_headers_are_preserved():
    model = Sarvam(api_key="test-api-key", default_headers={"X-Custom": "yes"})

    headers = model._get_client_params()["default_headers"]

    assert headers["X-Custom"] == "yes"
    assert headers["User-Agent"].startswith("agno/")


def test_sarvam_user_agent_reaches_the_openai_client():
    model = Sarvam(api_key="test-api-key")

    client = model.get_client()

    assert client.default_headers["User-Agent"].startswith("agno/")


def test_openai_like_does_not_get_the_sarvam_user_agent():
    model = OpenAILike(id="test-model", api_key="test-key")

    headers = model._get_client_params().get("default_headers") or {}

    assert not any(key.lower() == "user-agent" for key in headers)


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
