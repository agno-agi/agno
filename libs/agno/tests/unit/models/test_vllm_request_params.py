"""vLLM sampling options must survive request construction and serialization."""

import pytest

from agno.models.vllm import VLLM


@pytest.mark.parametrize("repetition_penalty,min_p", [(1.1, 0.05), (1.0, 0.0)])
def test_sampling_params_are_sent_in_extra_body(repetition_penalty, min_p):
    model = VLLM(repetition_penalty=repetition_penalty, min_p=min_p)

    params = model.get_request_params()

    assert params["extra_body"] == {"repetition_penalty": repetition_penalty, "min_p": min_p}
    assert "repetition_penalty" not in params
    assert "min_p" not in params


def test_unset_sampling_params_preserve_server_defaults():
    model = VLLM()

    assert "extra_body" not in model.get_request_params()
    assert "repetition_penalty" not in model.to_dict()
    assert "min_p" not in model.to_dict()


@pytest.mark.parametrize("explicit", [False, True])
def test_sampling_params_merge_without_mutating_extra_body(explicit):
    extra_body = {"repetition_penalty": 1.2, "min_p": 0.1, "ignore_eos": True}
    model = VLLM(
        repetition_penalty=1.0 if explicit else None,
        min_p=0.0 if explicit else None,
        top_k=20,
        enable_thinking=False,
        extra_body=extra_body,
    )

    params = model.get_request_params()

    assert params["extra_body"] == {
        "repetition_penalty": 1.0 if explicit else 1.2,
        "min_p": 0.0 if explicit else 0.1,
        "ignore_eos": True,
        "top_k": 20,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    assert extra_body == {"repetition_penalty": 1.2, "min_p": 0.1, "ignore_eos": True}


def test_sampling_params_survive_model_round_trip():
    model = VLLM(repetition_penalty=1.1, min_p=0.0, extra_body={"ignore_eos": True})

    restored = VLLM.from_dict(model.to_dict())

    assert restored.get_request_params() == model.get_request_params()
