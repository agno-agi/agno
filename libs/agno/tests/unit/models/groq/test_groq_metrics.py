from typing import Optional

from agno.metrics import MessageMetrics
from agno.models.groq.groq import Groq


class MockGroqUsage:
    """Mock CompletionUsage for Groq testing."""

    def __init__(
        self,
        prompt_tokens: Optional[int] = 0,
        completion_tokens: Optional[int] = 0,
        total_tokens: Optional[int] = 0,
        prompt_tokens_details=None,
        completion_tokens_details=None,
        completion_time: Optional[float] = None,
        prompt_time: Optional[float] = None,
        queue_time: Optional[float] = None,
        total_time: Optional[float] = None,
    ):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = total_tokens
        self.prompt_tokens_details = prompt_tokens_details
        self.completion_tokens_details = completion_tokens_details
        self.completion_time = completion_time
        self.prompt_time = prompt_time
        self.queue_time = queue_time
        self.total_time = total_time


class MockPromptTokensDetails:
    def __init__(self, cached_tokens: int = 0):
        self.cached_tokens = cached_tokens


class MockCompletionTokensDetails:
    def __init__(self, reasoning_tokens: int = 0):
        self.reasoning_tokens = reasoning_tokens


def test_groq_get_metrics_basic():
    model = Groq(id="llama-3.3-70b-versatile", api_key="test-key")
    usage = MockGroqUsage(
        prompt_tokens=100,
        completion_tokens=25,
        total_tokens=125,
        prompt_time=0.05,
        completion_time=0.15,
    )

    metrics = model._get_metrics(usage)  # type: ignore[arg-type]

    assert isinstance(metrics, MessageMetrics)
    assert metrics.input_tokens == 100
    assert metrics.output_tokens == 25
    assert metrics.total_tokens == 125
    assert metrics.cache_read_tokens == 0
    assert metrics.reasoning_tokens == 0
    assert metrics.provider_metrics is not None
    assert metrics.provider_metrics["prompt_time"] == 0.05
    assert metrics.provider_metrics["completion_time"] == 0.15


def test_groq_get_metrics_with_token_details_objects():
    model = Groq(id="llama-3.3-70b-versatile", api_key="test-key")
    usage = MockGroqUsage(
        prompt_tokens=1000,
        completion_tokens=200,
        total_tokens=1200,
        prompt_tokens_details=MockPromptTokensDetails(cached_tokens=512),
        completion_tokens_details=MockCompletionTokensDetails(reasoning_tokens=128),
    )

    metrics = model._get_metrics(usage)  # type: ignore[arg-type]

    assert metrics.input_tokens == 1000
    assert metrics.output_tokens == 200
    assert metrics.total_tokens == 1200
    assert metrics.cache_read_tokens == 512
    assert metrics.reasoning_tokens == 128


def test_groq_get_metrics_with_token_details_dicts():
    model = Groq(id="llama-3.3-70b-versatile", api_key="test-key")
    usage = MockGroqUsage(
        prompt_tokens=500,
        completion_tokens=100,
        total_tokens=600,
        prompt_tokens_details={"cached_tokens": 256},
        completion_tokens_details={"reasoning_tokens": 64},
    )

    metrics = model._get_metrics(usage)  # type: ignore[arg-type]

    assert metrics.input_tokens == 500
    assert metrics.output_tokens == 100
    assert metrics.total_tokens == 600
    assert metrics.cache_read_tokens == 256
    assert metrics.reasoning_tokens == 64
