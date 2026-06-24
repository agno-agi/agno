"""Unit tests for native structured-output support on AWS Bedrock Claude.

Bedrock-hosted Claude models support Anthropic's native structured outputs
(`output_format` + the `structured-outputs-2025-11-13` beta header) on the same
model generations as the direct Anthropic API. These tests pin that the Bedrock
subclass:
  - reports `supports_native_structured_outputs` correctly per model id, and
  - actually emits `output_format` and the beta header in outgoing requests.
"""

import pytest
from pydantic import BaseModel

pytest.importorskip("anthropic")
pytest.importorskip("boto3")

from agno.models.aws.claude import Claude as AwsClaude


class _Person(BaseModel):
    name: str
    age: int


class TestBedrockStructuredOutputSupportFlag:
    @pytest.mark.parametrize(
        "model_id",
        [
            # Confirmed GA on Bedrock via live calls (see AI-310 matrix)
            "global.anthropic.claude-sonnet-4-5-20250929-v1:0",
            "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
            "global.anthropic.claude-sonnet-4-6",
            "apac.anthropic.claude-haiku-4-5-20251001-v1:0",
            "global.anthropic.claude-opus-4-5-20251101-v1:0",
            "global.anthropic.claude-opus-4-6-v1",
            "claude-sonnet-4-5-20250929",  # plain Anthropic id — normalization is a no-op
        ],
    )
    def test_supported_models_enable_structured_outputs(self, model_id):
        model = AwsClaude(id=model_id, aws_access_key="k", aws_secret_key="s", aws_region="us-east-1")
        assert model.supports_native_structured_outputs is True

    @pytest.mark.parametrize(
        "model_id",
        [
            "anthropic.claude-3-5-sonnet-20240620-v1:0",
            "anthropic.claude-3-haiku-20240307-v1:0",
            "us.anthropic.claude-sonnet-4-20250514-v1:0",  # legacy Sonnet 4
            "us.anthropic.claude-opus-4-20250514-v1:0",  # legacy Opus 4
            # available on Bedrock but reject output_format (400) — see AI-310 matrix
            "us.anthropic.claude-opus-4-1-20250805-v1:0",
            "global.anthropic.claude-opus-4-7",
            # full inference-profile ARN of a legacy (Claude 3) model
            "arn:aws:bedrock:us-east-1:123456789012:inference-profile/us.anthropic.claude-3-5-sonnet-20240620-v1:0",
        ],
    )
    def test_unsupported_models_disable_structured_outputs(self, model_id):
        model = AwsClaude(id=model_id, aws_access_key="k", aws_secret_key="s", aws_region="us-east-1")
        assert model.supports_native_structured_outputs is False


@pytest.fixture
def model():
    return AwsClaude(
        id="global.anthropic.claude-sonnet-4-5-20250929-v1:0",
        aws_access_key="k",
        aws_secret_key="s",
        aws_region="us-east-1",
    )


class TestBedrockStructuredOutputRequestParams:
    def test_beta_header_added_with_response_format(self, model):
        params = model.get_request_params(response_format=_Person)
        assert "structured-outputs-2025-11-13" in params.get("betas", [])

    def test_no_beta_header_without_response_format(self, model):
        params = model.get_request_params()
        assert "structured-outputs-2025-11-13" not in params.get("betas", [])

    def test_output_format_built_in_request_kwargs(self, model):
        kwargs = model._prepare_request_kwargs("system prompt", response_format=_Person)
        assert "output_format" in kwargs
        assert kwargs["output_format"]["type"] == "json_schema"

    def test_no_output_format_without_response_format(self, model):
        kwargs = model._prepare_request_kwargs("system prompt")
        assert "output_format" not in kwargs

    def test_unsupported_model_omits_output_format(self):
        model = AwsClaude(
            id="anthropic.claude-3-5-sonnet-20240620-v1:0",
            aws_access_key="k",
            aws_secret_key="s",
            aws_region="us-east-1",
        )
        kwargs = model._prepare_request_kwargs("system prompt", response_format=_Person)
        assert "output_format" not in kwargs
        assert "structured-outputs-2025-11-13" not in kwargs.get("betas", [])


class TestSupportsBedrockStructuredOutputsHelper:
    """Direct tests for the shared supports_bedrock_structured_outputs() predicate."""

    @pytest.mark.parametrize(
        "base_id",
        [
            "claude-sonnet-4-5-20250929",
            "claude-sonnet-4-6",
            "claude-haiku-4-5-20251001",
            "claude-opus-4-5-20251101",
            "claude-opus-4-6-v1",
        ],
    )
    def test_supported_families(self, base_id):
        from agno.utils.models.claude import supports_bedrock_structured_outputs

        assert supports_bedrock_structured_outputs(base_id) is True

    @pytest.mark.parametrize(
        "base_id",
        [
            "claude-opus-4-1-20250805",  # available on Bedrock but rejects output_format
            "claude-opus-4-7",  # InvokeModel path unsupported
            "claude-sonnet-4-20250514",  # legacy Sonnet 4
            "claude-3-5-sonnet-20240620",
            "gpt-5.4",  # non-Claude
            "",
        ],
    )
    def test_unsupported_or_unknown(self, base_id):
        from agno.utils.models.claude import supports_bedrock_structured_outputs

        assert supports_bedrock_structured_outputs(base_id) is False
