"""Tests for OpenRouterResponses reasoning parameter handling.

Verifies that OpenRouterResponses only sends a `reasoning` block when the caller
explicitly configures reasoning params, unlike the parent OpenResponses which
unconditionally sends `reasoning: {}`.
"""

from agno.models.openai.open_responses import OpenResponses
from agno.models.openrouter import OpenRouterResponses


def test_no_reasoning_when_none_configured():
    """OpenRouterResponses must NOT send reasoning when no reasoning params are set."""
    model = OpenRouterResponses(api_key="test-key")
    base_params: dict = {}
    result = model._set_reasoning_request_param(base_params)
    assert "reasoning" not in result


def test_reasoning_sent_when_effort_set():
    """OpenRouterResponses sends reasoning with effort when reasoning_effort is set."""
    model = OpenRouterResponses(api_key="test-key", reasoning_effort="high")
    base_params: dict = {}
    result = model._set_reasoning_request_param(base_params)
    assert "reasoning" in result
    assert result["reasoning"]["effort"] == "high"


def test_reasoning_sent_when_summary_set():
    """OpenRouterResponses sends reasoning with summary when reasoning_summary is set."""
    model = OpenRouterResponses(api_key="test-key", reasoning_summary="auto")
    base_params: dict = {}
    result = model._set_reasoning_request_param(base_params)
    assert "reasoning" in result
    assert result["reasoning"]["summary"] == "auto"


def test_reasoning_sent_when_reasoning_dict_set():
    """OpenRouterResponses passes through an explicit reasoning dict."""
    model = OpenRouterResponses(api_key="test-key", reasoning={"effort": "low"})
    base_params: dict = {}
    result = model._set_reasoning_request_param(base_params)
    assert "reasoning" in result
    assert result["reasoning"]["effort"] == "low"


def test_parent_always_sends_reasoning():
    """Parent class (OpenResponses) always sends reasoning, even when empty.

    This documents the upstream behavior that OpenRouterResponses overrides.
    The parent unconditionally sets ``reasoning: {}`` which causes failures
    on OpenRouter-hosted models that reject empty reasoning objects.
    """
    model = OpenResponses()
    base_params: dict = {}
    result = model._set_reasoning_request_param(base_params)
    assert "reasoning" in result
    assert result["reasoning"] == {}
