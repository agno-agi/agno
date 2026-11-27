"""Sampling values Anthropic rejects with a 400 are dropped before the request is sent.

``temperature`` and ``top_p`` are never accepted together. With thinking on, ``temperature``
may only be 1, ``top_p`` must be at least 0.95 and ``top_k`` must be unset. The filter runs
on the ``extra_body`` the sampling parameters travel in.
"""

from unittest.mock import MagicMock

import pytest

from agno.utils.models.claude import route_sampling_params_to_extra_body

ENABLED = {"type": "enabled", "budget_tokens": 1024}
ADAPTIVE = {"type": "adaptive"}
DISABLED = {"type": "disabled"}


def _request(sampling, thinking=None):
    params = {"max_tokens": 2048, "extra_body": dict(sampling)}
    if thinking is not None:
        params["thinking"] = thinking
    return params


def test_without_thinking_single_values_are_kept():
    params = _request({"temperature": 0.0, "top_k": 3})

    result = route_sampling_params_to_extra_body(params, "claude-haiku-4-5-20251001")

    assert result is params
    assert params["extra_body"] == {"temperature": 0.0, "top_k": 3}


def test_no_sampling_params_is_a_no_op():
    params = {"max_tokens": 2048, "thinking": ENABLED}

    route_sampling_params_to_extra_body(params, "claude-haiku-4-5-20251001")

    assert params == {"max_tokens": 2048, "thinking": ENABLED}


def test_thinking_disabled_counts_as_off():
    params = _request({"temperature": 0.0, "top_k": 3}, thinking=DISABLED)

    route_sampling_params_to_extra_body(params, "claude-haiku-4-5-20251001")

    assert params["extra_body"] == {"temperature": 0.0, "top_k": 3}


@pytest.mark.parametrize("thinking", [ENABLED, ADAPTIVE])
def test_thinking_drops_temperature_top_k_and_low_top_p(thinking):
    params = _request({"temperature": 0.0, "top_p": 0.9, "top_k": 3}, thinking=thinking)

    route_sampling_params_to_extra_body(params, "claude-sonnet-4-6")

    assert params == {"max_tokens": 2048, "thinking": thinking}


@pytest.mark.parametrize("sampling", [{"temperature": 1.0}, {"top_p": 0.95}])
def test_thinking_keeps_an_allowed_value_on_its_own(sampling):
    params = _request(sampling, thinking=ENABLED)

    route_sampling_params_to_extra_body(params, "claude-haiku-4-5-20251001")

    assert params["extra_body"] == sampling


def test_temperature_and_top_p_are_never_sent_together():
    without_thinking = _request({"temperature": 0.5, "top_p": 0.9})
    route_sampling_params_to_extra_body(without_thinking, "claude-haiku-4-5-20251001")
    assert without_thinking["extra_body"] == {"temperature": 0.5}

    # With thinking on, temperature can only be the default, so top_p is the one kept.
    with_thinking = _request({"temperature": 1.0, "top_p": 0.95}, thinking=ENABLED)
    route_sampling_params_to_extra_body(with_thinking, "claude-haiku-4-5-20251001")
    assert with_thinking["extra_body"] == {"top_p": 0.95}


def test_thinking_inside_extra_body_is_honoured():
    params = _request({"thinking": ENABLED, "temperature": 0.0})

    route_sampling_params_to_extra_body(params, "claude-haiku-4-5-20251001")

    assert params["extra_body"] == {"thinking": ENABLED}


def test_thinking_inside_extra_body_outranks_the_field():
    # The SDK merges extra_body over the request, so a disabled there is what the API sees.
    params = _request({"thinking": DISABLED, "temperature": 0.0}, thinking=ENABLED)

    route_sampling_params_to_extra_body(params, "claude-haiku-4-5-20251001")

    assert params["extra_body"] == {"thinking": DISABLED, "temperature": 0.0}


def test_other_extra_body_keys_survive():
    params = _request({"temperature": 0.0, "service_tier": "auto"}, thinking=ENABLED)

    route_sampling_params_to_extra_body(params, "claude-sonnet-4-6")

    assert params["extra_body"] == {"service_tier": "auto"}


def test_dropped_values_are_reported_with_their_reason(monkeypatch):
    warn = MagicMock()
    monkeypatch.setattr("agno.utils.models.claude.log_warning", warn)

    route_sampling_params_to_extra_body(
        _request({"temperature": 0.0, "top_k": 3}, thinking=ENABLED), "claude-sonnet-4-6"
    )
    route_sampling_params_to_extra_body(_request({"temperature": 1.0}, thinking=ENABLED), "claude-sonnet-4-6")

    warn.assert_called_once()
    message = warn.call_args.args[0]
    assert "temperature=0.0 (must be 1 with thinking on)" in message
    assert "top_k=3 (must be unset with thinking on)" in message
