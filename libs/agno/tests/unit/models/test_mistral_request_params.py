"""Unit tests for Mistral request params: the sampling parameters supported by the
Mistral chat-completions API are forwarded via get_request_params, and zero values
are not silently dropped."""

import pytest

pytest.importorskip("mistralai")

from agno.models.mistral.mistral import MistralChat


def test_mistral_sampling_params_in_request_params():
    model = MistralChat(
        id="mistral-small-latest",
        frequency_penalty=0.5,
        presence_penalty=0.25,
        stop=["STOP"],
    )

    request_params = model.get_request_params()

    assert request_params["frequency_penalty"] == 0.5
    assert request_params["presence_penalty"] == 0.25
    assert request_params["stop"] == ["STOP"]


def test_mistral_sampling_params_omitted_when_not_provided():
    model = MistralChat(id="mistral-small-latest")

    request_params = model.get_request_params()

    assert "frequency_penalty" not in request_params
    assert "presence_penalty" not in request_params
    assert "stop" not in request_params


def test_mistral_request_params_can_override_sampling_params():
    model = MistralChat(
        id="mistral-small-latest",
        frequency_penalty=0.5,
        request_params={"frequency_penalty": 1.0},
    )

    request_params = model.get_request_params()

    assert request_params["frequency_penalty"] == 1.0


def test_mistral_to_dict_includes_sampling_params():
    model = MistralChat(
        id="mistral-small-latest",
        top_p=0.9,
        frequency_penalty=0.5,
        presence_penalty=0.25,
        stop=["STOP"],
    )

    model_dict = model.to_dict()

    assert model_dict["top_p"] == 0.9
    assert model_dict["frequency_penalty"] == 0.5
    assert model_dict["presence_penalty"] == 0.25
    assert model_dict["stop"] == ["STOP"]


# =============================================================================
# temperature / top_p / random_seed / penalties: zero values must not be dropped
# =============================================================================


def test_mistral_temperature_zero_included():
    """temperature=0.0 must appear in request params (falsy-check regression)."""
    model = MistralChat(id="mistral-small-latest", temperature=0.0)
    params = model.get_request_params()
    assert "temperature" in params
    assert params["temperature"] == 0.0


def test_mistral_top_p_zero_included():
    """top_p=0.0 must appear in request params (falsy-check regression)."""
    model = MistralChat(id="mistral-small-latest", top_p=0.0)
    params = model.get_request_params()
    assert "top_p" in params
    assert params["top_p"] == 0.0


def test_mistral_random_seed_zero_included():
    """random_seed=0 must appear in request params (falsy-check regression)."""
    model = MistralChat(id="mistral-small-latest", random_seed=0)
    params = model.get_request_params()
    assert "random_seed" in params
    assert params["random_seed"] == 0


def test_mistral_frequency_penalty_zero_included():
    """frequency_penalty=0.0 must appear in request params (falsy-check regression)."""
    model = MistralChat(id="mistral-small-latest", frequency_penalty=0.0)
    params = model.get_request_params()
    assert "frequency_penalty" in params
    assert params["frequency_penalty"] == 0.0


def test_mistral_presence_penalty_zero_included():
    """presence_penalty=0.0 must appear in request params (falsy-check regression)."""
    model = MistralChat(id="mistral-small-latest", presence_penalty=0.0)
    params = model.get_request_params()
    assert "presence_penalty" in params
    assert params["presence_penalty"] == 0.0


def test_mistral_temperature_none_excluded():
    """Unset temperature (None) must not appear in request params."""
    model = MistralChat(id="mistral-small-latest")
    params = model.get_request_params()
    assert "temperature" not in params


def test_mistral_top_p_none_excluded():
    """Unset top_p (None) must not appear in request params."""
    model = MistralChat(id="mistral-small-latest")
    params = model.get_request_params()
    assert "top_p" not in params


def test_mistral_positive_temperature_included():
    """Positive temperature is still forwarded correctly."""
    model = MistralChat(id="mistral-small-latest", temperature=0.7)
    params = model.get_request_params()
    assert params["temperature"] == 0.7


def test_mistral_all_sampling_params_zero():
    """All sampling params at zero must all appear in request params."""
    model = MistralChat(
        id="mistral-small-latest",
        temperature=0.0,
        top_p=0.0,
        frequency_penalty=0.0,
        presence_penalty=0.0,
    )
    params = model.get_request_params()
    assert params["temperature"] == 0.0
    assert params["top_p"] == 0.0
    assert params["frequency_penalty"] == 0.0
    assert params["presence_penalty"] == 0.0
