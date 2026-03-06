"""
Unit tests for OpenAI metrics collection.

Tests that the collect_metrics_on_completion flag works correctly for OpenAI models.
"""

from typing import Optional

from agno.models.openai.chat import OpenAIChat


class MockCompletionUsage:
    """Mock CompletionUsage object for testing."""

    def __init__(
        self,
        prompt_tokens: Optional[int] = 0,
        completion_tokens: Optional[int] = 0,
        total_tokens: Optional[int] = 0,
    ):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = total_tokens
        self.prompt_tokens_details = None
        self.completion_tokens_details = None


class MockChoice:
    """Mock Choice object for testing."""

    def __init__(self, finish_reason=None):
        self.finish_reason = finish_reason


class MockChatCompletionChunk:
    """Mock ChatCompletionChunk object for testing."""

    def __init__(self, usage=None, finish_reason=None):
        self.usage = usage
        self.choices = [MockChoice(finish_reason=finish_reason)]


def test_openai_chat_default_collect_metrics_flag():
    """Test that OpenAIChat has collect_metrics_on_completion set to False by default."""
    model = OpenAIChat(id="gpt-4o")
    assert model.collect_metrics_on_completion is False


def test_should_collect_metrics_when_usage_is_none():
    """Test that _should_collect_metrics returns False when usage is None."""
    model = OpenAIChat(id="gpt-4o")
    response = MockChatCompletionChunk(usage=None)
    assert model._should_collect_metrics(response) is False  # type: ignore[arg-type]


def test_should_collect_metrics_default_behavior():
    """Test that _should_collect_metrics returns True when collect_metrics_on_completion is False."""
    model = OpenAIChat(id="gpt-4o")
    usage = MockCompletionUsage(prompt_tokens=100, completion_tokens=20, total_tokens=120)

    # Test with no finish_reason (intermediate chunk)
    response = MockChatCompletionChunk(usage=usage, finish_reason=None)
    assert model._should_collect_metrics(response) is True  # type: ignore[arg-type]

    # Test with finish_reason (last chunk)
    response = MockChatCompletionChunk(usage=usage, finish_reason="stop")
    assert model._should_collect_metrics(response) is True  # type: ignore[arg-type]


def test_openai_streaming_metrics_simulation():
    """
    Simulate the default OpenAI streaming scenario.

    OpenAI returns incremental token counts, and we should collect on every chunk.
    """
    model = OpenAIChat(id="gpt-4o")

    chunks = [
        MockChatCompletionChunk(
            usage=MockCompletionUsage(prompt_tokens=100, completion_tokens=1, total_tokens=101),
            finish_reason=None,
        ),
        MockChatCompletionChunk(
            usage=MockCompletionUsage(prompt_tokens=0, completion_tokens=1, total_tokens=1),
            finish_reason=None,
        ),
        MockChatCompletionChunk(
            usage=MockCompletionUsage(prompt_tokens=0, completion_tokens=1, total_tokens=1),
            finish_reason="stop",
        ),
    ]

    collected_metrics = []
    for chunk in chunks:
        if model._should_collect_metrics(chunk):  # type: ignore[arg-type]
            metrics = model._get_metrics(chunk.usage)  # type: ignore[arg-type]
            collected_metrics.append(metrics)

    # Should collect metrics from all chunks with usage
    assert len(collected_metrics) == 3
