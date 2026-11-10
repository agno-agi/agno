"""Unit tests for Cohere request params: zero-valued sampling params
must not be silently dropped by a truthiness check."""

import pytest

pytest.importorskip("cohere")

from agno.models.cohere.chat import Cohere


def test_temperature_zero_included():
    """temperature=0.0 must appear in request params (falsy-check regression)."""
    params = Cohere(temperature=0.0).get_request_params()
    assert "temperature" in params
    assert params["temperature"] == 0.0


def test_top_p_zero_excluded():
    """top_p=0.0 is below Cohere's min of 0.01, so it must stay omitted."""
    params = Cohere(top_p=0.0).get_request_params()
    assert "p" not in params


def test_top_p_in_range_included():
    """A valid top_p is forwarded under Cohere's 'p' key."""
    params = Cohere(top_p=0.01).get_request_params()
    assert params["p"] == 0.01


def test_top_k_zero_included():
    """top_k=0 must appear in request params under Cohere's 'k' key."""
    params = Cohere(top_k=0).get_request_params()
    assert "k" in params
    assert params["k"] == 0


def test_seed_zero_included():
    """seed=0 is a valid deterministic seed and must appear in request params."""
    params = Cohere(seed=0).get_request_params()
    assert "seed" in params
    assert params["seed"] == 0


def test_frequency_penalty_zero_included():
    """frequency_penalty=0.0 must appear in request params."""
    params = Cohere(frequency_penalty=0.0).get_request_params()
    assert "frequency_penalty" in params
    assert params["frequency_penalty"] == 0.0


def test_presence_penalty_zero_included():
    """presence_penalty=0.0 must appear in request params."""
    params = Cohere(presence_penalty=0.0).get_request_params()
    assert "presence_penalty" in params
    assert params["presence_penalty"] == 0.0


def test_unset_sampling_params_excluded():
    """Unset (None) sampling params must not appear in request params."""
    params = Cohere().get_request_params()
    for key in ("temperature", "p", "k", "seed", "frequency_penalty", "presence_penalty"):
        assert key not in params


def test_positive_temperature_included():
    """Positive temperature is still forwarded correctly."""
    params = Cohere(temperature=0.7).get_request_params()
    assert params["temperature"] == 0.7


def test_all_zero_valued_params_survive_together():
    """Every in-range zero-valued param must survive together (top_p excluded: 0.0 is out of range)."""
    params = Cohere(
        temperature=0.0,
        top_k=0,
        seed=0,
        frequency_penalty=0.0,
        presence_penalty=0.0,
    ).get_request_params()
    assert params["temperature"] == 0.0
    assert params["k"] == 0
    assert params["seed"] == 0
    assert params["frequency_penalty"] == 0.0
    assert params["presence_penalty"] == 0.0
