"""Unit tests for LiteLLM structured-output (response_format) forwarding."""

from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("litellm")

from pydantic import BaseModel

from agno.models.litellm import LiteLLM
from agno.models.message import Message


class Movie(BaseModel):
    title: str
    year: int


def _mock_response():
    """Minimal non-streaming litellm response."""
    response = MagicMock()
    message = response.choices[0].message
    message.content = '{"title": "Inception", "year": 2010}'
    message.tool_calls = None
    message.reasoning_content = None
    response.usage = None
    return response


def _messages():
    return [Message(role="user", content="A movie and its year")]


def test_default_flags_are_false():
    model = LiteLLM(id="gpt-4o")
    assert model.supports_native_structured_outputs is False
    assert model.supports_json_schema_outputs is False


def test_invoke_forwards_pydantic_when_native_supported():
    model = LiteLLM(id="gpt-4o", api_key="x", supports_native_structured_outputs=True)
    model.client = MagicMock()
    model.client.completion.return_value = _mock_response()

    model.invoke(messages=_messages(), assistant_message=Message(role="assistant", content=""), response_format=Movie)

    assert model.client.completion.call_args.kwargs["response_format"] is Movie


def test_invoke_forwards_dict_when_json_schema_supported():
    model = LiteLLM(id="gpt-4o", api_key="x", supports_json_schema_outputs=True)
    model.client = MagicMock()
    model.client.completion.return_value = _mock_response()

    fmt = {"type": "json_schema", "json_schema": {"name": "Movie", "schema": {"type": "object"}}}
    model.invoke(messages=_messages(), assistant_message=Message(role="assistant", content=""), response_format=fmt)

    assert model.client.completion.call_args.kwargs["response_format"] == fmt


def test_invoke_does_not_forward_when_neither_flag_set():
    # Critical for providers (e.g. Anthropic) that reject response_format.
    model = LiteLLM(id="anthropic/claude-haiku-4-5", api_key="x")
    model.client = MagicMock()
    model.client.completion.return_value = _mock_response()

    model.invoke(messages=_messages(), assistant_message=Message(role="assistant", content=""), response_format=Movie)

    assert "response_format" not in model.client.completion.call_args.kwargs


def test_invoke_does_not_forward_when_no_schema():
    model = LiteLLM(id="gpt-4o", api_key="x", supports_native_structured_outputs=True)
    model.client = MagicMock()
    model.client.completion.return_value = _mock_response()

    model.invoke(messages=_messages(), assistant_message=Message(role="assistant", content=""), response_format=None)

    assert "response_format" not in model.client.completion.call_args.kwargs


def test_invoke_stream_forwards_response_format():
    model = LiteLLM(id="gpt-4o", api_key="x", supports_native_structured_outputs=True)
    model.client = MagicMock()
    model.client.completion.return_value = iter([])

    list(
        model.invoke_stream(
            messages=_messages(), assistant_message=Message(role="assistant", content=""), response_format=Movie
        )
    )

    assert model.client.completion.call_args.kwargs["response_format"] is Movie


@pytest.mark.asyncio
async def test_ainvoke_forwards_response_format():
    model = LiteLLM(id="gpt-4o", api_key="x", supports_native_structured_outputs=True)
    model.client = MagicMock()
    model.client.acompletion = AsyncMock(return_value=_mock_response())

    await model.ainvoke(
        messages=_messages(), assistant_message=Message(role="assistant", content=""), response_format=Movie
    )

    assert model.client.acompletion.call_args.kwargs["response_format"] is Movie


@pytest.mark.asyncio
async def test_ainvoke_stream_forwards_response_format():
    async def _empty():
        for _ in []:
            yield _

    model = LiteLLM(id="gpt-4o", api_key="x", supports_native_structured_outputs=True)
    model.client = MagicMock()
    model.client.acompletion = AsyncMock(return_value=_empty())

    async for _ in model.ainvoke_stream(
        messages=_messages(), assistant_message=Message(role="assistant", content=""), response_format=Movie
    ):
        pass

    assert model.client.acompletion.call_args.kwargs["response_format"] is Movie
