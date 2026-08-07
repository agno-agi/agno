"""Unit tests for Cerebras request params: the standard OpenAI-compatible sampling
parameters supported by the Cerebras API are forwarded via get_request_params."""

import pytest

pytest.importorskip("cerebras.cloud.sdk")

from agno.models.cerebras.cerebras import Cerebras


def test_cerebras_forwards_supported_sampling_params():
    model = Cerebras(
        id="llama-4-scout-17b-16e-instruct",
        seed=42,
        stop=["STOP"],
        frequency_penalty=0.5,
        presence_penalty=0.25,
        logit_bias={"123": -10},
        logprobs=True,
        top_logprobs=3,
        user="user-123",
    )

    request_params = model.get_request_params()

    assert request_params["seed"] == 42
    assert request_params["stop"] == ["STOP"]
    assert request_params["frequency_penalty"] == 0.5
    assert request_params["presence_penalty"] == 0.25
    assert request_params["logit_bias"] == {"123": -10}
    assert request_params["logprobs"] is True
    assert request_params["top_logprobs"] == 3
    assert request_params["user"] == "user-123"


def test_cerebras_omits_unset_sampling_params():
    model = Cerebras(id="llama-4-scout-17b-16e-instruct")

    request_params = model.get_request_params()

    for key in (
        "seed",
        "stop",
        "frequency_penalty",
        "presence_penalty",
        "logit_bias",
        "logprobs",
        "top_logprobs",
        "user",
    ):
        assert key not in request_params
