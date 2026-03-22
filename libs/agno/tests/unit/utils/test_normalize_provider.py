"""Tests for provider identifier normalization.

Ensures that display names exposed at runtime (e.g. ``"OpenAI"``, ``"Azure"``,
``"LMStudio"``) are correctly normalized to the canonical keys expected by
``_get_model_class`` and ``get_model``.

See: https://github.com/agno-agi/agno/issues/7093
"""

import pytest

from agno.models.utils import normalize_provider


# ---------------------------------------------------------------------------
# normalize_provider — unit tests
# ---------------------------------------------------------------------------

class TestNormalizeProvider:
    """Test the normalize_provider helper directly."""

    @pytest.mark.parametrize(
        "input_val,expected",
        [
            # Canonical keys pass through unchanged
            ("openai", "openai"),
            ("anthropic", "anthropic"),
            ("azure-openai", "azure-openai"),
            ("aws-bedrock", "aws-bedrock"),
            ("openai-responses", "openai-responses"),
            ("lmstudio", "lmstudio"),
            ("siliconflow", "siliconflow"),
            ("vertexai-claude", "vertexai-claude"),
            ("cerebras-openai", "cerebras-openai"),
            ("llama-cpp", "llama-cpp"),
            ("llama-openai", "llama-openai"),
            ("meta", "meta"),
            ("ibm", "ibm"),
            # Display names → canonical keys
            ("OpenAI", "openai"),
            ("Anthropic", "anthropic"),
            ("Azure", "azure-openai"),
            ("AwsBedrock", "aws-bedrock"),
            ("LMStudio", "lmstudio"),
            ("Siliconflow", "siliconflow"),
            ("CerebrasOpenAI", "cerebras-openai"),
            ("LlamaCpp", "llama-cpp"),
            ("LlamaOpenAI", "llama-openai"),
            ("Llama", "meta"),
            ("OpenResponses", "openai-responses"),
            ("VertexAI", "vertexai-claude"),
            ("IBM", "ibm"),
            ("WatsonX", "ibm"),
            # Case insensitivity
            ("OPENAI", "openai"),
            ("azure", "azure-openai"),
            ("AZURE", "azure-openai"),
            ("awsbedrock", "aws-bedrock"),
            ("AWSBEDROCK", "aws-bedrock"),
            # Whitespace stripping
            ("  openai  ", "openai"),
            ("  Azure  ", "azure-openai"),
        ],
    )
    def test_normalizes_correctly(self, input_val: str, expected: str) -> None:
        assert normalize_provider(input_val) == expected

    def test_unknown_provider_passes_through(self) -> None:
        """Unknown providers are lowercased and returned as-is."""
        assert normalize_provider("SomeNewProvider") == "somenewprovider"

    def test_already_canonical_is_idempotent(self) -> None:
        """Applying normalize_provider twice yields the same result."""
        for key in [
            "openai",
            "azure-openai",
            "aws-bedrock",
            "lmstudio",
            "cerebras-openai",
            "vertexai-claude",
        ]:
            assert normalize_provider(normalize_provider(key)) == key
