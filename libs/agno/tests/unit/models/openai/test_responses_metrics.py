"""Unit tests for OpenAIResponses/OpenRouterResponses usage parsing.

OpenRouter's Responses API includes a per-request `cost` in usage; the shared
`OpenAIResponses._get_metrics` (inherited by `OpenRouterResponses`) must surface it.
"""

from openai.types.responses import ResponseUsage

from agno.models.openai.open_responses import OpenResponses


def _usage(**overrides) -> ResponseUsage:
    fields = {
        "input_tokens": 10,
        "output_tokens": 5,
        "total_tokens": 15,
        "input_tokens_details": None,
        "output_tokens_details": None,
    }
    fields.update(overrides)
    return ResponseUsage.model_construct(**fields)


def test_responses_metrics_populates_cost_when_present():
    model = OpenResponses(id="openai/gpt-oss-20b")
    metrics = model._get_metrics(_usage(cost=0.00123))
    assert metrics.cost == 0.00123


def test_responses_metrics_cost_none_without_cost_field():
    """OpenAI itself does not return `cost`; metrics.cost must stay None (no-op)."""
    model = OpenResponses(id="openai/gpt-oss-20b")
    metrics = model._get_metrics(_usage())
    assert metrics.cost is None
