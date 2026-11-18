"""OpenAI's o-series and the gpt-5 family (gpt-5, gpt-5-mini, gpt-5-nano) answer any non-default
sampling parameter with a 400, so the request builders drop those values with a warning instead of
sending them. gpt-5.1 and later accept the full set again, and OpenAI-compatible providers are left
alone because their model ids say nothing about OpenAI's rules."""

from unittest.mock import MagicMock

import pytest

from agno.models.openai.chat import OpenAIChat
from agno.models.openai.like import OpenAILike
from agno.models.openai.open_responses import OpenResponses
from agno.models.openai.responses import OpenAIResponses
from agno.utils.models.openai import drop_fixed_sampling_params, has_fixed_sampling_params


@pytest.mark.parametrize(
    "model_id, expected",
    [
        ("gpt-5", True),
        ("gpt-5-mini", True),
        ("gpt-5-nano", True),
        ("gpt-5-2025-08-07", True),
        ("o1", True),
        ("o3", True),
        ("o3-mini", True),
        ("o4-mini", True),
        ("gpt-5.1", False),
        ("gpt-5.2", False),
        ("gpt-5.4-mini", False),
        ("gpt-4.1-mini", False),
        ("gpt-4o", False),
    ],
)
def test_has_fixed_sampling_params(model_id, expected):
    assert has_fixed_sampling_params(model_id) is expected


def test_chat_drops_what_a_fixed_sampling_model_rejects():
    model = OpenAIChat(
        id="gpt-5-mini",
        temperature=0,
        top_p=0.5,
        presence_penalty=0.5,
        frequency_penalty=0.5,
        logit_bias={"1": 1},
        logprobs=True,
        top_logprobs=1,
        stop=["zzz"],
        max_tokens=64,
        seed=7,
    )

    params = model.get_request_params()

    for name in (
        "temperature",
        "top_p",
        "presence_penalty",
        "frequency_penalty",
        "logit_bias",
        "logprobs",
        "top_logprobs",
        "stop",
        "max_tokens",
    ):
        assert name not in params, name
    assert params["max_completion_tokens"] == 64
    assert params["seed"] == 7


def test_chat_keeps_the_default_values():
    model = OpenAIChat(
        id="gpt-5-mini",
        temperature=1,
        top_p=1,
        presence_penalty=0,
        frequency_penalty=0,
        max_completion_tokens=32,
        max_tokens=64,
    )

    params = model.get_request_params()

    assert params["temperature"] == 1
    assert params["top_p"] == 1
    assert params["presence_penalty"] == 0
    assert params["frequency_penalty"] == 0
    assert params["max_completion_tokens"] == 32
    assert "max_tokens" not in params


def test_chat_leaves_other_models_alone():
    for model_id in ("gpt-5.4-mini", "gpt-4.1-mini"):
        params = OpenAIChat(id=model_id, temperature=0, top_p=0.5, stop=["zzz"], max_tokens=64).get_request_params()
        assert params["temperature"] == 0
        assert params["top_p"] == 0.5
        assert params["stop"] == ["zzz"]
        assert params["max_tokens"] == 64


def test_chat_filters_request_params_too():
    params = OpenAIChat(id="o4-mini", request_params={"temperature": 0, "top_p": 1}).get_request_params()

    assert "temperature" not in params
    assert params["top_p"] == 1


def test_openai_like_keeps_the_callers_values():
    params = OpenAILike(id="gpt-5-mini", base_url="http://localhost:8000/v1", temperature=0).get_request_params()

    assert params["temperature"] == 0


def test_responses_drops_temperature_and_top_p():
    params = OpenAIResponses(id="gpt-5-mini", temperature=0, top_p=0.5).get_request_params()

    assert "temperature" not in params
    assert "top_p" not in params


def test_responses_keeps_them_on_other_models():
    params = OpenAIResponses(id="gpt-5.4-mini", temperature=0, top_p=0.5).get_request_params()

    assert params["temperature"] == 0
    assert params["top_p"] == 0.5


def test_open_responses_keeps_the_callers_values():
    params = OpenResponses(id="gpt-5-mini", base_url="http://localhost:8000/v1", temperature=0).get_request_params()

    assert params["temperature"] == 0


def test_dropped_values_are_reported_once(monkeypatch):
    warn = MagicMock()
    monkeypatch.setattr("agno.utils.models.openai.log_warning", warn)

    drop_fixed_sampling_params({"temperature": 0, "top_p": 1, "stop": ["zzz"], "max_tokens": 64})
    drop_fixed_sampling_params({"temperature": 1})

    warn.assert_called_once()
    message = warn.call_args.args[0]
    assert "temperature=0" in message
    assert "stop=['zzz']" in message
    assert "max_tokens=64 (sent as max_completion_tokens)" in message
    assert "top_p" not in message
