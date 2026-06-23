from contextlib import asynccontextmanager, contextmanager
from unittest.mock import AsyncMock, Mock

import pytest

from agno.models.databricks import Databricks
from agno.models.message import Message


def _non_stream_response():
    return {
        "id": "chatcmpl-123",
        "object": "chat.completion",
        "model": "endpoint-name",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "Hello from Databricks",
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        },
    }


def _tool_response():
    return {
        "id": "chatcmpl-456",
        "object": "chat.completion",
        "model": "endpoint-name",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "get_weather", "arguments": "{\"city\":\"NYC\"}"},
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {
            "prompt_tokens": 8,
            "completion_tokens": 4,
            "total_tokens": 12,
        },
    }


def test_build_payload_uses_endpoint_as_model():
    model = Databricks(id="ignored-id", endpoint="served-endpoint", host="https://example.cloud.databricks.com")

    payload = model._build_payload([Message(role="user", content="hello")])

    assert payload["model"] == "served-endpoint"
    assert payload["messages"][0]["role"] == "user"
    assert payload["messages"][0]["content"] == "hello"


def test_get_request_params_omits_unsupported_chat_fields():
    model = Databricks(
        endpoint="served-endpoint",
        host="https://example.cloud.databricks.com",
        frequency_penalty=0.1,
        presence_penalty=0.2,
        seed=7,
        user="user-1",
        metadata={"tag": "x"},
        temperature=0.3,
    )

    request_params = model.get_request_params()

    assert request_params["temperature"] == 0.3
    assert "frequency_penalty" not in request_params
    assert "presence_penalty" not in request_params
    assert "seed" not in request_params
    assert "user" not in request_params
    assert "metadata" not in request_params


def test_get_client_loads_host_and_token_from_env(monkeypatch):
    monkeypatch.setenv("DATABRICKS_HOST", "https://env.cloud.databricks.com")
    monkeypatch.setenv("DATABRICKS_TOKEN", "env-token")

    model = Databricks(endpoint="served-endpoint")

    client = model.get_client()

    assert client.settings.host == "https://env.cloud.databricks.com"
    assert client.settings.workspace_url == "https://env.cloud.databricks.com"
    assert client.settings.token == "env-token"


def test_explicit_model_settings_override_env(monkeypatch):
    monkeypatch.setenv("DATABRICKS_HOST", "https://env.cloud.databricks.com")
    monkeypatch.setenv("DATABRICKS_TOKEN", "env-token")

    model = Databricks(
        endpoint="served-endpoint",
        host="https://explicit.cloud.databricks.com",
        token="explicit-token",
        default_headers={"X-Test": "1"},
    )

    client = model.get_client()

    assert client.settings.host == "https://explicit.cloud.databricks.com"
    assert client.settings.workspace_url == "https://explicit.cloud.databricks.com"
    assert client.settings.token == "explicit-token"
    assert client.settings.default_headers["X-Test"] == "1"


def test_explicit_model_settings_are_revalidated():
    model = Databricks(
        endpoint="served-endpoint",
        host="explicit.cloud.databricks.com/",
    )

    client = model.get_client()

    assert client.settings.host == "https://explicit.cloud.databricks.com"
    assert client.settings.workspace_url == "https://explicit.cloud.databricks.com"


def test_invalid_explicit_model_timeout_raises():
    model = Databricks(endpoint="served-endpoint", timeout=0)

    with pytest.raises(ValueError):
        model.get_client()


def test_invoke_uses_native_client():
    mock_client = Mock()
    mock_client.request_json.return_value = _non_stream_response()

    model = Databricks(endpoint="served-endpoint", host="https://example.cloud.databricks.com")
    model.client = mock_client

    assistant_message = Message(role="assistant")
    response = model.invoke([Message(role="user", content="hello")], assistant_message)

    assert response.content == "Hello from Databricks"
    assert response.response_usage is not None
    assert response.response_usage.total_tokens == 15
    mock_client.request_json.assert_called_once()
    args = mock_client.request_json.call_args.args
    kwargs = mock_client.request_json.call_args.kwargs
    assert args == ("POST", "/serving-endpoints/chat/completions")
    assert kwargs["json"]["model"] == "served-endpoint"


@pytest.mark.asyncio
async def test_ainvoke_uses_native_async_client():
    mock_client = Mock()
    mock_client.request_json = AsyncMock(return_value=_non_stream_response())

    model = Databricks(endpoint="served-endpoint", host="https://example.cloud.databricks.com")
    model.async_client = mock_client

    assistant_message = Message(role="assistant")
    response = await model.ainvoke([Message(role="user", content="hello")], assistant_message)

    assert response.content == "Hello from Databricks"
    assert response.response_usage is not None
    assert response.response_usage.total_tokens == 15
    mock_client.request_json.assert_awaited_once()


def test_parse_provider_response_tool_calls():
    model = Databricks(endpoint="served-endpoint", host="https://example.cloud.databricks.com")

    response = model._parse_provider_response(_tool_response())

    assert len(response.tool_calls) == 1
    assert response.tool_calls[0]["function"]["name"] == "get_weather"


def test_parse_tool_calls_aggregates_stream_fragments():
    tool_calls = Databricks.parse_tool_calls(
        [
            {"index": 0, "id": "call_1", "type": "function", "function": {"name": "get_weather", "arguments": "{"}},
            {"index": 0, "function": {"arguments": "\"city\":\"NY"}},
            {"index": 0, "function": {"arguments": "C\"}"}},
        ]
    )

    assert len(tool_calls) == 1
    assert tool_calls[0]["id"] == "call_1"
    assert tool_calls[0]["function"]["name"] == "get_weather"
    assert tool_calls[0]["function"]["arguments"] == "{\"city\":\"NYC\"}"


def test_parse_sse_line():
    model = Databricks(endpoint="served-endpoint", host="https://example.cloud.databricks.com")

    response = model._parse_sse_line('data: {"id":"chatcmpl-789","choices":[{"delta":{"content":"Hel"},"index":0}]}')

    assert response is not None
    assert response.content == "Hel"


def test_parse_sse_done_line_returns_none():
    model = Databricks(endpoint="served-endpoint", host="https://example.cloud.databricks.com")

    assert model._parse_sse_line("data: [DONE]") is None


def test_invoke_stream_uses_native_stream_client():
    @contextmanager
    def stream_ctx():
        response = Mock()
        response.iter_lines.return_value = [
            'data: {"id":"chatcmpl-1","choices":[{"delta":{"content":"Hel"},"index":0}]}',
            'data: {"id":"chatcmpl-1","choices":[{"delta":{"content":"lo"},"index":0}],"usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}}',
            "data: [DONE]",
        ]
        yield response

    mock_client = Mock()
    mock_client.stream.return_value = stream_ctx()

    model = Databricks(endpoint="served-endpoint", host="https://example.cloud.databricks.com")
    model.client = mock_client

    assistant_message = Message(role="assistant")
    chunks = list(model.invoke_stream([Message(role="user", content="hello")], assistant_message))

    assert [chunk.content for chunk in chunks if chunk.content] == ["Hel", "lo"]
    assert chunks[-1].response_usage is not None
    assert chunks[-1].response_usage.total_tokens == 2


@pytest.mark.asyncio
async def test_ainvoke_stream_uses_native_stream_client():
    @asynccontextmanager
    async def stream_ctx():
        response = Mock()

        async def _aiter_lines():
            for item in [
                'data: {"id":"chatcmpl-1","choices":[{"delta":{"content":"Hel"},"index":0}]}',
                'data: {"id":"chatcmpl-1","choices":[{"delta":{"content":"lo"},"index":0}],"usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}}',
                "data: [DONE]",
            ]:
                yield item

        response.aiter_lines = _aiter_lines
        yield response

    mock_client = Mock()
    mock_client.stream.return_value = stream_ctx()

    model = Databricks(endpoint="served-endpoint", host="https://example.cloud.databricks.com")
    model.async_client = mock_client

    assistant_message = Message(role="assistant")
    chunks = []
    async for chunk in model.ainvoke_stream([Message(role="user", content="hello")], assistant_message):
        chunks.append(chunk)

    assert [chunk.content for chunk in chunks if chunk.content] == ["Hel", "lo"]
    assert chunks[-1].response_usage is not None
    assert chunks[-1].response_usage.total_tokens == 2
