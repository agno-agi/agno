"""
Unit tests for OpenAILike streaming metrics collection (agno #11538).

vLLM (and other OpenAI-compatible servers with continuous usage stats) sends
a cumulative usage snapshot on every streaming chunk, and its final usage
frame has empty choices. Without this fix the default path summed every
cumulative snapshot (~53x inflation), and with collect_metrics_on_completion
set the final frame was dropped entirely (0 metrics).
"""

from typing import Optional

from agno.metrics import MessageMetrics
from agno.models.openai.like import OpenAILike


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

    def __init__(self, usage=None, choices=None):
        self.usage = usage
        self.choices = choices if choices is not None else [MockChoice()]


def test_openai_like_collect_metrics_flag_defaults_true():
    """OpenAILike defaults to collecting metrics only on the completion chunk."""
    model = OpenAILike(id="Qwen/Qwen2.5-0.5B-Instruct", api_key="test-key")
    assert model.collect_metrics_on_completion is True


def test_should_collect_metrics_skips_intermediate_cumulative_chunks():
    """Intermediate chunks with cumulative usage are not collected."""
    model = OpenAILike(id="Qwen/Qwen2.5-0.5B-Instruct", api_key="test-key")
    usage = MockCompletionUsage(prompt_tokens=38, completion_tokens=24, total_tokens=62)

    response = MockChatCompletionChunk(usage=usage, choices=[MockChoice(finish_reason=None)])
    assert model._should_collect_metrics(response) is False  # type: ignore[arg-type]


def test_should_collect_metrics_accepts_empty_choices_usage_frame():
    """The final usage frame with empty choices (vLLM style) is collected."""
    model = OpenAILike(id="Qwen/Qwen2.5-0.5B-Instruct", api_key="test-key")
    usage = MockCompletionUsage(prompt_tokens=38, completion_tokens=47, total_tokens=85)

    response = MockChatCompletionChunk(usage=usage, choices=[])
    assert model._should_collect_metrics(response) is True  # type: ignore[arg-type]


def test_should_collect_metrics_accepts_finish_reason_chunk():
    """A chunk with a finish_reason is still collected as the final chunk."""
    model = OpenAILike(id="Qwen/Qwen2.5-0.5B-Instruct", api_key="test-key")
    usage = MockCompletionUsage(prompt_tokens=38, completion_tokens=47, total_tokens=85)

    response = MockChatCompletionChunk(usage=usage, choices=[MockChoice(finish_reason="stop")])
    assert model._should_collect_metrics(response) is True  # type: ignore[arg-type]


def test_should_collect_metrics_ignores_chunks_without_usage():
    """Chunks without usage are never collected."""
    model = OpenAILike(id="Qwen/Qwen2.5-0.5B-Instruct", api_key="test-key")

    response = MockChatCompletionChunk(usage=None, choices=[])
    assert model._should_collect_metrics(response) is False  # type: ignore[arg-type]


def test_openai_like_vllm_cumulative_streaming_simulation():
    """
    Replay a vLLM-style cumulative stream: every chunk carries running totals
    and the final usage frame has empty choices.

    Only the final frame must be collected, reporting the true totals.
    """
    model = OpenAILike(id="Qwen/Qwen2.5-0.5B-Instruct", api_key="test-key")

    chunks = [
        MockChatCompletionChunk(
            usage=MockCompletionUsage(prompt_tokens=38, completion_tokens=i, total_tokens=38 + i),
            choices=[MockChoice(finish_reason=None)],
        )
        for i in range(1, 59)
    ]
    chunks.append(
        MockChatCompletionChunk(
            usage=MockCompletionUsage(prompt_tokens=38, completion_tokens=47, total_tokens=85),
            choices=[],
        )
    )

    collected_metrics = []
    for chunk in chunks:
        if model._should_collect_metrics(chunk):  # type: ignore[arg-type]
            metrics = model._get_metrics(chunk.usage)  # type: ignore[arg-type]
            collected_metrics.append(metrics)

    assert len(collected_metrics) == 1
    assert isinstance(collected_metrics[0], MessageMetrics)
    assert collected_metrics[0].input_tokens == 38
    assert collected_metrics[0].output_tokens == 47
    assert collected_metrics[0].total_tokens == 85


def test_openai_like_opt_out_still_collects_every_chunk():
    """Opting out of collect_metrics_on_completion preserves the old behavior."""
    model = OpenAILike(id="Qwen/Qwen2.5-0.5B-Instruct", api_key="test-key", collect_metrics_on_completion=False)
    usage = MockCompletionUsage(prompt_tokens=38, completion_tokens=24, total_tokens=62)

    response = MockChatCompletionChunk(usage=usage, choices=[MockChoice(finish_reason=None)])
    assert model._should_collect_metrics(response) is True  # type: ignore[arg-type]

    response = MockChatCompletionChunk(usage=usage, choices=[])
    assert model._should_collect_metrics(response) is True  # type: ignore[arg-type]
