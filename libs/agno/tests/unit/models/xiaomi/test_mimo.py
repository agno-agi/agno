import os
from unittest.mock import patch

import pytest

from agno.exceptions import ModelAuthenticationError
from agno.models.message import Message
from agno.models.utils import get_model
from agno.models.xiaomi import MiMo


def test_mimo_initialization_with_api_key():
    model = MiMo(id="mimo-v2.5-pro", api_key="test-api-key")
    assert model.id == "mimo-v2.5-pro"
    assert model.api_key == "test-api-key"
    assert model.base_url == "https://api.xiaomimimo.com/v1"


def test_mimo_initialization_without_api_key():
    with patch.dict(os.environ, {}, clear=True):
        model = MiMo(id="mimo-v2.5-pro")
        client_params = None
        with pytest.raises(ModelAuthenticationError):
            client_params = model._get_client_params()
        assert client_params is None


def test_mimo_initialization_with_env_api_key():
    with patch.dict(os.environ, {"MIMO_API_KEY": "env-api-key"}):
        model = MiMo(id="mimo-v2.5-pro")
        assert model.api_key == "env-api-key"


def test_mimo_client_params():
    model = MiMo(id="mimo-v2.5-pro", api_key="test-api-key")
    client_params = model._get_client_params()
    assert client_params["api_key"] == "test-api-key"
    assert client_params["base_url"] == "https://api.xiaomimimo.com/v1"


def test_mimo_default_values():
    model = MiMo(api_key="test-api-key")
    assert model.id == "mimo-v2.5-pro"
    assert model.name == "MiMo"
    assert model.provider == "Xiaomi MiMo"


def test_mimo_use_thinking_true_merges_extra_body():
    model = MiMo(
        api_key="test-api-key",
        use_thinking=True,
        extra_body={"custom": "value"},
    )

    request_params = model.get_request_params()

    assert request_params["extra_body"] == {
        "custom": "value",
        "thinking": {"type": "enabled"},
    }


def test_mimo_use_thinking_false_sends_disabled_flag():
    model = MiMo(api_key="test-api-key", use_thinking=False)

    request_params = model.get_request_params()

    assert request_params["extra_body"]["thinking"] == {"type": "disabled"}


def test_mimo_use_thinking_none_sends_no_flag():
    model = MiMo(api_key="test-api-key")

    request_params = model.get_request_params()

    assert "thinking" not in (request_params.get("extra_body") or {})


def test_mimo_use_thinking_does_not_overwrite_explicit_extra_body():
    model = MiMo(
        api_key="test-api-key",
        use_thinking=True,
        extra_body={"thinking": {"type": "disabled"}},
    )

    request_params = model.get_request_params()

    # An explicit thinking setting in extra_body takes precedence over the flag.
    assert request_params["extra_body"]["thinking"] == {"type": "disabled"}


def test_mimo_formats_reasoning_content_for_assistant_history():
    model = MiMo(api_key="test-api-key")
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


def test_get_model_parses_xiaomi_string():
    model = get_model("xiaomi:mimo-v2.5-pro")
    assert isinstance(model, MiMo)
    assert model.id == "mimo-v2.5-pro"
