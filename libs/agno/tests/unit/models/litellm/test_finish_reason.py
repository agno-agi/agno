"""Unit tests for LiteLLM finish_reason propagation."""

import pytest

pytest.importorskip("litellm")

from agno.models.litellm import LiteLLM


class MockDelta:
    def __init__(self, content=None, tool_calls=None, reasoning_content=None):
        self.content = content
        self.tool_calls = tool_calls
        self.reasoning_content = reasoning_content


class MockChoice:
    def __init__(self, delta=None, message=None, finish_reason=None):
        self.delta = delta
        self.message = message
        self.finish_reason = finish_reason


class MockMessage:
    def __init__(self, content=None, tool_calls=None, reasoning_content=None):
        self.content = content
        self.tool_calls = tool_calls
        self.reasoning_content = reasoning_content


class MockResponse:
    def __init__(self, choices=None, usage=None):
        self.choices = choices or []
        self.usage = usage


def test_streaming_finish_reason_stop():
    """finish_reason='stop' on final streaming chunk should appear in provider_data."""
    model = LiteLLM(id="test-model")
    chunk = MockResponse(
        choices=[MockChoice(delta=MockDelta(content="done"), finish_reason="stop")]
    )
    result = model._parse_provider_response_delta(chunk)
    assert result.provider_data is not None
    assert result.provider_data["finish_reason"] == "stop"


def test_streaming_finish_reason_length():
    """finish_reason='length' (truncated) should be propagated so callers can detect it."""
    model = LiteLLM(id="test-model")
    chunk = MockResponse(
        choices=[MockChoice(delta=MockDelta(content="truncat"), finish_reason="length")]
    )
    result = model._parse_provider_response_delta(chunk)
    assert result.provider_data is not None
    assert result.provider_data["finish_reason"] == "length"


def test_streaming_no_finish_reason():
    """Intermediate streaming chunks without finish_reason should not set provider_data."""
    model = LiteLLM(id="test-model")
    chunk = MockResponse(
        choices=[MockChoice(delta=MockDelta(content="hello"), finish_reason=None)]
    )
    result = model._parse_provider_response_delta(chunk)
    assert result.provider_data is None


def test_non_streaming_finish_reason():
    """Non-streaming responses should also propagate finish_reason."""
    model = LiteLLM(id="test-model")
    response = MockResponse(
        choices=[MockChoice(message=MockMessage(content="The answer is 42."), finish_reason="stop")]
    )
    result = model._parse_provider_response(response)
    assert result.provider_data is not None
    assert result.provider_data["finish_reason"] == "stop"


def test_non_streaming_finish_reason_length():
    """Non-streaming truncated response should expose finish_reason='length'."""
    model = LiteLLM(id="test-model")
    response = MockResponse(
        choices=[MockChoice(message=MockMessage(content="This essay is about"), finish_reason="length")]
    )
    result = model._parse_provider_response(response)
    assert result.provider_data is not None
    assert result.provider_data["finish_reason"] == "length"
