"""
Unit tests for Gemini metrics collection fix.

Tests the collect_metrics_on_completion flag that prevents
incorrect accumulation of cumulative token counts in streaming responses.
"""

from dataclasses import dataclass
from typing import Optional

from agno.models.base import MessageData, Model
from agno.models.metrics import Metrics
from agno.models.response import ModelResponse


@dataclass
class MockGeminiModel(Model):
    """Mock Gemini model for testing without google-genai dependency."""

    id: str = "gemini-2.0-flash-001"
    name: str = "Gemini"
    provider: str = "Google"
    collect_metrics_on_completion: bool = True
    api_key: Optional[str] = None

    def invoke(self, *args, **kwargs):
        raise NotImplementedError

    def invoke_stream(self, *args, **kwargs):
        raise NotImplementedError

    async def ainvoke(self, *args, **kwargs):
        raise NotImplementedError

    async def ainvoke_stream(self, *args, **kwargs):
        raise NotImplementedError

    def _parse_provider_response(self, *args, **kwargs):
        raise NotImplementedError

    def _parse_provider_response_delta(self, *args, **kwargs):
        raise NotImplementedError


@dataclass
class MockOpenAIModel(Model):
    """Mock OpenAI model for testing incremental metrics."""

    id: str = "gpt-4"
    name: str = "OpenAI"
    provider: str = "OpenAI"
    collect_metrics_on_completion: bool = False
    api_key: Optional[str] = None

    def invoke(self, *args, **kwargs):
        raise NotImplementedError

    def invoke_stream(self, *args, **kwargs):
        raise NotImplementedError

    async def ainvoke(self, *args, **kwargs):
        raise NotImplementedError

    async def ainvoke_stream(self, *args, **kwargs):
        raise NotImplementedError

    def _parse_provider_response(self, *args, **kwargs):
        raise NotImplementedError

    def _parse_provider_response_delta(self, *args, **kwargs):
        raise NotImplementedError


def test_gemini_collect_metrics_flag():
    """Test that Gemini-like models have collect_metrics_on_completion set to True."""
    model = MockGeminiModel()
    assert model.collect_metrics_on_completion is True


def test_gemini_streaming_metrics_not_summed():
    """
    Test that streaming metrics use the last chunk instead of summing.

    Gemini returns cumulative token counts in each streaming chunk.
    This test verifies that the final metrics reflect the last chunk's values,
    not the sum of all chunks.
    """
    model = MockGeminiModel()

    # Create a stream data object
    stream_data = MessageData()

    # Simulate streaming chunks with cumulative token counts
    # Each chunk has the same prompt tokens (5000) but same completion tokens
    chunks = [
        ModelResponse(
            role="assistant",
            content="First",
            response_usage=Metrics(input_tokens=5000, output_tokens=5000, total_tokens=10000),
        ),
        ModelResponse(
            role="assistant",
            content=" chunk",
            response_usage=Metrics(input_tokens=5000, output_tokens=5000, total_tokens=10000),
        ),
        ModelResponse(
            role="assistant",
            content=" of",
            response_usage=Metrics(input_tokens=5000, output_tokens=5000, total_tokens=10000),
        ),
        ModelResponse(
            role="assistant",
            content=" text",
            response_usage=Metrics(input_tokens=5000, output_tokens=5000, total_tokens=10000),
        ),
    ]

    # Process all chunks through _populate_stream_data
    for chunk in chunks:
        list(model._populate_stream_data(stream_data=stream_data, model_response_delta=chunk))

    # Verify that metrics reflect the last chunk, not the sum
    assert stream_data.response_metrics is not None
    assert stream_data.response_metrics.input_tokens == 5000  # Not 20000 (5000 * 4)
    assert stream_data.response_metrics.output_tokens == 5000  # Not 20000 (5000 * 4)
    assert stream_data.response_metrics.total_tokens == 10000  # Not 40000 (10000 * 4)


def test_gemini_streaming_metrics_cumulative_pattern():
    """
    Test realistic cumulative token count pattern from Gemini.

    This simulates the actual pattern where prompt tokens stay constant
    and completion tokens increment with each chunk.
    """
    model = MockGeminiModel(id="gemini-2.5-flash-lite")

    stream_data = MessageData()

    # Realistic cumulative pattern: prompt stays same, completion increments
    chunks = [
        ModelResponse(
            role="assistant",
            content="The",
            response_usage=Metrics(input_tokens=189, output_tokens=1, total_tokens=190),
        ),
        ModelResponse(
            role="assistant",
            content=" answer",
            response_usage=Metrics(input_tokens=189, output_tokens=2, total_tokens=191),
        ),
        ModelResponse(
            role="assistant",
            content=" is",
            response_usage=Metrics(input_tokens=189, output_tokens=3, total_tokens=192),
        ),
        ModelResponse(
            role="assistant",
            content=" 42",
            response_usage=Metrics(input_tokens=189, output_tokens=4, total_tokens=193),
        ),
    ]

    for chunk in chunks:
        list(model._populate_stream_data(stream_data=stream_data, model_response_delta=chunk))

    # Should have the final cumulative values, not the sum
    assert stream_data.response_metrics is not None
    assert stream_data.response_metrics.input_tokens == 189  # Not 756 (189 * 4)
    assert stream_data.response_metrics.output_tokens == 4  # Not 10 (1+2+3+4)
    assert stream_data.response_metrics.total_tokens == 193  # Not 766


def test_gemini_streaming_with_cache_tokens():
    """Test that cached tokens are also handled correctly (not summed)."""
    model = MockGeminiModel()

    stream_data = MessageData()

    chunks = [
        ModelResponse(
            role="assistant",
            content="Cached",
            response_usage=Metrics(input_tokens=1000, output_tokens=1, cache_read_tokens=5000, total_tokens=1001),
        ),
        ModelResponse(
            role="assistant",
            content=" response",
            response_usage=Metrics(input_tokens=1000, output_tokens=2, cache_read_tokens=5000, total_tokens=1002),
        ),
    ]

    for chunk in chunks:
        list(model._populate_stream_data(stream_data=stream_data, model_response_delta=chunk))

    # Cache tokens should also not be summed
    assert stream_data.response_metrics is not None
    assert stream_data.response_metrics.cache_read_tokens == 5000  # Not 10000


def test_gemini_streaming_metrics_with_none_usage():
    """Test that chunks without usage data don't cause errors."""
    model = MockGeminiModel()

    stream_data = MessageData()

    chunks = [
        ModelResponse(role="assistant", content="No", response_usage=None),
        ModelResponse(
            role="assistant",
            content=" usage",
            response_usage=Metrics(input_tokens=100, output_tokens=2, total_tokens=102),
        ),
    ]

    for chunk in chunks:
        list(model._populate_stream_data(stream_data=stream_data, model_response_delta=chunk))

    # Should have metrics from the second chunk only
    assert stream_data.response_metrics is not None
    assert stream_data.response_metrics.input_tokens == 100
    assert stream_data.response_metrics.output_tokens == 2


def test_openai_incremental_metrics_still_summed():
    """Test that models with incremental counts still sum correctly."""
    model = MockOpenAIModel()

    stream_data = MessageData()

    # OpenAI-style incremental counts
    chunks = [
        ModelResponse(
            role="assistant",
            content="The",
            response_usage=Metrics(input_tokens=100, output_tokens=1, total_tokens=101),
        ),
        ModelResponse(
            role="assistant",
            content=" answer",
            response_usage=Metrics(input_tokens=0, output_tokens=1, total_tokens=1),
        ),
        ModelResponse(
            role="assistant",
            content=" is",
            response_usage=Metrics(input_tokens=0, output_tokens=1, total_tokens=1),
        ),
    ]

    for chunk in chunks:
        list(model._populate_stream_data(stream_data=stream_data, model_response_delta=chunk))

    # Should sum the metrics for incremental providers
    assert stream_data.response_metrics is not None
    assert stream_data.response_metrics.input_tokens == 100  # 100 + 0 + 0
    assert stream_data.response_metrics.output_tokens == 3  # 1 + 1 + 1
    assert stream_data.response_metrics.total_tokens == 103  # 101 + 1 + 1
