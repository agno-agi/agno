"""Unit tests for Claude request params: output_config passthrough
and _prepare_request_kwargs messages parameter compatibility."""

from unittest.mock import MagicMock

import pytest

pytest.importorskip("anthropic")

from agno.models.anthropic.claude import Claude as AnthropicClaude
from agno.models.vertexai.claude import Claude as VertexAIClaude


def test_anthropic_output_config_in_request_params():
    model = AnthropicClaude(
        id="claude-sonnet-4-6",
        thinking={"type": "adaptive"},
        output_config={"effort": "high"},
    )

    request_params = model.get_request_params()

    assert request_params["thinking"] == {"type": "adaptive"}
    assert request_params["output_config"] == {"effort": "high"}


def test_anthropic_output_config_omitted_when_not_provided():
    model = AnthropicClaude(id="claude-sonnet-4-6", thinking={"type": "adaptive"})

    request_params = model.get_request_params()

    assert request_params["thinking"] == {"type": "adaptive"}
    assert "output_config" not in request_params


def test_anthropic_request_params_can_override_output_config():
    model = AnthropicClaude(
        id="claude-sonnet-4-6",
        output_config={"effort": "high"},
        request_params={"output_config": {"effort": "low"}},
    )

    request_params = model.get_request_params()

    assert request_params["output_config"] == {"effort": "low"}


def test_anthropic_to_dict_includes_output_config():
    model = AnthropicClaude(id="claude-sonnet-4-6", output_config={"effort": "medium"})

    model_dict = model.to_dict()

    assert model_dict["output_config"] == {"effort": "medium"}


def test_aws_claude_output_config_in_request_params():
    pytest.importorskip("boto3")
    from agno.models.aws.claude import Claude as AwsClaude

    model = AwsClaude(output_config={"effort": "high"})

    request_params = model.get_request_params()

    assert request_params["output_config"] == {"effort": "high"}


def test_aws_output_config_omitted_when_not_provided():
    pytest.importorskip("boto3")
    from agno.models.aws.claude import Claude as AwsClaude

    model = AwsClaude()

    request_params = model.get_request_params()

    assert "output_config" not in request_params


def test_aws_request_params_can_override_output_config():
    pytest.importorskip("boto3")
    from agno.models.aws.claude import Claude as AwsClaude

    model = AwsClaude(
        output_config={"effort": "high"},
        request_params={"output_config": {"effort": "low"}},
    )

    request_params = model.get_request_params()

    assert request_params["output_config"] == {"effort": "low"}


def test_vertexai_claude_output_config_in_request_params():
    model = VertexAIClaude(output_config={"effort": "high"})

    request_params = model.get_request_params()

    assert request_params["output_config"] == {"effort": "high"}


def test_vertexai_output_config_omitted_when_not_provided():
    model = VertexAIClaude()

    request_params = model.get_request_params()

    assert "output_config" not in request_params


def test_vertexai_request_params_can_override_output_config():
    model = VertexAIClaude(
        output_config={"effort": "high"},
        request_params={"output_config": {"effort": "low"}},
    )

    request_params = model.get_request_params()

    assert request_params["output_config"] == {"effort": "low"}


def test_aws_to_dict_includes_output_config():
    pytest.importorskip("boto3")
    from agno.models.aws.claude import Claude as AwsClaude

    model = AwsClaude(output_config={"effort": "high"})

    model_dict = model.to_dict()

    assert model_dict["output_config"] == {"effort": "high"}


def test_vertexai_to_dict_includes_output_config():
    model = VertexAIClaude(output_config={"effort": "medium"})

    model_dict = model.to_dict()

    assert model_dict["output_config"] == {"effort": "medium"}


# =============================================================================
# _prepare_request_kwargs accepts messages parameter
# =============================================================================


def _make_mock_message(role: str, container_id: str | None = None):
    """Create a minimal Message-like mock with optional container provider_data."""
    msg = MagicMock()
    msg.role = role
    if container_id:
        msg.provider_data = {"container": {"id": container_id}}
    else:
        msg.provider_data = None
    return msg


def test_aws_prepare_request_kwargs_accepts_messages():
    """AWS Claude._prepare_request_kwargs must accept messages kwarg without TypeError."""
    pytest.importorskip("boto3")
    from agno.models.aws.claude import Claude as AwsClaude

    model = AwsClaude()
    messages = [_make_mock_message("user"), _make_mock_message("assistant")]
    kwargs = model._prepare_request_kwargs("You are helpful.", messages=messages)

    assert "system" in kwargs
    assert kwargs["system"] == [{"text": "You are helpful.", "type": "text"}]


def test_vertexai_prepare_request_kwargs_accepts_messages():
    """VertexAI Claude._prepare_request_kwargs must accept messages kwarg without TypeError."""
    model = VertexAIClaude()
    messages = [_make_mock_message("user"), _make_mock_message("assistant")]
    kwargs = model._prepare_request_kwargs("You are helpful.", messages=messages)

    assert "system" in kwargs
    assert kwargs["system"] == [{"text": "You are helpful.", "type": "text"}]


def test_aws_prepare_request_kwargs_messages_does_not_affect_output():
    """Passing messages to AWS Claude should not change the returned kwargs."""
    pytest.importorskip("boto3")
    from agno.models.aws.claude import Claude as AwsClaude

    model = AwsClaude()
    kwargs_without = model._prepare_request_kwargs("system prompt")
    kwargs_with = model._prepare_request_kwargs("system prompt", messages=[_make_mock_message("user")])

    assert kwargs_without == kwargs_with


def test_vertexai_prepare_request_kwargs_messages_does_not_affect_output():
    """Passing messages to VertexAI Claude should not change the returned kwargs."""
    model = VertexAIClaude()
    kwargs_without = model._prepare_request_kwargs("system prompt")
    kwargs_with = model._prepare_request_kwargs("system prompt", messages=[_make_mock_message("user")])

    assert kwargs_without == kwargs_with


def test_aws_prepare_request_kwargs_signature_matches_parent():
    """AWS Claude._prepare_request_kwargs signature must match parent for all kwargs."""
    pytest.importorskip("boto3")
    from agno.models.aws.claude import Claude as AwsClaude

    model = AwsClaude()
    kwargs = model._prepare_request_kwargs(
        "system prompt",
        tools=[{"name": "test", "description": "test tool", "input_schema": {"type": "object", "properties": {}}}],
        response_format=None,
        messages=[_make_mock_message("user")],
    )

    assert "system" in kwargs
    assert "tools" in kwargs


def test_vertexai_prepare_request_kwargs_signature_matches_parent():
    """VertexAI Claude._prepare_request_kwargs signature must match parent for all kwargs."""
    model = VertexAIClaude()
    kwargs = model._prepare_request_kwargs(
        "system prompt",
        tools=[{"name": "test", "description": "test tool", "input_schema": {"type": "object", "properties": {}}}],
        response_format=None,
        messages=[_make_mock_message("user")],
    )

    assert "system" in kwargs
    assert "tools" in kwargs


# =============================================================================
# temperature / top_p / top_k: zero values must not be silently dropped.
# They ride in extra_body because anthropic 1.0.0 stopped declaring them on the
# request methods, so a zero being dropped now means a zero missing from there.
# =============================================================================


def test_anthropic_temperature_zero_included():
    """temperature=0.0 must survive into the request, in extra_body (falsy-check regression)."""
    model = AnthropicClaude(id="claude-haiku-4-5-20251001", temperature=0.0)
    params = model.get_request_params()
    assert "temperature" not in params, "sampling params travel in extra_body"
    assert params["extra_body"]["temperature"] == 0.0


def test_anthropic_top_p_zero_included():
    """top_p=0.0 must survive into the request, in extra_body (falsy-check regression)."""
    model = AnthropicClaude(id="claude-haiku-4-5-20251001", top_p=0.0)
    params = model.get_request_params()
    assert "top_p" not in params, "sampling params travel in extra_body"
    assert params["extra_body"]["top_p"] == 0.0


def test_anthropic_top_k_zero_included():
    """top_k=0 must survive into the request, in extra_body (falsy-check regression)."""
    model = AnthropicClaude(id="claude-haiku-4-5-20251001", top_k=0)
    params = model.get_request_params()
    assert "top_k" not in params, "sampling params travel in extra_body"
    assert params["extra_body"]["top_k"] == 0


def test_anthropic_temperature_none_excluded():
    """Unset temperature (None) must not appear in request params."""
    model = AnthropicClaude(id="claude-haiku-4-5-20251001")
    params = model.get_request_params()
    assert "temperature" not in params
    assert "extra_body" not in params


def test_anthropic_top_p_none_excluded():
    """Unset top_p (None) must not appear in request params."""
    model = AnthropicClaude(id="claude-haiku-4-5-20251001")
    params = model.get_request_params()
    assert "top_p" not in params
    assert "extra_body" not in params


def test_anthropic_top_k_none_excluded():
    """Unset top_k (None) must not appear in request params."""
    model = AnthropicClaude(id="claude-haiku-4-5-20251001")
    params = model.get_request_params()
    assert "top_k" not in params
    assert "extra_body" not in params


def test_anthropic_positive_temperature_included():
    """Positive temperature is still forwarded correctly, in extra_body."""
    model = AnthropicClaude(id="claude-haiku-4-5-20251001", temperature=0.7)
    params = model.get_request_params()
    assert params["extra_body"]["temperature"] == 0.7


def test_anthropic_all_sampling_params_zero():
    """Zero sampling params must survive together into extra_body.

    temperature and top_p are checked in separate pairs: Anthropic rejects those two
    together on every current model, so that pair never reaches the request.
    """
    params = AnthropicClaude(id="claude-haiku-4-5-20251001", temperature=0.0, top_k=0).get_request_params()
    assert params["extra_body"] == {"temperature": 0.0, "top_k": 0}

    params = AnthropicClaude(id="claude-haiku-4-5-20251001", top_p=0.0, top_k=0).get_request_params()
    assert params["extra_body"] == {"top_p": 0.0, "top_k": 0}


def test_aws_temperature_zero_included():
    """AWS Claude: temperature=0.0 must survive into the request, in extra_body."""
    pytest.importorskip("boto3")
    from agno.models.aws.claude import Claude as AwsClaude

    model = AwsClaude(temperature=0.0)
    params = model.get_request_params()
    assert "temperature" not in params, "sampling params travel in extra_body"
    assert params["extra_body"]["temperature"] == 0.0


def test_aws_top_p_zero_included():
    """AWS Claude: top_p=0.0 must survive into the request, in extra_body."""
    pytest.importorskip("boto3")
    from agno.models.aws.claude import Claude as AwsClaude

    model = AwsClaude(top_p=0.0)
    params = model.get_request_params()
    assert "top_p" not in params, "sampling params travel in extra_body"
    assert params["extra_body"]["top_p"] == 0.0


def test_aws_top_k_zero_included():
    """AWS Claude: top_k=0 must survive into the request, in extra_body."""
    pytest.importorskip("boto3")
    from agno.models.aws.claude import Claude as AwsClaude

    model = AwsClaude(top_k=0)
    params = model.get_request_params()
    assert "top_k" not in params, "sampling params travel in extra_body"
    assert params["extra_body"]["top_k"] == 0


def test_aws_temperature_none_excluded():
    """AWS Claude: unset temperature must not appear in request params."""
    pytest.importorskip("boto3")
    from agno.models.aws.claude import Claude as AwsClaude

    model = AwsClaude()
    params = model.get_request_params()
    assert "temperature" not in params
    assert "extra_body" not in params


def test_vertexai_temperature_zero_included():
    """VertexAI Claude: temperature=0.0 must survive into the request, in extra_body."""
    model = VertexAIClaude(temperature=0.0)
    params = model.get_request_params()
    assert "temperature" not in params, "sampling params travel in extra_body"
    assert params["extra_body"]["temperature"] == 0.0


def test_vertexai_top_p_zero_included():
    """VertexAI Claude: top_p=0.0 must survive into the request, in extra_body."""
    model = VertexAIClaude(top_p=0.0)
    params = model.get_request_params()
    assert "top_p" not in params, "sampling params travel in extra_body"
    assert params["extra_body"]["top_p"] == 0.0


def test_vertexai_top_k_zero_included():
    """VertexAI Claude: top_k=0 must survive into the request, in extra_body."""
    model = VertexAIClaude(top_k=0)
    params = model.get_request_params()
    assert "top_k" not in params, "sampling params travel in extra_body"
    assert params["extra_body"]["top_k"] == 0


def test_vertexai_temperature_none_excluded():
    """VertexAI Claude: unset temperature must not appear in request params."""
    model = VertexAIClaude()
    params = model.get_request_params()
    assert "temperature" not in params
    assert "extra_body" not in params


# =============================================================================
# thinking / models without sampling support: a temperature, top_p or top_k the API
# would reject with a 400 is dropped from the request instead of failing it (#9931).
# =============================================================================

THINKING = {"type": "enabled", "budget_tokens": 1024}


def test_anthropic_thinking_drops_temperature():
    """temperature=0 with thinking on is rejected by Anthropic, so it must not be sent."""
    model = AnthropicClaude(id="claude-haiku-4-5-20251001", temperature=0.0, thinking=THINKING)
    params = model.get_request_params()
    assert params["thinking"] == THINKING
    assert "extra_body" not in params


def test_anthropic_thinking_keeps_temperature_one():
    """temperature=1 is the one value accepted alongside thinking, so it stays in extra_body."""
    model = AnthropicClaude(id="claude-haiku-4-5-20251001", temperature=1.0, thinking=THINKING)
    params = model.get_request_params()
    assert params["extra_body"] == {"temperature": 1.0}


def test_anthropic_temperature_and_top_p_are_never_sent_together():
    """Anthropic rejects the pair on every current model; without thinking, temperature is the one kept."""
    model = AnthropicClaude(id="claude-haiku-4-5-20251001", temperature=0.5, top_p=0.9)
    params = model.get_request_params()
    assert params["extra_body"] == {"temperature": 0.5}


def test_anthropic_explicit_extra_body_is_filtered_too():
    """A sampling value passed straight through request_params["extra_body"] gets the same treatment."""
    supplied = {"extra_body": {"temperature": 0.0}}
    model = AnthropicClaude(id="claude-haiku-4-5-20251001", thinking=THINKING, request_params=supplied)
    params = model.get_request_params()
    assert "extra_body" not in params
    assert supplied == {"extra_body": {"temperature": 0.0}}, "the caller's request_params was mutated"


def test_anthropic_thinking_from_request_params_is_seen():
    """thinking passed through request_params counts too: the filter runs on the merged dict."""
    model = AnthropicClaude(id="claude-haiku-4-5-20251001", temperature=0.0, request_params={"thinking": THINKING})
    params = model.get_request_params()
    assert "extra_body" not in params


def test_anthropic_thinking_inside_extra_body_is_seen():
    """thinking passed raw through extra_body reaches the API too, so it counts for the filter."""
    supplied = {"extra_body": {"thinking": THINKING, "temperature": 0.0}}
    model = AnthropicClaude(id="claude-haiku-4-5-20251001", request_params=supplied)
    params = model.get_request_params()
    assert params["extra_body"] == {"thinking": THINKING}
    assert supplied == {"extra_body": {"thinking": THINKING, "temperature": 0.0}}, (
        "the caller's request_params was mutated"
    )


def test_anthropic_model_without_sampling_support_drops_them_without_thinking():
    """Claude Sonnet 5 rejects a non-default temperature, top_p or top_k on every request."""
    model = AnthropicClaude(id="claude-sonnet-5", temperature=0.0, top_p=1.0, top_k=1)
    params = model.get_request_params()
    assert "extra_body" not in params


def test_aws_thinking_drops_temperature():
    pytest.importorskip("boto3")
    from agno.models.aws.claude import Claude as AwsClaude

    model = AwsClaude(id="us.anthropic.claude-sonnet-4-5-20250929-v1:0", temperature=0.0, thinking=THINKING)
    params = model.get_request_params()
    assert params["thinking"] == THINKING
    assert "extra_body" not in params


def test_vertexai_thinking_drops_temperature():
    model = VertexAIClaude(id="claude-sonnet-4-5@20250929", temperature=0.0, thinking=THINKING)
    params = model.get_request_params()
    assert params["thinking"] == THINKING
    assert "extra_body" not in params


def test_azure_thinking_drops_temperature():
    from agno.models.azure import AzureFoundryClaude

    # 0.5 rather than 0: AzureFoundryClaude still gates sampling params on truthiness.
    model = AzureFoundryClaude(
        id="claude-sonnet-4-5", api_key="test-key", resource="my-resource", temperature=0.5, thinking=THINKING
    )
    params = model.get_request_params()
    assert params["thinking"] == THINKING
    assert "extra_body" not in params
