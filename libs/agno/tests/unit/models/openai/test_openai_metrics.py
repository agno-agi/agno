"""
Unit tests for OpenAI metrics collection.

Tests that the collect_metrics_on_completion flag works correctly for OpenAI models.
"""

from typing import Optional

import pytest
from openai.types.completion_usage import CompletionUsage
from openai.types.responses import ResponseUsage

from agno.metrics import MessageMetrics
from agno.models.base import MessageData
from agno.models.message import Message
from agno.models.openai.chat import OpenAIChat
from agno.models.openai.like import OpenAILike
from agno.models.openai.responses import OpenAIResponses
from agno.models.vllm.vllm import VLLM


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


class MockDelta:
    """Mock ChoiceDelta object for testing."""

    def __init__(self, content=None, role=None, tool_calls=None, audio=None):
        self.content = content
        self.role = role
        self.tool_calls = tool_calls
        self.audio = audio


class MockChoice:
    """Mock Choice object for testing."""

    def __init__(self, finish_reason=None, content=None, role=None):
        self.finish_reason = finish_reason
        self.delta = MockDelta(content=content, role=role)


class MockChatCompletionChunk:
    """Mock ChatCompletionChunk object for testing."""

    def __init__(self, usage=None, finish_reason=None, choices=None, content=None, role=None):
        self.id = "chatcmpl-test"
        self.system_fingerprint = None
        self.model_extra = None
        self.usage = usage
        if choices is not None:
            self.choices = choices
        else:
            self.choices = [MockChoice(finish_reason=finish_reason, content=content, role=role)]


def test_openai_chat_default_collect_metrics_flag():
    """Test that OpenAIChat has collect_metrics_on_completion set to False by default."""
    model = OpenAIChat(id="gpt-4o")
    assert model.collect_metrics_on_completion is False


def test_openai_like_default_collect_metrics_flag():
    """OpenAILike and VLLM default collect_metrics_on_completion to True."""
    like_model = OpenAILike(id="Qwen/Qwen2.5-0.5B-Instruct")
    vllm_model = VLLM(id="Qwen/Qwen2.5-0.5B-Instruct")
    assert like_model.collect_metrics_on_completion is True
    assert vllm_model.collect_metrics_on_completion is True


def test_should_collect_metrics_on_completion_accepts_empty_choices_usage_frame():
    """When collect_metrics_on_completion is True, accept both finish_reason chunks and empty-choices final usage chunks."""
    model = OpenAILike(id="Qwen/Qwen2.5-0.5B-Instruct")
    usage = MockCompletionUsage(prompt_tokens=38, completion_tokens=47, total_tokens=85)

    intermediate_chunk = MockChatCompletionChunk(usage=usage, finish_reason=None)
    assert model._should_collect_metrics(intermediate_chunk) is False  # type: ignore[arg-type]

    finish_chunk = MockChatCompletionChunk(usage=usage, finish_reason="stop")
    assert model._should_collect_metrics(finish_chunk) is True  # type: ignore[arg-type]

    empty_choices_usage_chunk = MockChatCompletionChunk(usage=usage, choices=[])
    assert model._should_collect_metrics(empty_choices_usage_chunk) is True  # type: ignore[arg-type]

    empty_choices_no_usage_chunk = MockChatCompletionChunk(usage=None, choices=[])
    assert model._should_collect_metrics(empty_choices_no_usage_chunk) is False  # type: ignore[arg-type]


def test_openai_like_vllm_cumulative_streaming_metrics_not_inflated():
    """Replay vLLM cumulative per-chunk usage plus empty-choices final usage frame without inflating metrics."""
    model = OpenAILike(id="Qwen/Qwen2.5-0.5B-Instruct")

    chunks = [
        MockChatCompletionChunk(
            usage=MockCompletionUsage(prompt_tokens=38, completion_tokens=4, total_tokens=42),
            finish_reason=None,
            content="ALPHA",
            role="assistant",
        ),
        MockChatCompletionChunk(
            usage=MockCompletionUsage(prompt_tokens=38, completion_tokens=24, total_tokens=62),
            finish_reason=None,
            content="7",
        ),
        MockChatCompletionChunk(
            usage=MockCompletionUsage(prompt_tokens=38, completion_tokens=47, total_tokens=85),
            finish_reason="stop",
            content="",
        ),
        MockChatCompletionChunk(
            usage=MockCompletionUsage(prompt_tokens=38, completion_tokens=47, total_tokens=85),
            choices=[],
        ),
    ]

    stream_data = MessageData()
    stream_data.response_metrics = MessageMetrics()
    stream_data.response_metrics.start_timer()
    assistant_message = Message(role="assistant")

    for chunk in chunks:
        delta = model._parse_provider_response_delta(chunk)  # type: ignore[arg-type]
        list(model._populate_stream_data(stream_data=stream_data, model_response_delta=delta))

    model._populate_assistant_message_from_stream_data(assistant_message=assistant_message, stream_data=stream_data)

    assert assistant_message.content == "ALPHA7"
    assert assistant_message.metrics is not None
    assert assistant_message.metrics.input_tokens == 38
    assert assistant_message.metrics.output_tokens == 47
    assert assistant_message.metrics.total_tokens == 85
    assert assistant_message.metrics.time_to_first_token is not None
    assert assistant_message.metrics.duration is not None


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
