"""Tests for retrying streams that complete without usable output.

A provider can return HTTP success and close a stream after emitting only
empty content or metadata. When retries are enabled, such a stream should
consume a retry attempt instead of being treated as successful.

See https://github.com/agno-agi/agno/issues/8952
"""

import os
from unittest.mock import patch

import pytest

# Set test API key to avoid env var lookup errors
os.environ.setdefault("OPENAI_API_KEY", "test-key-for-testing")

from agno.exceptions import ModelProviderError
from agno.models.openai.chat import OpenAIChat
from agno.models.response import ModelResponse


@pytest.fixture
def model_with_one_retry():
    """Create a model instance with 1 retry and no delay."""
    return OpenAIChat(id="gpt-4o-mini", retries=1, delay_between_retries=0)


@pytest.fixture
def model_without_retries():
    """Create a model instance with retries disabled."""
    return OpenAIChat(id="gpt-4o-mini", retries=0)


def _empty_attempt():
    """Chunks for a stream that completes without usable output."""
    return [
        ModelResponse(content=""),
        ModelResponse(response_usage={"input_tokens": 1}),  # type: ignore
    ]


def _recovered_attempt():
    """Chunks for a stream that produces usable output."""
    return [ModelResponse(content="recovered")]


# =============================================================================
# Tests for _response_has_usable_output helper
# =============================================================================


@pytest.mark.parametrize(
    "response,expected",
    [
        (ModelResponse(content="hello"), True),
        (ModelResponse(content="  "), True),  # whitespace remains valid content
        (ModelResponse(content=""), False),
        (ModelResponse(content=None), False),
        (ModelResponse(reasoning_content="thinking"), True),
        (ModelResponse(redacted_reasoning_content="redacted"), True),
        (ModelResponse(tool_calls=[{"id": "1", "function": {"name": "f"}}]), True),
        (ModelResponse(response_usage={"input_tokens": 1}), False),  # type: ignore
        (ModelResponse(), False),
    ],
    ids=[
        "content",
        "whitespace_content",
        "empty_content",
        "no_content",
        "reasoning",
        "redacted_reasoning",
        "tool_calls",
        "usage_only",
        "empty_chunk",
    ],
)
def test_response_has_usable_output(model_with_one_retry, response, expected):
    assert model_with_one_retry._response_has_usable_output(response) is expected


# =============================================================================
# Sync streaming
# =============================================================================


def test_sync_stream_empty_output_is_retried(model_with_one_retry):
    """A stream completing without usable output should consume a retry attempt."""
    call_count = 0

    def mock_invoke_stream(**kwargs):
        nonlocal call_count
        call_count += 1
        attempt = _empty_attempt() if call_count == 1 else _recovered_attempt()
        yield from attempt

    with patch.object(model_with_one_retry, "invoke_stream", side_effect=mock_invoke_stream):
        responses = list(model_with_one_retry._invoke_stream_with_retry(messages=[]))

    assert call_count == 2, "Empty stream should have triggered a retry"
    assert [r.content for r in responses] == ["recovered"]
    # Metadata-only chunks from the discarded attempt must not be emitted downstream
    assert all(r.response_usage is None for r in responses)


def test_sync_stream_metadata_flushed_when_usable_output_arrives(model_with_one_retry):
    """Metadata received before the first usable chunk is flushed in order."""

    def mock_invoke_stream(**kwargs):
        yield ModelResponse(response_usage={"input_tokens": 1})  # type: ignore
        yield ModelResponse(content="hello")
        yield ModelResponse(content=" world")

    with patch.object(model_with_one_retry, "invoke_stream", side_effect=mock_invoke_stream):
        responses = list(model_with_one_retry._invoke_stream_with_retry(messages=[]))

    assert len(responses) == 3
    assert responses[0].response_usage is not None
    assert [r.content for r in responses] == [None, "hello", " world"]


def test_sync_stream_all_empty_attempts_raise(model_with_one_retry):
    """If every attempt completes without usable output, raise ModelProviderError."""
    call_count = 0

    def mock_invoke_stream(**kwargs):
        nonlocal call_count
        call_count += 1
        yield from _empty_attempt()

    with patch.object(model_with_one_retry, "invoke_stream", side_effect=mock_invoke_stream):
        with pytest.raises(ModelProviderError):
            list(model_with_one_retry._invoke_stream_with_retry(messages=[]))

    assert call_count == 2, "All retry attempts should have been consumed"


def test_sync_stream_empty_output_not_retried_when_retries_disabled(model_without_retries):
    """With retries=0 the previous behavior is unchanged: the stream passes through."""
    call_count = 0

    def mock_invoke_stream(**kwargs):
        nonlocal call_count
        call_count += 1
        yield from _empty_attempt()

    with patch.object(model_without_retries, "invoke_stream", side_effect=mock_invoke_stream):
        responses = list(model_without_retries._invoke_stream_with_retry(messages=[]))

    assert call_count == 1
    assert len(responses) == 2


def test_sync_stream_error_after_usable_output_is_not_retried(model_with_one_retry):
    """Once usable output has been emitted, an error must not restart the stream."""
    call_count = 0

    def mock_invoke_stream(**kwargs):
        nonlocal call_count
        call_count += 1
        yield ModelResponse(content="partial")
        raise ModelProviderError("Server error", status_code=500)

    received = []
    with patch.object(model_with_one_retry, "invoke_stream", side_effect=mock_invoke_stream):
        with pytest.raises(ModelProviderError):
            for response in model_with_one_retry._invoke_stream_with_retry(messages=[]):
                received.append(response)

    assert call_count == 1, "Stream must not restart after delivering usable output"
    assert [r.content for r in received] == ["partial"]


def test_sync_stream_error_before_usable_output_is_still_retried(model_with_one_retry):
    """Provider errors before any usable output keep the existing retry behavior."""
    call_count = 0

    def mock_invoke_stream(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ModelProviderError("Server error", status_code=500)
        yield from _recovered_attempt()

    with patch.object(model_with_one_retry, "invoke_stream", side_effect=mock_invoke_stream):
        responses = list(model_with_one_retry._invoke_stream_with_retry(messages=[]))

    assert call_count == 2
    assert [r.content for r in responses] == ["recovered"]


@pytest.mark.parametrize(
    "usable_chunk",
    [
        ModelResponse(content="  "),
        ModelResponse(tool_calls=[{"id": "1", "function": {"name": "f"}}]),
        ModelResponse(reasoning_content="thinking"),
    ],
    ids=["whitespace_content", "tool_calls", "reasoning"],
)
def test_sync_stream_usable_chunk_variants_prevent_retry(model_with_one_retry, usable_chunk):
    """Whitespace content, tool calls, and reasoning all count as usable output."""
    call_count = 0

    def mock_invoke_stream(**kwargs):
        nonlocal call_count
        call_count += 1
        yield usable_chunk

    with patch.object(model_with_one_retry, "invoke_stream", side_effect=mock_invoke_stream):
        responses = list(model_with_one_retry._invoke_stream_with_retry(messages=[]))

    assert call_count == 1, "Usable output should not trigger a retry"
    assert len(responses) == 1


# =============================================================================
# Async streaming
# =============================================================================


@pytest.mark.asyncio
async def test_async_stream_empty_output_is_retried(model_with_one_retry):
    """An async stream completing without usable output should consume a retry attempt."""
    call_count = 0

    async def mock_ainvoke_stream(**kwargs):
        nonlocal call_count
        call_count += 1
        attempt = _empty_attempt() if call_count == 1 else _recovered_attempt()
        for chunk in attempt:
            yield chunk

    with patch.object(model_with_one_retry, "ainvoke_stream", side_effect=mock_ainvoke_stream):
        responses = [r async for r in model_with_one_retry._ainvoke_stream_with_retry(messages=[])]

    assert call_count == 2, "Empty async stream should have triggered a retry"
    assert [r.content for r in responses] == ["recovered"]
    assert all(r.response_usage is None for r in responses)


@pytest.mark.asyncio
async def test_async_stream_metadata_flushed_when_usable_output_arrives(model_with_one_retry):
    """Metadata received before the first usable chunk is flushed in order."""

    async def mock_ainvoke_stream(**kwargs):
        yield ModelResponse(response_usage={"input_tokens": 1})  # type: ignore
        yield ModelResponse(content="hello")

    with patch.object(model_with_one_retry, "ainvoke_stream", side_effect=mock_ainvoke_stream):
        responses = [r async for r in model_with_one_retry._ainvoke_stream_with_retry(messages=[])]

    assert len(responses) == 2
    assert responses[0].response_usage is not None
    assert responses[1].content == "hello"


@pytest.mark.asyncio
async def test_async_stream_all_empty_attempts_raise(model_with_one_retry):
    """If every async attempt completes without usable output, raise ModelProviderError."""
    call_count = 0

    async def mock_ainvoke_stream(**kwargs):
        nonlocal call_count
        call_count += 1
        for chunk in _empty_attempt():
            yield chunk

    with patch.object(model_with_one_retry, "ainvoke_stream", side_effect=mock_ainvoke_stream):
        with pytest.raises(ModelProviderError):
            async for _ in model_with_one_retry._ainvoke_stream_with_retry(messages=[]):
                pass

    assert call_count == 2, "All retry attempts should have been consumed"


@pytest.mark.asyncio
async def test_async_stream_empty_output_not_retried_when_retries_disabled(model_without_retries):
    """With retries=0 the previous behavior is unchanged: the stream passes through."""
    call_count = 0

    async def mock_ainvoke_stream(**kwargs):
        nonlocal call_count
        call_count += 1
        for chunk in _empty_attempt():
            yield chunk

    with patch.object(model_without_retries, "ainvoke_stream", side_effect=mock_ainvoke_stream):
        responses = [r async for r in model_without_retries._ainvoke_stream_with_retry(messages=[])]

    assert call_count == 1
    assert len(responses) == 2


@pytest.mark.asyncio
async def test_async_stream_error_after_usable_output_is_not_retried(model_with_one_retry):
    """Once usable output has been emitted, an async error must not restart the stream."""
    call_count = 0

    async def mock_ainvoke_stream(**kwargs):
        nonlocal call_count
        call_count += 1
        yield ModelResponse(content="partial")
        raise ModelProviderError("Server error", status_code=500)

    received = []
    with patch.object(model_with_one_retry, "ainvoke_stream", side_effect=mock_ainvoke_stream):
        with pytest.raises(ModelProviderError):
            async for response in model_with_one_retry._ainvoke_stream_with_retry(messages=[]):
                received.append(response)

    assert call_count == 1, "Async stream must not restart after delivering usable output"
    assert [r.content for r in received] == ["partial"]
