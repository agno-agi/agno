"""
Unit tests for Perplexity metrics collection fix.

Tests the collect_metrics_on_completion flag that prevents
incorrect accumulation of cumulative token counts in streaming responses.
"""

from typing import Optional

from agno.models.metrics import MessageMetrics
from agno.models.perplexity.perplexity import Perplexity


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


def test_perplexity_collect_metrics_flag():
    """Test that Perplexity has collect_metrics_on_completion set to True."""
    model = Perplexity(id="sonar", api_key="test-key")
    assert model.collect_metrics_on_completion is True


def test_should_collect_metrics_on_completion():
    """Test that _should_collect_metrics only returns True on last chunk when flag is True."""
    model = Perplexity(id="sonar", api_key="test-key")
    usage = MockCompletionUsage(prompt_tokens=100, completion_tokens=20, total_tokens=120)

    # Test with no finish_reason (intermediate chunk) - should NOT collect
    response = MockChatCompletionChunk(usage=usage, finish_reason=None)
    assert model._should_collect_metrics(response) is False  # type: ignore[arg-type]

    # Test with finish_reason (last chunk) - should collect
    response = MockChatCompletionChunk(usage=usage, finish_reason="stop")
    assert model._should_collect_metrics(response) is True  # type: ignore[arg-type]


def test_perplexity_get_metrics_basic():
    """Test that Perplexity._get_metrics correctly converts CompletionUsage to Metrics."""
    model = Perplexity(id="sonar", api_key="test-key")
    usage = MockCompletionUsage(prompt_tokens=1965, completion_tokens=29, total_tokens=1994)

    metrics = model._get_metrics(usage)  # type: ignore[arg-type]

    assert isinstance(metrics, MessageMetrics)
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
    This test verifies that metrics are only collected on the last chunk.
    """
    model = Perplexity(id="sonar", api_key="test-key")

    chunks = [
        MockChatCompletionChunk(
            usage=MockCompletionUsage(prompt_tokens=1965, completion_tokens=1, total_tokens=1966),
            finish_reason=None,
        ),
        MockChatCompletionChunk(
            usage=MockCompletionUsage(prompt_tokens=1965, completion_tokens=2, total_tokens=1967),
            finish_reason=None,
        ),
        MockChatCompletionChunk(
            usage=MockCompletionUsage(prompt_tokens=1965, completion_tokens=3, total_tokens=1968),
            finish_reason=None,
        ),
        MockChatCompletionChunk(
            usage=MockCompletionUsage(prompt_tokens=1965, completion_tokens=29, total_tokens=1994),
            finish_reason="stop",
        ),
    ]

    collected_metrics = []
    for chunk in chunks:
        if model._should_collect_metrics(chunk):  # type: ignore[arg-type]
            metrics = model._get_metrics(chunk.usage)  # type: ignore[arg-type]
            collected_metrics.append(metrics)

    # Should only collect metrics from the last chunk
    assert len(collected_metrics) == 1
    assert collected_metrics[0].input_tokens == 1965
    assert collected_metrics[0].output_tokens == 29
    assert collected_metrics[0].total_tokens == 1994


def test_perplexity_get_metrics_with_none_values():
    """Test that Perplexity._get_metrics handles None values gracefully."""
    model = Perplexity(id="sonar", api_key="test-key")
    usage = MockCompletionUsage(prompt_tokens=None, completion_tokens=None, total_tokens=None)

    metrics = model._get_metrics(usage)  # type: ignore[arg-type]

    assert metrics.input_tokens == 0
    assert metrics.output_tokens == 0
    assert metrics.total_tokens == 0


def test_collect_metrics_with_different_finish_reasons():
    """Test that metrics are collected for all finish_reason values."""
    model = Perplexity(id="sonar", api_key="test-key")
    usage = MockCompletionUsage(prompt_tokens=100, completion_tokens=20, total_tokens=120)

    for finish_reason in ["stop", "length", "tool_calls", "content_filter"]:
        response = MockChatCompletionChunk(usage=usage, finish_reason=finish_reason)
        assert model._should_collect_metrics(response) is True  # type: ignore[arg-type]
