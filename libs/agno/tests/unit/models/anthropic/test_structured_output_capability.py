"""
Regression test for Claude structured output capability detection (#6509).

Uses a blocklist of legacy prefixes/aliases (NON_STRUCTURED_OUTPUT_PREFIXES,
NON_STRUCTURED_OUTPUT_ALIASES). All new models default to supported since
Anthropic's trend is universal structured output support.
"""

import pytest

from agno.models.anthropic.claude import Claude


class TestSupportsStructuredOutputs:
    """Tests for Claude._supports_structured_outputs()."""

    # --- Models that SHOULD support structured outputs ---

    @pytest.mark.parametrize(
        "model_id",
        [
            # Claude Opus 4.1
            "claude-opus-4-1-20250805",
            "claude-opus-4-1",
            # Claude Sonnet 4.5
            "claude-sonnet-4-5-20250929",
            "claude-sonnet-4-5",
            # Claude Opus 4.5
            "claude-opus-4-5-20251101",
            "claude-opus-4-5",
            # Claude Haiku 4.5
            "claude-haiku-4-5-20251001",
            "claude-haiku-4-5",
            # Claude Opus 4.6
            "claude-opus-4-6",
            "claude-opus-4-6-20251201",
            # Claude Sonnet 4.6
            "claude-sonnet-4-6",
            # Future models should also be supported by default
            "claude-opus-4-7",
            "claude-sonnet-5-0",
            "claude-opus-5-0",
            "claude-haiku-5-0",
        ],
    )
    def test_supported_models(self, model_id: str):
        """Supported and future Claude models should return True."""
        model = Claude(id=model_id)
        assert model._supports_structured_outputs() is True, f"Model '{model_id}' should support structured outputs"

    @pytest.mark.parametrize(
        "model_id",
        [
            "claude-sonnet-4-5-20250929",
            "claude-opus-4-6",
        ],
    )
    def test_native_structured_outputs_flag_set_in_post_init(self, model_id: str):
        """__post_init__ should set supports_native_structured_outputs = True for supported models."""
        model = Claude(id=model_id)
        assert model.supports_native_structured_outputs is True, (
            f"Model '{model_id}' should have supports_native_structured_outputs=True after init"
        )

    # --- Models that should NOT support structured outputs ---

    @pytest.mark.parametrize(
        "model_id",
        [
            # Claude 3.x family
            "claude-3-opus-20240229",
            "claude-3-sonnet-20240229",
            "claude-3-haiku-20240307",
            "claude-3-opus",
            "claude-3-sonnet",
            "claude-3-haiku",
            # Claude 3.5 family
            "claude-3-5-sonnet-20240620",
            "claude-3-5-sonnet-20241022",
            "claude-3-5-sonnet",
            "claude-3-5-haiku-20241022",
            "claude-3-5-haiku-latest",
            "claude-3-5-haiku",
            # Claude Sonnet 4.0
            "claude-sonnet-4-20250514",
            "claude-sonnet-4-0",
            "claude-sonnet-4",
            # Claude Opus 4.0
            "claude-opus-4-20250514",
            "claude-opus-4-0",
            "claude-opus-4",
        ],
    )
    def test_unsupported_models(self, model_id: str):
        """Legacy and unsupported models should return False."""
        model = Claude(id=model_id)
        assert model._supports_structured_outputs() is False, (
            f"Model '{model_id}' should NOT support structured outputs"
        )

    @pytest.mark.parametrize(
        "model_id",
        [
            "claude-3-opus-20240229",
            "claude-sonnet-4-20250514",
            "claude-opus-4-20250514",
        ],
    )
    def test_native_structured_outputs_flag_not_set_for_unsupported(self, model_id: str):
        """__post_init__ should NOT set supports_native_structured_outputs for unsupported models."""
        model = Claude(id=model_id)
        assert model.supports_native_structured_outputs is False, (
            f"Model '{model_id}' should have supports_native_structured_outputs=False after init"
        )

    # --- Bedrock provider-specific model IDs ---

    @pytest.mark.parametrize(
        "model_id",
        [
            # Bedrock format: region.anthropic.model-suffix
            "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
            "eu.anthropic.claude-sonnet-4-5-20250929-v1:0",
            "global.anthropic.claude-sonnet-4-5-20250929-v1:0",
            "us.anthropic.claude-sonnet-4-6-v1:0",
            "us.anthropic.claude-opus-4-6-20251201-v1:0",
            "us.anthropic.claude-haiku-4-5-20251001-v1:0",
            # Bedrock regional variants with different prefix
            "apac.anthropic.claude-sonnet-4-5-20250929-v1:0",
            "eu-central-1.anthropic.claude-opus-4-5-20251101-v1:0",
        ],
    )
    def test_bedrock_model_ids_support_structured_outputs(self, model_id: str):
        """Bedrock Claude model IDs (region.anthropic.X-v1:0) should be
        correctly normalized by _extract_claude_core_id and recognized as
        supporting native structured outputs."""
        model = Claude(id=model_id)
        assert model._supports_structured_outputs() is True, (
            f"Bedrock model '{model_id}' should support structured outputs"
        )

    @pytest.mark.parametrize(
        "model_id",
        [
            "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
            "us.anthropic.claude-opus-4-6-20251201-v1:0",
            "global.anthropic.claude-sonnet-4-5-20250929-v1:0",
        ],
    )
    def test_bedrock_native_structured_outputs_flag_set_in_post_init(self, model_id: str):
        """__post_init__ on the Anthropic Claude class should set
        supports_native_structured_outputs=True for Bedrock model IDs after
        _extract_claude_core_id normalization."""
        model = Claude(id=model_id)
        assert model.supports_native_structured_outputs is True, (
            f"Bedrock model '{model_id}' should have supports_native_structured_outputs=True after init"
        )

    @pytest.mark.parametrize(
        "model_id",
        [
            # Bedrock Claude 3.x (unsupported)
            "us.anthropic.claude-3-sonnet-20240229-v1:0",
            "us.anthropic.claude-3-haiku-20240307-v1:0",
            "us.anthropic.claude-3-opus-20240229-v1:0",
            # Bedrock Claude 3.5 (unsupported)
            "us.anthropic.claude-3-5-sonnet-20240620-v1:0",
            "us.anthropic.claude-3-5-haiku-20241022-v1:0",
            # Bedrock Claude Sonnet 4.0 (unsupported)
            "us.anthropic.claude-sonnet-4-20250514-v1:0",
            # Bedrock Claude Opus 4.0 (unsupported)
            "us.anthropic.claude-opus-4-20250514-v1:0",
        ],
    )
    def test_bedrock_unsupported_model_ids(self, model_id: str):
        """Bedrock model IDs for legacy/unsupported models should not report
        native structured output support."""
        model = Claude(id=model_id)
        assert model._supports_structured_outputs() is False, (
            f"Bedrock model '{model_id}' should NOT support structured outputs"
        )

    # --- Vertex AI provider-specific model IDs ---

    @pytest.mark.parametrize(
        "model_id",
        [
            "claude-sonnet-4-5@20250929",
            "claude-opus-4-6@20251201",
            "claude-haiku-4-5@20251001",
        ],
    )
    def test_vertex_ai_model_ids_support_structured_outputs(self, model_id: str):
        """Vertex AI Claude model IDs (X@YYYYMMDD) should be normalized by
        _extract_claude_core_id and recognized as supporting structured outputs."""
        model = Claude(id=model_id)
        assert model._supports_structured_outputs() is True, (
            f"Vertex AI model '{model_id}' should support structured outputs"
        )

    # --- LiteLLM provider-specific model IDs ---

    @pytest.mark.parametrize(
        "model_id",
        [
            "anthropic/claude-sonnet-4-5-20250929",
            "anthropic/claude-opus-4-6-20251201",
        ],
    )
    def test_litellm_model_ids_support_structured_outputs(self, model_id: str):
        """LiteLLM Claude model IDs (anthropic/X) should be normalized by
        _extract_claude_core_id and recognized as supporting structured outputs."""
        model = Claude(id=model_id)
        assert model._supports_structured_outputs() is True, (
            f"LiteLLM model '{model_id}' should support structured outputs"
        )
