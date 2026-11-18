from unittest.mock import patch

import pytest
from openai.types.responses import ResponseUsage

from agno.exceptions import ModelAuthenticationError
from agno.models.message import Message
from agno.models.openrouter import OpenRouterResponses


def test_openrouter_responses_default_config():
    """Test OpenRouterResponses default configuration."""
    with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
        model = OpenRouterResponses()

        assert model.id == "openai/gpt-oss-20b"
        assert model.name == "OpenRouterResponses"
        assert model.provider == "OpenRouter"
        assert model.base_url == "https://openrouter.ai/api/v1"
        assert model.store is False  # Stateless by default


def test_openrouter_responses_requires_api_key():
    """Test OpenRouterResponses raises error when no API key is provided."""
    model = OpenRouterResponses()

    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(ModelAuthenticationError, match="OPENROUTER_API_KEY not set"):
            model._get_client_params()


def test_openrouter_responses_api_key_from_env():
    """Test OpenRouterResponses uses API key from environment."""
    model = OpenRouterResponses()

    with patch.dict("os.environ", {"OPENROUTER_API_KEY": "env-api-key"}):
        params = model._get_client_params()
        assert params["api_key"] == "env-api-key"


def test_openrouter_responses_api_key_explicit():
    """Test OpenRouterResponses uses explicit API key over environment."""
    model = OpenRouterResponses(api_key="explicit-key")

    with patch.dict("os.environ", {"OPENROUTER_API_KEY": "env-key"}):
        params = model._get_client_params()
        assert params["api_key"] == "explicit-key"


def test_openrouter_responses_fallback_models():
    """Test OpenRouterResponses with fallback models configuration."""
    model = OpenRouterResponses(
        api_key="test-key",
        models=["anthropic/claude-sonnet-4", "google/gemini-2.0-flash"],
    )

    request_params = model.get_request_params()

    assert "extra_body" in request_params
    assert request_params["extra_body"]["models"] == [
        "anthropic/claude-sonnet-4",
        "google/gemini-2.0-flash",
    ]


@pytest.mark.parametrize(
    "model_id,expected",
    [
        ("anthropic/claude-sonnet-4", False),
        ("openai/gpt-4.1", False),
        ("openai/gpt-oss-20b", False),
        ("other/gpt-6-sol", False),
        ("openai/o3-mini", True),
        ("openai/o4-mini", True),
        ("openai/gpt-5.6-luna", True),
        ("openai/gpt-6-sol", True),
        ("openai/gpt-6.1-sol", True),
    ],
)
def test_openrouter_responses_reasoning_model_detection(model_id, expected):
    """Test OpenRouterResponses reasoning model detection."""
    model = OpenRouterResponses(id=model_id, api_key="test-key")
    assert model._using_reasoning_model() is expected


@pytest.mark.parametrize("model_id", ["openai/gpt-5.6-luna", "openai/gpt-6-sol", "openai/gpt-6.1-sol"])
def test_openrouter_gpt_tool_follow_up_requests_reasoning_without_chaining(model_id):
    """Stateless tool follow-ups request encrypted reasoning and replay it with the call."""
    model = OpenRouterResponses(id=model_id, api_key="test-key", include=["message.output_text.logprobs"])
    messages = [
        Message(role="user", content="Look it up"),
        Message(
            role="assistant",
            provider_data={
                "response_id": "resp_previous",
                "reasoning_output": {
                    "id": "rs_previous",
                    "type": "reasoning",
                    "summary": [],
                    "encrypted_content": "encrypted-reasoning",
                },
            },
            tool_calls=[
                {
                    "id": "fc_previous",
                    "call_id": "call_previous",
                    "type": "function",
                    "function": {"name": "lookup", "arguments": "{}"},
                }
            ],
        ),
        Message(role="tool", tool_call_id="call_previous", content="Found it"),
    ]

    params = model.get_request_params(messages=messages)
    assert params["store"] is False
    assert "previous_response_id" not in params
    assert "reasoning" not in params
    assert params["include"] == ["message.output_text.logprobs", "reasoning.encrypted_content"]
    assert model.include == ["message.output_text.logprobs"]

    formatted = model._format_messages(messages)
    assert formatted[0] == {"role": "user", "content": "Look it up"}
    assert formatted[1].model_dump(exclude_none=True) == messages[1].provider_data["reasoning_output"]
    assert formatted[2]["type"] == "function_call"
    assert formatted[2]["id"] == "fc_previous"
    assert formatted[2]["call_id"] == "call_previous"
    assert formatted[3] == {"type": "function_call_output", "call_id": "call_previous", "output": "Found it"}


def test_openrouter_responses_client_params():
    """Test OpenRouterResponses client parameters."""
    model = OpenRouterResponses(
        id="anthropic/claude-sonnet-4",
        api_key="test-key",
        timeout=30.0,
        max_retries=3,
    )

    params = model._get_client_params()

    assert params["api_key"] == "test-key"
    assert params["base_url"] == "https://openrouter.ai/api/v1"
    assert params["timeout"] == 30.0
    assert params["max_retries"] == 3


class MockResponseUsage:
    """Mock ResponseUsage object for testing cost parsing."""

    def __init__(self, cost=None):
        self.input_tokens = 12
        self.output_tokens = 3
        self.total_tokens = 15
        self.input_tokens_details = None
        self.output_tokens_details = None
        self.cost = cost


class MockResponseUsageWithoutCost:
    """Mock ResponseUsage object that has no cost attribute."""

    def __init__(self):
        self.input_tokens = 12
        self.output_tokens = 3
        self.total_tokens = 15
        self.input_tokens_details = None
        self.output_tokens_details = None


def test_openrouter_responses_get_metrics_parses_cost():
    """Test OpenRouterResponses parses cost from ResponseUsage into MessageMetrics."""
    model = OpenRouterResponses(id="openai/gpt-4o-mini", api_key="test-key")

    metrics = model._get_metrics(MockResponseUsage(cost=3.6e-06))  # type: ignore[arg-type]

    assert metrics.cost == 3.6e-06
    assert metrics.input_tokens == 12
    assert metrics.output_tokens == 3
    assert metrics.total_tokens == 15


def test_openrouter_responses_get_metrics_parses_cost_from_real_sdk_usage():
    """Test cost is preserved through OpenAI SDK ResponseUsage into MessageMetrics."""
    model = OpenRouterResponses(id="openai/gpt-4o-mini", api_key="test-key")

    usage = ResponseUsage.model_validate(
        {
            "input_tokens": 12,
            "input_tokens_details": {
                "cached_tokens": 0,
                "cache_write_tokens": 0,
            },
            "output_tokens": 3,
            "output_tokens_details": {"reasoning_tokens": 0},
            "total_tokens": 15,
            "cost": 3.6e-06,
        }
    )

    assert getattr(usage, "cost", None) == 3.6e-06

    metrics = model._get_metrics(usage)

    assert metrics.cost == 3.6e-06
    assert metrics.input_tokens == 12
    assert metrics.output_tokens == 3
    assert metrics.total_tokens == 15


def test_openrouter_responses_get_metrics_cost_defaults_to_none_when_unavailable():
    """Test OpenRouterResponses leaves cost as None when usage has no cost attribute."""
    model = OpenRouterResponses(id="openai/gpt-4o-mini", api_key="test-key")

    metrics = model._get_metrics(MockResponseUsageWithoutCost())  # type: ignore[arg-type]

    assert metrics.cost is None
    assert metrics.input_tokens == 12
    assert metrics.output_tokens == 3
    assert metrics.total_tokens == 15


def test_openrouter_responses_get_metrics_zero_cost():
    """Test OpenRouterResponses preserves a zero cost from ResponseUsage."""
    model = OpenRouterResponses(id="openai/gpt-4o-mini", api_key="test-key")

    metrics = model._get_metrics(MockResponseUsage(cost=0.0))  # type: ignore[arg-type]

    assert metrics.cost == 0.0
