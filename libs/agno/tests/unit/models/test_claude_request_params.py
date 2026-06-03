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
# cache_tools TTL must match extended_cache_time (Anthropic mixed-TTL rule)
# =============================================================================

_TOOLS = [{"name": "test", "description": "test tool", "input_schema": {"type": "object", "properties": {}}}]


def test_cache_tools_uses_1h_ttl_when_extended_cache_time():
    """With extended_cache_time the tools block must be cached at 1h, matching the system block.

    Anthropic processes cache blocks tools -> system -> messages and rejects a shorter TTL
    before a longer one, so a bare (5m) tools block before a 1h system block is invalid.
    """
    model = AnthropicClaude(id="claude-haiku-4-5", cache_tools=True, extended_cache_time=True)
    kwargs = model._prepare_request_kwargs("system prompt", tools=[dict(_TOOLS[0])])

    assert kwargs["tools"][-1]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}


def test_cache_tools_uses_default_ttl_without_extended_cache_time():
    """Without extended_cache_time the tools block stays at the default (5m) ephemeral cache."""
    model = AnthropicClaude(id="claude-haiku-4-5", cache_tools=True, extended_cache_time=False)
    kwargs = model._prepare_request_kwargs("system prompt", tools=[dict(_TOOLS[0])])

    assert kwargs["tools"][-1]["cache_control"] == {"type": "ephemeral"}


def test_cache_tools_disabled_leaves_tools_uncached():
    """With cache_tools off the tools block must not carry cache_control."""
    model = AnthropicClaude(id="claude-haiku-4-5", cache_tools=False, extended_cache_time=True)
    kwargs = model._prepare_request_kwargs("system prompt", tools=[dict(_TOOLS[0])])

    assert "cache_control" not in kwargs["tools"][-1]


def test_aws_cache_tools_inherits_extended_ttl():
    """AWS Claude inherits _apply_cache_tools, so the tools block must honor extended_cache_time."""
    pytest.importorskip("boto3")
    from agno.models.aws.claude import Claude as AwsClaude

    model = AwsClaude(cache_tools=True, extended_cache_time=True)
    kwargs = model._prepare_request_kwargs("system prompt", tools=[dict(_TOOLS[0])])

    assert kwargs["tools"][-1]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}


def test_vertexai_cache_tools_inherits_extended_ttl():
    """VertexAI Claude inherits _apply_cache_tools, so the tools block must honor extended_cache_time."""
    model = VertexAIClaude(id="claude-haiku-4-5", cache_tools=True, extended_cache_time=True)
    kwargs = model._prepare_request_kwargs("system prompt", tools=[dict(_TOOLS[0])])

    assert kwargs["tools"][-1]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}


def test_azure_cache_tools_inherits_extended_ttl():
    """Azure Claude inherits _apply_cache_tools, so the tools block must honor extended_cache_time."""
    from agno.models.azure.claude import Claude as AzureClaude

    model = AzureClaude(id="claude-haiku-4-5", cache_tools=True, extended_cache_time=True)
    kwargs = model._prepare_request_kwargs("system prompt", tools=[dict(_TOOLS[0])])

    assert kwargs["tools"][-1]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}


# =============================================================================
# temperature / top_p / top_k: zero values must not be silently dropped
# =============================================================================


def test_anthropic_temperature_zero_included():
    """temperature=0.0 must appear in request params (falsy-check regression)."""
    model = AnthropicClaude(id="claude-haiku-4-5-20251001", temperature=0.0)
    params = model.get_request_params()
    assert "temperature" in params
    assert params["temperature"] == 0.0


def test_anthropic_top_p_zero_included():
    """top_p=0.0 must appear in request params (falsy-check regression)."""
    model = AnthropicClaude(id="claude-haiku-4-5-20251001", top_p=0.0)
    params = model.get_request_params()
    assert "top_p" in params
    assert params["top_p"] == 0.0


def test_anthropic_top_k_zero_included():
    """top_k=0 must appear in request params (falsy-check regression)."""
    model = AnthropicClaude(id="claude-haiku-4-5-20251001", top_k=0)
    params = model.get_request_params()
    assert "top_k" in params
    assert params["top_k"] == 0


def test_anthropic_temperature_none_excluded():
    """Unset temperature (None) must not appear in request params."""
    model = AnthropicClaude(id="claude-haiku-4-5-20251001")
    params = model.get_request_params()
    assert "temperature" not in params


def test_anthropic_top_p_none_excluded():
    """Unset top_p (None) must not appear in request params."""
    model = AnthropicClaude(id="claude-haiku-4-5-20251001")
    params = model.get_request_params()
    assert "top_p" not in params


def test_anthropic_top_k_none_excluded():
    """Unset top_k (None) must not appear in request params."""
    model = AnthropicClaude(id="claude-haiku-4-5-20251001")
    params = model.get_request_params()
    assert "top_k" not in params


def test_anthropic_positive_temperature_included():
    """Positive temperature is still forwarded correctly."""
    model = AnthropicClaude(id="claude-haiku-4-5-20251001", temperature=0.7)
    params = model.get_request_params()
    assert params["temperature"] == 0.7


def test_anthropic_all_sampling_params_zero():
    """All three sampling params at zero must all appear in request params."""
    model = AnthropicClaude(id="claude-haiku-4-5-20251001", temperature=0.0, top_p=0.0, top_k=0)
    params = model.get_request_params()
    assert params["temperature"] == 0.0
    assert params["top_p"] == 0.0
    assert params["top_k"] == 0


def test_aws_temperature_zero_included():
    """AWS Claude: temperature=0.0 must appear in request params."""
    pytest.importorskip("boto3")
    from agno.models.aws.claude import Claude as AwsClaude

    model = AwsClaude(temperature=0.0)
    params = model.get_request_params()
    assert "temperature" in params
    assert params["temperature"] == 0.0


def test_aws_top_p_zero_included():
    """AWS Claude: top_p=0.0 must appear in request params."""
    pytest.importorskip("boto3")
    from agno.models.aws.claude import Claude as AwsClaude

    model = AwsClaude(top_p=0.0)
    params = model.get_request_params()
    assert "top_p" in params
    assert params["top_p"] == 0.0


def test_aws_top_k_zero_included():
    """AWS Claude: top_k=0 must appear in request params."""
    pytest.importorskip("boto3")
    from agno.models.aws.claude import Claude as AwsClaude

    model = AwsClaude(top_k=0)
    params = model.get_request_params()
    assert "top_k" in params
    assert params["top_k"] == 0


def test_aws_temperature_none_excluded():
    """AWS Claude: unset temperature must not appear in request params."""
    pytest.importorskip("boto3")
    from agno.models.aws.claude import Claude as AwsClaude

    model = AwsClaude()
    params = model.get_request_params()
    assert "temperature" not in params


def test_vertexai_temperature_zero_included():
    """VertexAI Claude: temperature=0.0 must appear in request params."""
    model = VertexAIClaude(temperature=0.0)
    params = model.get_request_params()
    assert "temperature" in params
    assert params["temperature"] == 0.0


def test_vertexai_top_p_zero_included():
    """VertexAI Claude: top_p=0.0 must appear in request params."""
    model = VertexAIClaude(top_p=0.0)
    params = model.get_request_params()
    assert "top_p" in params
    assert params["top_p"] == 0.0


def test_vertexai_top_k_zero_included():
    """VertexAI Claude: top_k=0 must appear in request params."""
    model = VertexAIClaude(top_k=0)
    params = model.get_request_params()
    assert "top_k" in params
    assert params["top_k"] == 0


def test_vertexai_temperature_none_excluded():
    """VertexAI Claude: unset temperature must not appear in request params."""
    model = VertexAIClaude()
    params = model.get_request_params()
    assert "temperature" not in params
