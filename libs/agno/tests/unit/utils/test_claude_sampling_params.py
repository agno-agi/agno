"""Sampling parameters Anthropic rejects with a 400 are dropped before the request is built.

With thinking on, ``temperature`` may only be 1, ``top_p`` must be at least 0.95 and
``top_k`` must be unset. Claude Opus 4.7, Sonnet 5 and later models apply that on every
request and reject any ``top_p``. The API answers each of these with a 400, so the
model-side filter decides which values survive.
"""

from unittest.mock import MagicMock

import pytest

from agno.utils.models.claude import drop_unsupported_sampling_params, supports_sampling_params

ENABLED = {"type": "enabled", "budget_tokens": 1024}
ADAPTIVE = {"type": "adaptive"}
DISABLED = {"type": "disabled"}


@pytest.mark.parametrize(
    "model_id, expected",
    [
        ("claude-haiku-4-5-20251001", True),
        ("claude-sonnet-4-6", True),
        ("claude-opus-4-6", True),
        ("claude-3-7-sonnet-20250219", True),
        ("claude-sonnet-4", True),  # alias for 4-0
        ("us.anthropic.claude-sonnet-4-6-v1:0", True),  # Bedrock
        ("claude-sonnet-4-5@20250929", True),  # Vertex AI
        ("anthropic/claude-sonnet-4-6", True),  # LiteLLM
        ("gpt-4o", True),  # not a Claude model
        ("claude-opus-4-7", False),
        ("claude-sonnet-5", False),
        ("claude-opus-5", False),
        ("us.anthropic.claude-sonnet-5-v1:0", False),
        ("claude-sonnet-5@20260401", False),
    ],
)
def test_supports_sampling_params(model_id, expected):
    assert supports_sampling_params(model_id) is expected


def test_without_thinking_everything_is_kept():
    params = {"max_tokens": 100, "temperature": 0.0, "top_p": 0.5, "top_k": 3}

    result = drop_unsupported_sampling_params(params, "claude-haiku-4-5-20251001")

    assert result is params
    assert params == {"max_tokens": 100, "temperature": 0.0, "top_p": 0.5, "top_k": 3}


def test_thinking_disabled_counts_as_off():
    params = {"thinking": DISABLED, "temperature": 0.0, "top_k": 3}

    drop_unsupported_sampling_params(params, "claude-haiku-4-5-20251001")

    assert params == {"thinking": DISABLED, "temperature": 0.0, "top_k": 3}


@pytest.mark.parametrize("thinking", [ENABLED, ADAPTIVE])
def test_thinking_drops_temperature_top_k_and_low_top_p(thinking):
    params = {"thinking": thinking, "max_tokens": 2048, "temperature": 0.0, "top_p": 0.9, "top_k": 3}

    drop_unsupported_sampling_params(params, "claude-sonnet-4-6")

    assert params == {"thinking": thinking, "max_tokens": 2048}


def test_thinking_keeps_temperature_one_and_top_p_from_0_95():
    params = {"thinking": ENABLED, "temperature": 1.0, "top_p": 0.95}

    drop_unsupported_sampling_params(params, "claude-haiku-4-5-20251001")

    assert params == {"thinking": ENABLED, "temperature": 1.0, "top_p": 0.95}


def test_model_without_sampling_support_drops_everything_but_temperature_one():
    params = {"temperature": 0.0, "top_p": 1.0, "top_k": 1}

    drop_unsupported_sampling_params(params, "claude-sonnet-5")

    assert params == {}

    kept = {"temperature": 1, "thinking": DISABLED}
    drop_unsupported_sampling_params(kept, "claude-sonnet-5")
    assert kept == {"temperature": 1, "thinking": DISABLED}


def test_dropped_values_are_reported_once(monkeypatch):
    warn = MagicMock()
    monkeypatch.setattr("agno.utils.models.claude.log_warning", warn)

    drop_unsupported_sampling_params({"thinking": ENABLED, "temperature": 0.0, "top_k": 3}, "claude-sonnet-4-6")
    drop_unsupported_sampling_params({"thinking": ENABLED, "temperature": 1.0}, "claude-sonnet-4-6")

    warn.assert_called_once()
    message = warn.call_args.args[0]
    assert "temperature=0.0" in message and "top_k=3" in message
