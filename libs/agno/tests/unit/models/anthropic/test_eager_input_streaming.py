"""Tests for Claude eager_input_streaming on streamed tool calls."""

from contextlib import contextmanager
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

pytest.importorskip("anthropic")

from agno.models.anthropic.claude import Claude
from agno.models.message import Message
from agno.models.vertexai.claude import Claude as VertexAIClaude


def _client_tool(name: str = "save_doc", strict: bool = False) -> Dict[str, Any]:
    tool: Dict[str, Any] = {
        "type": "function",
        "function": {
            "name": name,
            "description": "Save a document.",
            "parameters": {
                "type": "object",
                "properties": {"content": {"type": "string", "description": "Body"}},
                "required": ["content"],
            },
        },
    }
    if strict:
        tool["strict"] = True
    return tool


def _messages() -> List[Message]:
    return [Message(role="user", content="Write a document")]


def _mock_sync_stream_client():
    captured: Dict[str, Any] = {}
    client = MagicMock()
    client.is_closed.return_value = False

    @contextmanager
    def _stream(**kwargs):
        captured.update(kwargs)
        yield iter(())

    client.messages.stream.side_effect = _stream
    client.beta.messages.stream.side_effect = _stream
    client.messages.create.side_effect = lambda **kwargs: (
        captured.update(kwargs) or MagicMock(role="assistant", content=[], usage=None)
    )
    client.beta.messages.create.side_effect = client.messages.create.side_effect
    return client, captured


def _mock_async_stream_client():
    captured: Dict[str, Any] = {}
    client = MagicMock()
    client.is_closed.return_value = False

    class _AsyncStreamCtx:
        def __init__(self, kwargs: Dict[str, Any]) -> None:
            captured.update(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    client.messages.stream.side_effect = lambda **kwargs: _AsyncStreamCtx(kwargs)
    client.beta.messages.stream.side_effect = lambda **kwargs: _AsyncStreamCtx(kwargs)

    async def _acreate(**kwargs):
        captured.update(kwargs)
        return MagicMock(role="assistant", content=[], usage=None)

    client.messages.create.side_effect = _acreate
    client.beta.messages.create.side_effect = _acreate
    return client, captured


def test_eager_input_streaming_defaults_false_and_serializes():
    model = Claude(id="claude-sonnet-5-5", api_key="x")
    assert model.eager_input_streaming is False
    assert model.to_dict()["eager_input_streaming"] is False

    enabled = Claude(id="claude-sonnet-5-5", api_key="x", eager_input_streaming=True)
    assert enabled.to_dict()["eager_input_streaming"] is True

    vertex = VertexAIClaude()
    assert vertex.eager_input_streaming is False


def test_invoke_stream_adds_eager_input_streaming_to_eligible_client_tools():
    client, captured = _mock_sync_stream_client()
    model = Claude(id="claude-sonnet-5-5", api_key="x", eager_input_streaming=True, cache_tools=True)
    model.client = client

    tools = [
        _client_tool("save_doc"),
        _client_tool("strict_doc", strict=True),
        {"type": "web_search_20250305", "name": "web_search"},
    ]

    list(model.invoke_stream(_messages(), Message(role="assistant"), tools=tools))

    sent_tools = captured["tools"]
    assert sent_tools[0]["name"] == "save_doc"
    assert sent_tools[0]["eager_input_streaming"] is True
    assert "eager_input_streaming" not in sent_tools[1]
    assert sent_tools[1]["strict"] is True
    assert "eager_input_streaming" not in sent_tools[2]
    assert sent_tools[2]["cache_control"] == {"type": "ephemeral"}


def test_invoke_stream_beta_surface_adds_eager_input_streaming():
    client, captured = _mock_sync_stream_client()
    model = Claude(
        id="claude-sonnet-5-5",
        api_key="x",
        eager_input_streaming=True,
        betas=["context-1m-2025-08-07"],
    )
    model.client = client

    list(model.invoke_stream(_messages(), Message(role="assistant"), tools=[_client_tool("save_doc")]))

    assert client.beta.messages.stream.called
    assert captured["tools"][0]["eager_input_streaming"] is True


def test_non_streamed_invoke_does_not_add_eager_input_streaming():
    client, captured = _mock_sync_stream_client()
    model = Claude(id="claude-sonnet-5-5", api_key="x", eager_input_streaming=True)
    model.client = client

    model.invoke(_messages(), Message(role="assistant"), tools=[_client_tool("save_doc")])

    assert "eager_input_streaming" not in captured["tools"][0]


def test_invoke_stream_when_disabled_omits_eager_input_streaming():
    client, captured = _mock_sync_stream_client()
    model = Claude(id="claude-sonnet-5-5", api_key="x", eager_input_streaming=False)
    model.client = client

    list(model.invoke_stream(_messages(), Message(role="assistant"), tools=[_client_tool("save_doc")]))

    assert "eager_input_streaming" not in captured["tools"][0]


@pytest.mark.asyncio
async def test_ainvoke_stream_and_ainvoke_respect_streaming_only():
    client, captured = _mock_async_stream_client()
    model = Claude(id="claude-sonnet-5-5", api_key="x", eager_input_streaming=True)
    model.async_client = client

    tools = [
        _client_tool("save_doc"),
        _client_tool("strict_doc", strict=True),
        {"type": "web_search_20250305", "name": "web_search"},
    ]
    async for _ in model.ainvoke_stream(_messages(), Message(role="assistant"), tools=tools):
        pass

    assert captured["tools"][0]["eager_input_streaming"] is True
    assert "eager_input_streaming" not in captured["tools"][1]
    assert "eager_input_streaming" not in captured["tools"][2]

    captured.clear()
    await model.ainvoke(_messages(), Message(role="assistant"), tools=[_client_tool("save_doc")])
    assert "eager_input_streaming" not in captured["tools"][0]
