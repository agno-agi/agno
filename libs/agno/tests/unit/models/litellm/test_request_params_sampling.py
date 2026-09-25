from agno.models.litellm import LiteLLM


def test_no_sampling_params_are_sent_by_default():
    params = LiteLLM(id="anthropic/claude-sonnet-4-5").get_request_params()

    assert "temperature" not in params
    assert "top_p" not in params


def test_sampling_params_set_on_the_model_are_sent():
    params = LiteLLM(id="openai/gpt-4o-mini", temperature=0.2, top_p=0.9).get_request_params()

    assert params["temperature"] == 0.2
    assert params["top_p"] == 0.9


def test_a_zero_temperature_is_still_sent():
    params = LiteLLM(id="openai/gpt-4o-mini", temperature=0.0).get_request_params()

    assert params["temperature"] == 0.0
    assert "top_p" not in params
