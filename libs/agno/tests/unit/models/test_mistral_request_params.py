"""Unit tests for Mistral request params: the standard sampling parameters
supported by the Mistral chat-completions API are forwarded via get_request_params."""

import pytest

pytest.importorskip("mistralai")

from agno.models.mistral.mistral import MistralChat


def test_mistral_forwards_supported_sampling_params():
    model = MistralChat(
        id="mistral-small-latest",
        frequency_penalty=0.5,
        presence_penalty=0.25,
        stop=["STOP"],
        n=2,
    )

    request_params = model.get_request_params()

    assert request_params["frequency_penalty"] == 0.5
    assert request_params["presence_penalty"] == 0.25
    assert request_params["stop"] == ["STOP"]
    assert request_params["n"] == 2


def test_mistral_omits_unset_sampling_params():
    model = MistralChat(id="mistral-small-latest")

    request_params = model.get_request_params()

    for key in ("frequency_penalty", "presence_penalty", "stop", "n"):
        assert key not in request_params
