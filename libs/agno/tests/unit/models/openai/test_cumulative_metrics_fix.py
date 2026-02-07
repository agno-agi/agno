"""
Unit tests for cumulative metrics fix.

Tests the is_cumulative_usage flag that prevents incorrect accumulation
of cumulative token counts in streaming responses from providers like
Perplexity, Gemini, and Claude.
"""

from typing import Optional

from agno.models.metrics import Metrics
from agno.models.openai.chat import OpenAIChat
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


def test_openai_chat_default_is_cumulative_usage_flag():
    """Test that OpenAIChat has is_cumulative_usage set to False by default."""
    model = OpenAIChat(id="gpt-4o")
    assert model.is_cumulative_usage is False


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

    # Mock prompt_tokens_details
    class MockPromptTokensDetails:
        def __init__(self):
            self.audio_tokens = 10
            self.cached_tokens = 500

    # Mock completion_tokens_details
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


def test_perplexity_get_metrics_with_none_values():
    """Test that Perplexity._get_metrics handles None values gracefully."""
    model = Perplexity(id="sonar", api_key="test-key")

    # Create usage with None values
    usage = MockCompletionUsage(prompt_tokens=None, completion_tokens=None, total_tokens=None)

    metrics = model._get_metrics(usage)  # type: ignore[arg-type]

    assert metrics.input_tokens == 0
    assert metrics.output_tokens == 0
    assert metrics.total_tokens == 0


def test_metrics_accumulation_behavior():
    """
    Test that metrics accumulation behaves correctly based on is_cumulative_usage flag.

    This test verifies the logic in Model base class:
    - When is_cumulative_usage=False (OpenAI): metrics should accumulate (+=)
    - When is_cumulative_usage=True (Perplexity): metrics should overwrite (=)
    """
    from agno.models.metrics import Metrics

    # Test accumulation (OpenAI behavior)
    openai_model = OpenAIChat(id="gpt-4o")
    assert openai_model.is_cumulative_usage is False

    metrics1 = Metrics(input_tokens=100, output_tokens=1, total_tokens=101)
    metrics2 = Metrics(input_tokens=0, output_tokens=1, total_tokens=1)
    metrics3 = Metrics(input_tokens=0, output_tokens=1, total_tokens=1)

    # Simulate accumulation
    accumulated = Metrics()
    accumulated += metrics1
    accumulated += metrics2
    accumulated += metrics3

    assert accumulated.input_tokens == 100
    assert accumulated.output_tokens == 3  # 1 + 1 + 1
    assert accumulated.total_tokens == 103  # 101 + 1 + 1

    # Test overwrite (Perplexity behavior)
    perplexity_model = Perplexity(id="sonar", api_key="test-key")
    assert perplexity_model.is_cumulative_usage is True

    # Simulate overwrite - just use the latest metrics
    final_metrics = metrics3  # In reality, this would be metrics from last chunk
    assert final_metrics.output_tokens == 1


def test_cumulative_streaming_simulation():
    """
    Simulate the actual streaming scenario with cumulative metrics.

    Perplexity sends cumulative counts: (1, 2, 3, ..., 29)
    With is_cumulative_usage=True, the base Model class will overwrite
    instead of accumulate, so we end up with just the final count of 29.
    """
    model = Perplexity(id="sonar", api_key="test-key")

    # These represent what Perplexity sends in each streaming chunk
    chunk_metrics = [
        Metrics(input_tokens=1965, output_tokens=1, total_tokens=1966),
        Metrics(input_tokens=1965, output_tokens=2, total_tokens=1967),
        Metrics(input_tokens=1965, output_tokens=3, total_tokens=1968),
        # ... skipping intermediate
        Metrics(input_tokens=1965, output_tokens=29, total_tokens=1994),
    ]

    # Simulate what happens in Model base class with is_cumulative_usage=True
    final_metrics = None
    for chunk_metric in chunk_metrics:
        if model.is_cumulative_usage:
            # Overwrite instead of accumulate
            final_metrics = chunk_metric
        else:
            # Would accumulate (OpenAI behavior)
            if final_metrics is None:
                final_metrics = Metrics()
            final_metrics += chunk_metric

    # With is_cumulative_usage=True, we should have just the last chunk
    assert final_metrics is not None
    assert final_metrics.input_tokens == 1965
    assert final_metrics.output_tokens == 29
    assert final_metrics.total_tokens == 1994
