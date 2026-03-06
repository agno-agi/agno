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
