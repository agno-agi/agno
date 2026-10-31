from typing import Optional

from agno.metrics import MessageMetrics
from agno.models.cerebras.cerebras import Cerebras


class MockCerebrasUsage:
    """Mock ChatCompletionResponseUsage for Cerebras testing."""

    def __init__(
        self,
        prompt_tokens: Optional[int] = 0,
        completion_tokens: Optional[int] = 0,
        total_tokens: Optional[int] = 0,
        prompt_tokens_details=None,
        completion_tokens_details=None,
        time_system: Optional[float] = None,
        time_prompt: Optional[float] = None,
    ):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = total_tokens
        self.prompt_tokens_details = prompt_tokens_details
        self.completion_tokens_details = completion_tokens_details
        self.time_system = time_system
        self.time_prompt = time_prompt


class MockPromptTokensDetails:
    def __init__(self, cached_tokens: int = 0):
        self.cached_tokens = cached_tokens


class MockCompletionTokensDetails:
    def __init__(self, reasoning_tokens: int = 0):
        self.reasoning_tokens = reasoning_tokens


def test_cerebras_get_metrics_basic():
    model = Cerebras(id="llama3.1-70b", api_key="test-key")
    usage = MockCerebrasUsage(
        prompt_tokens=150,
        completion_tokens=50,
        total_tokens=200,
        time_system=0.01,
        time_prompt=0.03,
    )

    metrics = model._get_metrics(usage)  # type: ignore[arg-type]

    assert isinstance(metrics, MessageMetrics)
    assert metrics.input_tokens == 150
    assert metrics.output_tokens == 50
    assert metrics.total_tokens == 200
    assert metrics.cache_read_tokens == 0
    assert metrics.reasoning_tokens == 0
    assert metrics.provider_metrics is not None
    assert metrics.provider_metrics["time_system"] == 0.01
    assert metrics.provider_metrics["time_prompt"] == 0.03


def test_cerebras_get_metrics_with_token_details_objects():
    model = Cerebras(id="llama3.1-70b", api_key="test-key")
    usage = MockCerebrasUsage(
        prompt_tokens=800,
        completion_tokens=150,
        total_tokens=950,
        prompt_tokens_details=MockPromptTokensDetails(cached_tokens=400),
        completion_tokens_details=MockCompletionTokensDetails(reasoning_tokens=50),
    )

    metrics = model._get_metrics(usage)  # type: ignore[arg-type]

    assert metrics.input_tokens == 800
    assert metrics.output_tokens == 150
    assert metrics.total_tokens == 950
    assert metrics.cache_read_tokens == 400
    assert metrics.reasoning_tokens == 50


def test_cerebras_get_metrics_with_token_details_dicts():
    model = Cerebras(id="llama3.1-70b", api_key="test-key")
    usage = MockCerebrasUsage(
        prompt_tokens=600,
        completion_tokens=120,
        total_tokens=720,
        prompt_tokens_details={"cached_tokens": 300},
        completion_tokens_details={"reasoning_tokens": 40},
    )

    metrics = model._get_metrics(usage)  # type: ignore[arg-type]

    assert metrics.input_tokens == 600
    assert metrics.output_tokens == 120
    assert metrics.total_tokens == 720
    assert metrics.cache_read_tokens == 300
    assert metrics.reasoning_tokens == 40
