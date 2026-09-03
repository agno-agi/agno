"""Sampling parameters Anthropic rejects with a 400 are dropped before the request is sent.

``temperature`` and ``top_p`` are never accepted together. With thinking on, ``temperature``
may only be 1, ``top_p`` must be at least 0.95 and ``top_k`` must be unset. Claude Opus 4.7,
Sonnet 5 and later models apply that on every request and reject any ``top_p``. The filter
runs on the ``extra_body`` the sampling parameters travel in.
"""

from unittest.mock import MagicMock

import pytest

from agno.utils.models.claude import drop_unsupported_sampling_params, supports_sampling_params

ENABLED = {"type": "enabled", "budget_tokens": 1024}
ADAPTIVE = {"type": "adaptive"}
DISABLED = {"type": "disabled"}


def _request(sampling, thinking=None):
    params = {"max_tokens": 2048, "extra_body": dict(sampling)}
    if thinking is not None:
        params["thinking"] = thinking
    return params


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


def test_without_thinking_single_values_are_kept():
    params = _request({"temperature": 0.0, "top_k": 3})

    result = drop_unsupported_sampling_params(params, "claude-haiku-4-5-20251001")

    assert result is params
    assert params["extra_body"] == {"temperature": 0.0, "top_k": 3}


def test_no_sampling_params_is_a_no_op():
    params = {"max_tokens": 2048, "thinking": ENABLED}

    drop_unsupported_sampling_params(params, "claude-haiku-4-5-20251001")

    assert params == {"max_tokens": 2048, "thinking": ENABLED}


def test_thinking_disabled_counts_as_off():
    params = _request({"temperature": 0.0, "top_k": 3}, thinking=DISABLED)

    drop_unsupported_sampling_params(params, "claude-haiku-4-5-20251001")

    assert params["extra_body"] == {"temperature": 0.0, "top_k": 3}


@pytest.mark.parametrize("thinking", [ENABLED, ADAPTIVE])
def test_thinking_drops_temperature_top_k_and_low_top_p(thinking):
    params = _request({"temperature": 0.0, "top_p": 0.9, "top_k": 3}, thinking=thinking)

    drop_unsupported_sampling_params(params, "claude-sonnet-4-6")

    assert params == {"max_tokens": 2048, "thinking": thinking}


@pytest.mark.parametrize("sampling", [{"temperature": 1.0}, {"top_p": 0.95}])
def test_thinking_keeps_an_allowed_value_on_its_own(sampling):
    params = _request(sampling, thinking=ENABLED)

    drop_unsupported_sampling_params(params, "claude-haiku-4-5-20251001")

    assert params["extra_body"] == sampling


def test_temperature_and_top_p_are_never_sent_together():
    without_thinking = _request({"temperature": 0.5, "top_p": 0.9})
    drop_unsupported_sampling_params(without_thinking, "claude-haiku-4-5-20251001")
    assert without_thinking["extra_body"] == {"temperature": 0.5}

    # With thinking on, temperature can only be the default, so top_p is the one kept.
    with_thinking = _request({"temperature": 1.0, "top_p": 0.95}, thinking=ENABLED)
    drop_unsupported_sampling_params(with_thinking, "claude-haiku-4-5-20251001")
    assert with_thinking["extra_body"] == {"top_p": 0.95}


def test_model_without_sampling_support_drops_everything_but_temperature_one():
    params = _request({"temperature": 0.0, "top_p": 1.0, "top_k": 1})
    drop_unsupported_sampling_params(params, "claude-sonnet-5")
    assert "extra_body" not in params

    kept = _request({"temperature": 1}, thinking=DISABLED)
    drop_unsupported_sampling_params(kept, "claude-sonnet-5")
    assert kept["extra_body"] == {"temperature": 1}


def test_other_extra_body_keys_survive():
    params = _request({"temperature": 0.0, "service_tier": "auto"}, thinking=ENABLED)

    drop_unsupported_sampling_params(params, "claude-sonnet-4-6")

    assert params["extra_body"] == {"service_tier": "auto"}


def test_dropped_values_are_reported_with_their_reason(monkeypatch):
    warn = MagicMock()
    monkeypatch.setattr("agno.utils.models.claude.log_warning", warn)

    drop_unsupported_sampling_params(_request({"temperature": 0.0, "top_k": 3}, thinking=ENABLED), "claude-sonnet-4-6")
    drop_unsupported_sampling_params(_request({"temperature": 1.0}, thinking=ENABLED), "claude-sonnet-4-6")

    warn.assert_called_once()
    message = warn.call_args.args[0]
    assert "temperature=0.0 (must be 1 with thinking on)" in message
    assert "top_k=3 (must be unset with thinking on)" in message
