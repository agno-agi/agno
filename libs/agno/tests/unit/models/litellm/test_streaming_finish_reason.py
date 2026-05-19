"""Unit tests for LiteLLM streaming finish_reason propagation.

Regression coverage for agno-agi/agno#7985: when streaming through the
LiteLLM model, the `finish_reason` returned by LiteLLM (e.g. 'length',
'stop') must be propagated through Agno's response on the same
`provider_data` path that other providers (e.g. OpenAI) use for
provider-specific response metadata.
"""

import pytest

pytest.importorskip("litellm")

from agno.models.litellm import LiteLLM
from agno.models.message import Message


class MockChoiceDelta:
    """Mock streaming delta payload."""

    def __init__(self, content=None):
        self.content = content
        self.reasoning_content = None
        self.tool_calls = None


class MockStreamChoice:
    """Mock streaming choice carrying a delta and a finish_reason."""

    def __init__(self, content=None, finish_reason=None):
        self.delta = MockChoiceDelta(content=content)
        self.finish_reason = finish_reason


class MockStreamChunk:
    """Mock LiteLLM streaming chunk."""

    def __init__(self, content=None, finish_reason=None, usage=None):
        self.choices = [MockStreamChoice(content=content, finish_reason=finish_reason)]
        self.usage = usage


class MockClient:
    """Mock LiteLLM client returning a fixed sequence of streaming chunks."""

    def __init__(self, chunks):
        self._chunks = chunks

    def completion(self, **kwargs):
        for chunk in self._chunks:
            yield chunk

    async def acompletion(self, **kwargs):
        async def _gen():
            for chunk in self._chunks:
                yield chunk

        return _gen()


def _length_chunks():
    return [
        MockStreamChunk(content="Artificial "),
        MockStreamChunk(content="intelligence"),
        MockStreamChunk(content=None, finish_reason="length"),
    ]


def test_delta_parser_exposes_finish_reason_via_provider_data():
    """The streaming delta parser must surface finish_reason in provider_data."""
    model = LiteLLM(id="gpt-4o")

    final_chunk = MockStreamChunk(content=None, finish_reason="length")
    model_response = model._parse_provider_response_delta(final_chunk)

    assert model_response.provider_data is not None
    assert model_response.provider_data.get("finish_reason") == "length"


def test_non_streaming_parser_exposes_finish_reason_via_provider_data():
    """Non-streaming path must expose finish_reason consistently with streaming."""
    model = LiteLLM(id="gpt-4o")

    class _Msg:
        content = "done"
        reasoning_content = None
        tool_calls = None

    class _Choice:
        message = _Msg()
        finish_reason = "stop"

    class _Resp:
        choices = [_Choice()]
        usage = None

    model_response = model._parse_provider_response(_Resp())

    assert model_response.provider_data is not None
    assert model_response.provider_data.get("finish_reason") == "stop"


def test_sync_streaming_propagates_finish_reason():
    """invoke_stream must yield a delta exposing finish_reason='length'."""
    model = LiteLLM(id="gpt-4o")
    model.client = MockClient(_length_chunks())

    assistant_message = Message(role="assistant")
    finish_reasons = []
    for delta in model.invoke_stream(
        messages=[Message(role="user", content="hi")], assistant_message=assistant_message
    ):
        if delta.provider_data and delta.provider_data.get("finish_reason"):
            finish_reasons.append(delta.provider_data["finish_reason"])

    assert "length" in finish_reasons


@pytest.mark.asyncio
async def test_async_streaming_propagates_finish_reason():
    """ainvoke_stream must yield a delta exposing finish_reason='length'."""
    model = LiteLLM(id="gpt-4o")
    model.client = MockClient(_length_chunks())

    assistant_message = Message(role="assistant")
    finish_reasons = []
    async for delta in model.ainvoke_stream(
        messages=[Message(role="user", content="hi")], assistant_message=assistant_message
    ):
        if delta.provider_data and delta.provider_data.get("finish_reason"):
            finish_reasons.append(delta.provider_data["finish_reason"])

    assert "length" in finish_reasons
