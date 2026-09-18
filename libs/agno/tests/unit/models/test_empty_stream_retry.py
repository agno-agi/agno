import asyncio
from typing import Any, AsyncIterator, Iterator
from unittest.mock import patch

import pytest

from agno.media import Audio, File, Image, Video
from agno.metrics import MessageMetrics
from agno.models.base import Model, _has_usable_stream_output
from agno.models.response import ModelResponse


class StubModel(Model):
    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return ModelResponse()

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return ModelResponse()

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        yield ModelResponse()

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        yield ModelResponse()

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return ModelResponse()

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return ModelResponse()


@pytest.fixture
def model() -> StubModel:
    return StubModel(id="test-model", retries=2, delay_between_retries=0)


def test_sync_empty_stream_is_retried_and_chunks_are_preserved(model: StubModel):
    call_count = 0

    def mock_invoke_stream(**kwargs: Any) -> Iterator[ModelResponse]:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            yield ModelResponse(
                content="",
                provider_data={"attempt": 1},
                response_usage=MessageMetrics(input_tokens=1),
            )
            return
        yield ModelResponse(provider_data={"attempt": 2}, response_usage=MessageMetrics(input_tokens=2))
        yield ModelResponse(content="recovered")

    with patch.object(model, "invoke_stream", side_effect=mock_invoke_stream):
        responses = list(model._invoke_stream_with_retry(messages=[]))

    assert call_count == 2
    assert [response.provider_data for response in responses if response.provider_data] == [
        {"attempt": 1},
        {"attempt": 2},
    ]
    assert [response.response_usage.input_tokens for response in responses if response.response_usage] == [1, 2]
    assert responses[-1].content == "recovered"


def test_sync_all_empty_attempts_return_blank_response(model: StubModel):
    call_count = 0

    def mock_invoke_stream(**kwargs: Any) -> Iterator[ModelResponse]:
        nonlocal call_count
        call_count += 1
        yield ModelResponse(
            provider_data={"attempt": call_count},
            response_usage=MessageMetrics(input_tokens=call_count),
        )
        yield ModelResponse(content="")

    with patch.object(model, "invoke_stream", side_effect=mock_invoke_stream):
        responses = list(model._invoke_stream_with_retry(messages=[]))

    assert call_count == 3
    assert len(responses) == 6
    assert [response.provider_data for response in responses if response.provider_data] == [
        {"attempt": 1},
        {"attempt": 2},
        {"attempt": 3},
    ]
    assert responses[-1].content == ""


def test_sync_empty_stream_is_unchanged_without_retries(model: StubModel):
    model.retries = 0
    call_count = 0

    def mock_invoke_stream(**kwargs: Any) -> Iterator[ModelResponse]:
        nonlocal call_count
        call_count += 1
        yield ModelResponse(provider_data={"attempt": 1}, response_usage=MessageMetrics(input_tokens=1))
        yield ModelResponse(content="")

    with patch.object(model, "invoke_stream", side_effect=mock_invoke_stream):
        responses = list(model._invoke_stream_with_retry(messages=[]))

    assert call_count == 1
    assert len(responses) == 2
    assert responses[0].provider_data == {"attempt": 1}
    assert responses[1].content == ""


@pytest.mark.parametrize(
    "response",
    [
        ModelResponse(content=" "),
        ModelResponse(reasoning_content="thinking"),
        ModelResponse(redacted_reasoning_content="redacted"),
        ModelResponse(tool_calls=[{"id": "call-1"}]),
        ModelResponse(audio=Audio(content=b"audio")),
        ModelResponse(images=[Image(content=b"image")]),
        ModelResponse(videos=[Video(content=b"video")]),
        ModelResponse(audios=[Audio(content=b"audio")]),
        ModelResponse(files=[File(content=b"file")]),
    ],
    ids=["content", "reasoning", "redacted_reasoning", "tool_call", "audio", "image", "video", "audios", "file"],
)
def test_usable_stream_output_signals(response: ModelResponse):
    assert _has_usable_stream_output(response) is True


@pytest.mark.parametrize(
    "response",
    [ModelResponse(), ModelResponse(content=""), ModelResponse(provider_data={"request_id": "metadata-only"})],
    ids=["empty", "empty_content", "metadata_only"],
)
def test_empty_stream_output_signals(response: ModelResponse):
    assert _has_usable_stream_output(response) is False


def test_async_empty_stream_is_retried_and_chunks_are_preserved(model: StubModel):
    call_count = 0

    async def mock_ainvoke_stream(**kwargs: Any) -> AsyncIterator[ModelResponse]:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            yield ModelResponse(
                content="",
                provider_data={"attempt": 1},
                response_usage=MessageMetrics(input_tokens=1),
            )
            return
        yield ModelResponse(provider_data={"attempt": 2}, response_usage=MessageMetrics(input_tokens=2))
        yield ModelResponse(reasoning_content="recovered")

    async def collect_responses() -> list[ModelResponse]:
        return [response async for response in model._ainvoke_stream_with_retry(messages=[])]

    with patch.object(model, "ainvoke_stream", side_effect=mock_ainvoke_stream):
        responses = asyncio.run(collect_responses())

    assert call_count == 2
    assert [response.provider_data for response in responses if response.provider_data] == [
        {"attempt": 1},
        {"attempt": 2},
    ]
    assert [response.response_usage.input_tokens for response in responses if response.response_usage] == [1, 2]
    assert responses[-1].reasoning_content == "recovered"


def test_async_all_empty_attempts_return_blank_response(model: StubModel):
    call_count = 0

    async def mock_ainvoke_stream(**kwargs: Any) -> AsyncIterator[ModelResponse]:
        nonlocal call_count
        call_count += 1
        yield ModelResponse(
            provider_data={"attempt": call_count},
            response_usage=MessageMetrics(input_tokens=call_count),
        )
        yield ModelResponse(content="")

    async def collect_responses() -> list[ModelResponse]:
        return [response async for response in model._ainvoke_stream_with_retry(messages=[])]

    with patch.object(model, "ainvoke_stream", side_effect=mock_ainvoke_stream):
        responses = asyncio.run(collect_responses())

    assert call_count == 3
    assert len(responses) == 6
    assert [response.provider_data for response in responses if response.provider_data] == [
        {"attempt": 1},
        {"attempt": 2},
        {"attempt": 3},
    ]
    assert responses[-1].content == ""
