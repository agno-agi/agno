"""Unit tests for Claude output_config passthrough (#7050)."""

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
