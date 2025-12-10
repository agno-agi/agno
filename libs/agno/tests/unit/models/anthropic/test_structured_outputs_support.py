"""Unit tests for Claude model structured outputs support."""

import pytest
from agno.models.anthropic import Claude


class TestClaudeStructuredOutputsSupport:
    """Test Claude model's structured outputs support detection."""

    def test_claude_opus_4_5_supports_structured_outputs(self):
        """Test that Claude Opus 4.5 models support structured outputs."""
        model = Claude(id="claude-opus-4-5-20251101")
        assert model._supports_structured_outputs() is True

    def test_claude_opus_4_1_supports_structured_outputs(self):
        """Test that Claude Opus 4.1 models support structured outputs."""
        model = Claude(id="claude-opus-4-1-20250101")
        assert model._supports_structured_outputs() is True

    def test_claude_opus_4_0_does_not_support_structured_outputs(self):
        """Test that Claude Opus 4.0 models do not support structured outputs."""
        model = Claude(id="claude-opus-4-20250101")
        assert model._supports_structured_outputs() is False

    def test_claude_sonnet_4_5_supports_structured_outputs(self):
        """Test that Claude Sonnet 4.5 models support structured outputs."""
        model = Claude(id="claude-sonnet-4-5-20250929")
        assert model._supports_structured_outputs() is True

    def test_claude_sonnet_4_0_does_not_support_structured_outputs(self):
        """Test that Claude Sonnet 4.0 models do not support structured outputs."""
        model = Claude(id="claude-sonnet-4-20250514")
        assert model._supports_structured_outputs() is False

    def test_claude_3_models_do_not_support_structured_outputs(self):
        """Test that all Claude 3.x models do not support structured outputs."""
        models = [
            "claude-3-opus-20240229",
            "claude-3-sonnet-20240229",
            "claude-3-haiku-20240307",
            "claude-3-5-sonnet-20240620",
            "claude-3-5-sonnet-20241022",
            "claude-3-5-haiku-20241022",
        ]
        for model_id in models:
            model = Claude(id=model_id)
            assert model._supports_structured_outputs() is False, f"Model {model_id} should not support structured outputs"

    def test_claude_opus_4_5_with_variant_formats(self):
        """Test Claude Opus 4.5 with different date formats."""
        models = [
            "claude-opus-4-5-20251101",
            "claude-opus-4-5-20251201",
            "claude-opus-4-5-beta",
        ]
        for model_id in models:
            model = Claude(id=model_id)
            assert model._supports_structured_outputs() is True, f"Model {model_id} should support structured outputs"

    def test_future_claude_models_support_structured_outputs(self):
        """Test that future Claude models (not in blacklist) support structured outputs by default."""
        # Future models that are not explicitly blacklisted should support structured outputs
        future_models = [
            "claude-opus-5-20260101",
            "claude-sonnet-5-20260101",
            "claude-haiku-5-20260101",
        ]
        for model_id in future_models:
            model = Claude(id=model_id)
            assert model._supports_structured_outputs() is True, f"Future model {model_id} should support structured outputs"

    def test_blacklisted_models_do_not_support_structured_outputs(self):
        """Test that models in NON_STRUCTURED_OUTPUT_MODELS do not support structured outputs."""
        blacklisted_models = [
            "claude-3-opus-20240229",
            "claude-3-sonnet-20240229",
            "claude-3-haiku-20240307",
            "claude-sonnet-4-20250514",
        ]
        for model_id in blacklisted_models:
            model = Claude(id=model_id)
            assert model._supports_structured_outputs() is False, f"Blacklisted model {model_id} should not support structured outputs"

    def test_default_model_supports_structured_outputs(self):
        """Test that the default Claude model supports structured outputs."""
        model = Claude()  # Uses default id="claude-sonnet-4-5-20250929"
        assert model._supports_structured_outputs() is True
