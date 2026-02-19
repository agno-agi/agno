"""
Regression test for Claude structured output capability detection (#6509).

The _supports_structured_outputs() method used overly restrictive pattern checks
that rejected newer Claude model IDs (e.g. claude-opus-4-6) even though they
support structured outputs. The fix removes the hard-coded version whitelists
for Sonnet 4.x and Opus 4.x families, relying instead on the explicit
NON_STRUCTURED_OUTPUT_MODELS blacklist and the claude-3-* legacy prefix check.
"""

import pytest

from agno.models.anthropic.claude import Claude


class TestSupportsStructuredOutputs:
    """Tests for Claude._supports_structured_outputs()."""

    # --- Models that SHOULD support structured outputs ---

    @pytest.mark.parametrize(
        "model_id",
        [
            # Claude Sonnet 4.5 family
            "claude-sonnet-4-5-20250929",
            "claude-sonnet-4-5-latest",
            # Claude Opus 4.1 / 4.5 / 4.6 family
            "claude-opus-4-1-20250630",
            "claude-opus-4-5-20250901",
            "claude-opus-4-6",
            "claude-opus-4-6-20251201",
            # Future models should also be supported
            "claude-opus-4-7",
            "claude-sonnet-4-6",
            "claude-sonnet-5-0",
            "claude-opus-5-0",
        ],
    )
    def test_modern_models_support_structured_outputs(self, model_id: str):
        """Modern Claude models should report structured output support."""
        model = Claude(id=model_id)
        assert model._supports_structured_outputs() is True, f"Model '{model_id}' should support structured outputs"

    @pytest.mark.parametrize(
        "model_id",
        [
            # Claude Sonnet 4.5 family
            "claude-sonnet-4-5-20250929",
            # Claude Opus 4.6
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
            "claude-sonnet-4",
        ],
    )
    def test_legacy_models_do_not_support_structured_outputs(self, model_id: str):
        """Legacy Claude models should NOT report structured output support."""
        model = Claude(id=model_id)
        assert model._supports_structured_outputs() is False, (
            f"Model '{model_id}' should NOT support structured outputs"
        )

    @pytest.mark.parametrize(
        "model_id",
        [
            "claude-3-opus-20240229",
            "claude-sonnet-4-20250514",
        ],
    )
    def test_native_structured_outputs_flag_not_set_for_legacy(self, model_id: str):
        """__post_init__ should NOT set supports_native_structured_outputs for legacy models."""
        model = Claude(id=model_id)
        assert model.supports_native_structured_outputs is False, (
            f"Model '{model_id}' should have supports_native_structured_outputs=False after init"
        )
