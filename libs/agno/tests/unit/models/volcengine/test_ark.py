import os
from unittest.mock import patch

import pytest

from agno.exceptions import ModelAuthenticationError
from agno.models.message import Message
from agno.models.utils import get_model
from agno.models.volcengine import Ark


def test_ark_initialization_with_api_key():
    model = Ark(id="doubao-seed-2-1-pro-260628", api_key="test-api-key")
    assert model.id == "doubao-seed-2-1-pro-260628"
    assert model.api_key == "test-api-key"
    assert model.base_url == "https://ark.cn-beijing.volces.com/api/v3"


def test_ark_initialization_without_api_key():
    with patch.dict(os.environ, {}, clear=True):
        model = Ark(id="doubao-seed-2-1-pro-260628")
        client_params = None
        with pytest.raises(ModelAuthenticationError):
            client_params = model._get_client_params()
        assert client_params is None


def test_ark_initialization_with_env_api_key():
    with patch.dict(os.environ, {"ARK_API_KEY": "env-api-key"}):
        model = Ark(id="doubao-seed-2-1-pro-260628")
        assert model.api_key == "env-api-key"


def test_ark_client_params():
    model = Ark(id="doubao-seed-2-1-pro-260628", api_key="test-api-key")
    client_params = model._get_client_params()
    assert client_params["api_key"] == "test-api-key"
    assert client_params["base_url"] == "https://ark.cn-beijing.volces.com/api/v3"


def test_ark_default_values():
    model = Ark(api_key="test-api-key")
    assert model.id == "doubao-seed-2-1-pro-260628"
    assert model.name == "Ark"
    assert model.provider == "Volcengine Ark"
    assert model.supports_native_structured_outputs is True


def test_ark_use_thinking_true_merges_extra_body():
    model = Ark(
        api_key="test-api-key",
        use_thinking=True,
        extra_body={"custom": "value"},
    )

    request_params = model.get_request_params()

    assert request_params["extra_body"] == {
        "custom": "value",
        "thinking": {"type": "enabled"},
    }


def test_ark_use_thinking_false_sends_disabled_flag():
    model = Ark(api_key="test-api-key", use_thinking=False)

    request_params = model.get_request_params()

    assert request_params["extra_body"]["thinking"] == {"type": "disabled"}


def test_ark_use_thinking_none_sends_no_flag():
    model = Ark(api_key="test-api-key")

    request_params = model.get_request_params()

    assert "thinking" not in (request_params.get("extra_body") or {})


def test_ark_use_thinking_does_not_overwrite_explicit_extra_body():
    model = Ark(
        api_key="test-api-key",
        use_thinking=True,
        extra_body={"thinking": {"type": "disabled"}},
    )

    request_params = model.get_request_params()

    # An explicit thinking setting in extra_body takes precedence over the flag.
    assert request_params["extra_body"]["thinking"] == {"type": "disabled"}


def test_ark_thinking_and_reasoning_effort_together():
    model = Ark(
        api_key="test-api-key",
        use_thinking=True,
        reasoning_effort="low",
    )

    request_params = model.get_request_params()

    assert request_params["extra_body"]["thinking"] == {"type": "enabled"}
    assert request_params["reasoning_effort"] == "low"


def test_ark_use_thinking_false_strips_reasoning_effort():
    model = Ark(
        api_key="test-api-key",
        use_thinking=False,
        reasoning_effort="low",
    )

    request_params = model.get_request_params()

    assert request_params["extra_body"]["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in request_params


def test_ark_formats_reasoning_content_for_assistant_history():
    model = Ark(api_key="test-api-key")
    message = Message(
        role="assistant",
        content="",
        reasoning_content="I should call a tool.",
        tool_calls=[
            {
                "id": "call_123",
                "type": "function",
                "function": {"name": "get_weather", "arguments": "{}"},
            }
        ],
    )

    formatted_message = model._format_message(message)

    assert formatted_message["role"] == "assistant"
    assert formatted_message["reasoning_content"] == "I should call a tool."
    assert formatted_message["tool_calls"] == message.tool_calls


def test_get_model_parses_volcengine_string():
    model = get_model("volcengine:doubao-seed-2-1-pro-260628")
    assert isinstance(model, Ark)
    assert model.id == "doubao-seed-2-1-pro-260628"
