from unittest.mock import MagicMock, patch

import pytest

from agno.exceptions import ModelAuthenticationError, ModelProviderError
from agno.models.message import Message
from agno.models.nebius import Nebius


def _model_with_client(client: MagicMock) -> Nebius:
    client.is_closed.return_value = False
    return Nebius(api_key="test-api-key", client=client)


def test_default_config_uses_active_catalog_model():
    model = Nebius(api_key="test-api-key")

    assert model.id == "openai/gpt-oss-120b"
    assert model.name == "Nebius"
    assert model.provider == "Nebius"
    assert model.base_url == "https://api.tokenfactory.nebius.com/v1/"


def test_client_params_include_token_factory_endpoint_and_auth():
    model = Nebius(api_key="test-api-key", timeout=30, max_retries=2)

    assert model._get_client_params() == {
        "api_key": "test-api-key",
        "base_url": "https://api.tokenfactory.nebius.com/v1/",
        "timeout": 30,
        "max_retries": 2,
    }


def test_api_key_is_required():
    with patch.dict("os.environ", {}, clear=True):
        model = Nebius(api_key=None)

        with pytest.raises(ModelAuthenticationError, match="NEBIUS_API_KEY not set"):
            model._get_client_params()


def test_tool_request_uses_default_model_and_forwards_schema():
    client = MagicMock()
    provider_response = object()
    parsed_response = object()
    client.chat.completions.create.return_value = provider_response
    model = _model_with_client(client)
    model._parse_provider_response = MagicMock(return_value=parsed_response)  # type: ignore[method-assign]
    messages = [Message(role="user", content="Weather in Paris?")]
    assistant_message = Message(role="assistant")
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get weather for a city",
                "parameters": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                    "required": ["city"],
                },
            },
        }
    ]

    result = model.invoke(messages, assistant_message, tools=tools, tool_choice="auto")

    assert result is parsed_response
    client.chat.completions.create.assert_called_once_with(
        model="openai/gpt-oss-120b",
        messages=[{"role": "user", "content": "Weather in Paris?"}],
        tools=tools,
        tool_choice="auto",
    )


def test_stream_request_sets_usage_options():
    client = MagicMock()
    chunks = [object(), object()]
    client.chat.completions.create.return_value = chunks
    model = _model_with_client(client)
    model._parse_provider_response_delta = MagicMock(  # type: ignore[method-assign]
        side_effect=["first", "second"]
    )
    messages = [Message(role="user", content="Hello")]

    result = list(model.invoke_stream(messages, Message(role="assistant")))

    assert result == ["first", "second"]
    client.chat.completions.create.assert_called_once_with(
        model="openai/gpt-oss-120b",
        messages=[{"role": "user", "content": "Hello"}],
        stream=True,
        stream_options={"include_usage": True},
    )


def test_provider_errors_are_not_suppressed():
    client = MagicMock()
    client.chat.completions.create.side_effect = RuntimeError("upstream failed")
    model = _model_with_client(client)

    with pytest.raises(ModelProviderError, match="upstream failed"):
        model.invoke(
            [Message(role="user", content="Hello")],
            Message(role="assistant"),
        )
