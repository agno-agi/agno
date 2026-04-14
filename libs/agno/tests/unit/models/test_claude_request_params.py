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
