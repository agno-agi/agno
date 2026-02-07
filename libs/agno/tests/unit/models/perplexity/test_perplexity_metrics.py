"""
Unit tests for Perplexity metrics collection fix.

Tests the is_cumulative_usage flag that prevents
incorrect accumulation of cumulative token counts in streaming responses.
"""

from typing import Optional

from agno.models.base import MessageData
from agno.models.metrics import Metrics
from agno.models.perplexity.perplexity import Perplexity
from agno.models.response import ModelResponse


class MockCompletionUsage:
    """Mock CompletionUsage object for testing."""

    def __init__(
        self,
        prompt_tokens: Optional[int] = 0,
        completion_tokens: Optional[int] = 0,
        total_tokens: Optional[int] = 0,
        prompt_tokens_details=None,
        completion_tokens_details=None,
    ):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = total_tokens
        self.prompt_tokens_details = prompt_tokens_details
        self.completion_tokens_details = completion_tokens_details


class MockChoice:
    """Mock Choice object for testing."""

    def __init__(self, finish_reason=None):
        self.finish_reason = finish_reason


class MockChatCompletionChunk:
    """Mock ChatCompletionChunk object for testing."""

    def __init__(self, usage=None, finish_reason=None):
        self.usage = usage
        self.choices = [MockChoice(finish_reason=finish_reason)]


def test_perplexity_is_cumulative_usage_flag():
    """Test that Perplexity has is_cumulative_usage set to True."""
    model = Perplexity(id="sonar", api_key="test-key")
    assert model.is_cumulative_usage is True


def test_perplexity_get_metrics_basic():
    """Test that Perplexity._get_metrics correctly converts CompletionUsage to Metrics."""
    model = Perplexity(id="sonar", api_key="test-key")
    usage = MockCompletionUsage(prompt_tokens=1965, completion_tokens=29, total_tokens=1994)

    metrics = model._get_metrics(usage)  # type: ignore[arg-type]

    assert isinstance(metrics, Metrics)
    assert metrics.input_tokens == 1965
    assert metrics.output_tokens == 29
    assert metrics.total_tokens == 1994


def test_perplexity_get_metrics_with_details():
    """Test that Perplexity._get_metrics correctly handles prompt and completion token details."""
    model = Perplexity(id="sonar", api_key="test-key")

    class MockPromptTokensDetails:
        def __init__(self):
            self.audio_tokens = 10
            self.cached_tokens = 500

    class MockCompletionTokensDetails:
        def __init__(self):
            self.audio_tokens = 5
            self.reasoning_tokens = 100

    usage = MockCompletionUsage(
        prompt_tokens=1965,
        completion_tokens=29,
        total_tokens=1994,
        prompt_tokens_details=MockPromptTokensDetails(),
        completion_tokens_details=MockCompletionTokensDetails(),
    )

    metrics = model._get_metrics(usage)  # type: ignore[arg-type]

    assert metrics.input_tokens == 1965
    assert metrics.output_tokens == 29
    assert metrics.total_tokens == 1994
    assert metrics.audio_input_tokens == 10
    assert metrics.cache_read_tokens == 500
    assert metrics.audio_output_tokens == 5
    assert metrics.reasoning_tokens == 100


def test_perplexity_streaming_metrics_simulation():
    """
    Simulate the streaming scenario that was causing the bug.

    Perplexity returns cumulative token counts (1, 2, 3, ..., N) in each chunk.
    This test verifies that metrics are replaced (not accumulated) during streaming.
    """
    model = Perplexity(id="sonar", api_key="test-key")
    stream_data = MessageData()

    # First chunk with cumulative metrics
    response_delta_1 = ModelResponse(
        response_usage=Metrics(
            input_tokens=1965,
            output_tokens=1,
            total_tokens=1966,
        )
    )
    list(model._populate_stream_data(stream_data, response_delta_1))

    # Metrics should be set
    assert stream_data.response_metrics is not None
    assert stream_data.response_metrics.input_tokens == 1965
    assert stream_data.response_metrics.output_tokens == 1
    assert stream_data.response_metrics.total_tokens == 1966

    # Second chunk with cumulative metrics
    response_delta_2 = ModelResponse(
        response_usage=Metrics(
            input_tokens=1965,
            output_tokens=2,
            total_tokens=1967,
        )
    )
    list(model._populate_stream_data(stream_data, response_delta_2))

    # Metrics should be replaced, not accumulated
    assert stream_data.response_metrics.input_tokens == 1965
    assert stream_data.response_metrics.output_tokens == 2
    assert stream_data.response_metrics.total_tokens == 1967

    # Third chunk with cumulative metrics
    response_delta_3 = ModelResponse(
        response_usage=Metrics(
            input_tokens=1965,
            output_tokens=3,
            total_tokens=1968,
        )
    )
    list(model._populate_stream_data(stream_data, response_delta_3))

    # Metrics should be replaced, not accumulated
    assert stream_data.response_metrics.input_tokens == 1965
    assert stream_data.response_metrics.output_tokens == 3
    assert stream_data.response_metrics.total_tokens == 1968

    # Final chunk with cumulative metrics
    response_delta_4 = ModelResponse(
        response_usage=Metrics(
            input_tokens=1965,
            output_tokens=29,
            total_tokens=1994,
        )
    )
    list(model._populate_stream_data(stream_data, response_delta_4))

    # Final metrics should reflect the last chunk (cumulative total)
    assert stream_data.response_metrics.input_tokens == 1965
    assert stream_data.response_metrics.output_tokens == 29
    assert stream_data.response_metrics.total_tokens == 1994


def test_perplexity_get_metrics_with_none_values():
    """Test that Perplexity._get_metrics handles None values gracefully."""
    model = Perplexity(id="sonar", api_key="test-key")
    usage = MockCompletionUsage(prompt_tokens=None, completion_tokens=None, total_tokens=None)

    metrics = model._get_metrics(usage)  # type: ignore[arg-type]

    assert metrics.input_tokens == 0
    assert metrics.output_tokens == 0
    assert metrics.total_tokens == 0


def test_perplexity_cumulative_usage_with_detailed_metrics():
    """Test that cumulative usage correctly replaces detailed metrics like reasoning_tokens."""
    model = Perplexity(id="sonar", api_key="test-key")
    stream_data = MessageData()

    # First chunk with detailed metrics
    response_delta_1 = ModelResponse(
        response_usage=Metrics(
            input_tokens=100,
            output_tokens=5,
            total_tokens=105,
            reasoning_tokens=10,
            cache_read_tokens=50,
        )
    )
    list(model._populate_stream_data(stream_data, response_delta_1))

    assert stream_data.response_metrics is not None
    assert stream_data.response_metrics.input_tokens == 100
    assert stream_data.response_metrics.output_tokens == 5
    assert stream_data.response_metrics.reasoning_tokens == 10
    assert stream_data.response_metrics.cache_read_tokens == 50

    # Second chunk with updated cumulative metrics
    response_delta_2 = ModelResponse(
        response_usage=Metrics(
            input_tokens=100,
            output_tokens=10,
            total_tokens=110,
            reasoning_tokens=20,
            cache_read_tokens=50,
        )
    )
    list(model._populate_stream_data(stream_data, response_delta_2))

    # All metrics should be replaced with the new cumulative values
    assert stream_data.response_metrics.input_tokens == 100
    assert stream_data.response_metrics.output_tokens == 10
    assert stream_data.response_metrics.reasoning_tokens == 20
    assert stream_data.response_metrics.cache_read_tokens == 50
