"""
Unit tests for OpenAI metrics collection.

Tests that the collect_metrics_on_completion flag works correctly for OpenAI models.
"""

from typing import Optional

import pytest
from openai.types.completion_usage import CompletionUsage
from openai.types.responses import ResponseUsage

from agno.models.openai.chat import OpenAIChat
from agno.models.openai.responses import OpenAIResponses


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


def test_openai_get_metrics_computes_audio_total_tokens():
    """Audio totals should be derived from input and output audio token counts."""
    model = OpenAIChat(id="gpt-4o")

    class MockPromptTokensDetails:
        def __init__(self):
            self.audio_tokens = 11
            self.cached_tokens = 7

    class MockCompletionTokensDetails:
        def __init__(self):
            self.audio_tokens = 13
            self.reasoning_tokens = 5

    usage = MockCompletionUsage(
        prompt_tokens=100,
        completion_tokens=20,
        total_tokens=120,
        prompt_tokens_details=MockPromptTokensDetails(),
        completion_tokens_details=MockCompletionTokensDetails(),
    )

    metrics = model._get_metrics(usage)  # type: ignore[arg-type]

    assert metrics.audio_input_tokens == 11
    assert metrics.audio_output_tokens == 13
    assert metrics.audio_total_tokens == 24


@pytest.mark.parametrize(
    "model_class,usage_class,input_field,output_field",
    [
        (OpenAIChat, CompletionUsage, "prompt_tokens", "completion_tokens"),
        (OpenAIResponses, ResponseUsage, "input_tokens", "output_tokens"),
    ],
)
@pytest.mark.parametrize(
    "cache_details,expected_writes",
    [({"cache_write_tokens": 3000}, 3000), ({"cache_write_tokens": 0}, 0), ({"cache_write_tokens": None}, 0), ({}, 0)],
    ids=["writes", "zero", "null", "omitted"],
)
def test_openai_get_metrics_preserves_cache_writes(
    model_class, usage_class, input_field, output_field, cache_details, expected_writes
):
    """Preserve cache-write usage without requiring the field in older payloads."""
    # Match the SDK's non-strict response parsing for older provider payloads.
    usage = usage_class.construct(
        **{
            input_field: 15000,
            output_field: 50,
            "total_tokens": 15050,
            f"{input_field}_details": {"cached_tokens": 12000, **cache_details},
            f"{output_field}_details": {"reasoning_tokens": 7},
        }
    )

    metrics = model_class()._get_metrics(usage)

    assert metrics.cache_write_tokens == expected_writes
    assert metrics.cache_read_tokens == 12000
    assert metrics.input_tokens == 15000
    assert metrics.output_tokens == 50
    assert metrics.total_tokens == 15050
    assert metrics.reasoning_tokens == 7
