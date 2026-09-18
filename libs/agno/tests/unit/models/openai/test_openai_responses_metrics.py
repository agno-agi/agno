"""
Unit tests for OpenAI Responses metrics collection.

Verifies that _get_metrics parses cost (and other usage fields) from the
ResponseUsage object into MessageMetrics.
"""

from typing import Optional

from agno.models.openai.responses import OpenAIResponses


class MockResponseUsage:
    """Mock ResponseUsage object for testing."""

    def __init__(
        self,
        input_tokens: Optional[int] = 0,
        output_tokens: Optional[int] = 0,
        total_tokens: Optional[int] = 0,
        input_tokens_details=None,
        output_tokens_details=None,
        cost: Optional[float] = None,
    ):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.total_tokens = total_tokens
        self.input_tokens_details = input_tokens_details
        self.output_tokens_details = output_tokens_details
        self.cost = cost


class MockResponseUsageWithoutCost:
    """Mock ResponseUsage object that has no cost attribute."""

    def __init__(self):
        self.input_tokens = 12
        self.output_tokens = 3
        self.total_tokens = 15
        self.input_tokens_details = None
        self.output_tokens_details = None


class MockInputTokensDetails:
    def __init__(self, cached_tokens: Optional[int] = None):
        self.cached_tokens = cached_tokens


class MockOutputTokensDetails:
    def __init__(self, reasoning_tokens: Optional[int] = None):
        self.reasoning_tokens = reasoning_tokens


def test_openai_responses_get_metrics_basic():
    """Test that OpenAIResponses._get_metrics converts ResponseUsage to MessageMetrics."""
    model = OpenAIResponses(id="gpt-4o-mini")
    usage = MockResponseUsage(input_tokens=12, output_tokens=3, total_tokens=15)

    metrics = model._get_metrics(usage)  # type: ignore[arg-type]

    assert metrics.input_tokens == 12
    assert metrics.output_tokens == 3
    assert metrics.total_tokens == 15


def test_openai_responses_get_metrics_parses_cost():
    """Test that OpenAIResponses._get_metrics parses cost from ResponseUsage."""
    model = OpenAIResponses(id="gpt-4o-mini")
    usage = MockResponseUsage(
        input_tokens=12,
        output_tokens=3,
        total_tokens=15,
        cost=3.6e-06,
    )

    metrics = model._get_metrics(usage)  # type: ignore[arg-type]

    assert metrics.cost == 3.6e-06


def test_openai_responses_get_metrics_cost_defaults_to_none_when_unavailable():
    """Test that OpenAIResponses._get_metrics leaves cost as None when usage has no cost attribute."""
    model = OpenAIResponses(id="gpt-4o-mini")
    usage = MockResponseUsageWithoutCost()

    metrics = model._get_metrics(usage)  # type: ignore[arg-type]

    assert metrics.cost is None
    assert metrics.input_tokens == 12
    assert metrics.output_tokens == 3
    assert metrics.total_tokens == 15


def test_openai_responses_get_metrics_zero_cost():
    """Test that OpenAIResponses preserves a zero cost from ResponseUsage."""
    model = OpenAIResponses(id="gpt-4o-mini")
    usage = MockResponseUsage(
        input_tokens=12,
        output_tokens=3,
        total_tokens=15,
        cost=0.0,
    )

    metrics = model._get_metrics(usage)  # type: ignore[arg-type]

    assert metrics.cost == 0.0


def test_openai_responses_get_metrics_with_details_and_cost():
    """Test that OpenAIResponses._get_metrics parses cost along with token details."""
    model = OpenAIResponses(id="gpt-4o-mini")
    usage = MockResponseUsage(
        input_tokens=100,
        output_tokens=50,
        total_tokens=150,
        input_tokens_details=MockInputTokensDetails(cached_tokens=20),
        output_tokens_details=MockOutputTokensDetails(reasoning_tokens=5),
        cost=0.0002,
    )

    metrics = model._get_metrics(usage)  # type: ignore[arg-type]

    assert metrics.input_tokens == 100
    assert metrics.output_tokens == 50
    assert metrics.total_tokens == 150
    assert metrics.cache_read_tokens == 20
    assert metrics.reasoning_tokens == 5
    assert metrics.cost == 0.0002
