import pytest

pytest.importorskip("litellm")

from agno.models.litellm import LiteLLM


@pytest.mark.parametrize(
    "model_id",
    [
        "anthropic/claude-sonnet-4-5",
        "claude-opus-4-5",
        "bedrock/us.anthropic.claude-opus-4-5-20251101-v1:0",
        "vertex_ai/claude-sonnet-4-5@20250929",
    ],
)
def test_claude_gets_the_default_temperature_without_top_p(model_id):
    params = LiteLLM(id=model_id).get_request_params()

    assert params["temperature"] == 0.7
    assert "top_p" not in params


def test_other_models_keep_both_defaults():
    params = LiteLLM(id="openai/gpt-4o-mini").get_request_params()

    assert params["temperature"] == 0.7
    assert params["top_p"] == 1.0


def test_claude_keeps_a_top_p_the_user_changed():
    params = LiteLLM(id="anthropic/claude-sonnet-4-5", top_p=0.9).get_request_params()

    assert params["temperature"] == 0.7
    assert params["top_p"] == 0.9


def test_claude_keeps_top_p_when_no_temperature_is_sent():
    params = LiteLLM(id="anthropic/claude-sonnet-4-5", temperature=None).get_request_params()

    assert "temperature" not in params
    assert params["top_p"] == 1.0


def test_none_sends_neither():
    params = LiteLLM(id="openai/gpt-4o-mini", temperature=None, top_p=None).get_request_params()

    assert "temperature" not in params
    assert "top_p" not in params
