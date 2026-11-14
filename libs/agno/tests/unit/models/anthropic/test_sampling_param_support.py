"""Which model IDs still accept temperature, top_p and top_k.

Claude 4.7 deprecated the sampling parameters, and every model released since answers a
request carrying a non-default value with a 400 -- so the capability has to be read off
the model ID before the parameter is put on the request. The set of models that accept
them is closed and cannot grow, which is why an unrecognised ID is treated as rejecting
them: guessing the other way sends a parameter that fails the whole run.
"""

import pytest

from agno.utils.models.claude import supports_sampling_params


class TestSupportsSamplingParams:
    @pytest.mark.parametrize(
        "model_id",
        [
            # Claude 3 family
            "claude-3-haiku-20240307",
            "claude-3-5-haiku-20241022",
            "claude-3-5-sonnet-20241022",
            # Claude 4.0 through 4.6 -- the last releases that predate the deprecation
            "claude-sonnet-4-20250514",
            "claude-sonnet-4-5-20250929",
            "claude-sonnet-4-5",
            "claude-sonnet-4-6",
            "claude-opus-4-5-20251101",
            "claude-opus-4-6",
            "claude-haiku-4-5-20251001",
            # Family aliases, which point at a version in that range
            "claude-sonnet-4",
            "claude-opus-4",
            "claude-haiku-4",
        ],
    )
    def test_models_that_accept_them(self, model_id: str):
        assert supports_sampling_params(model_id) is True, f"'{model_id}' accepts the sampling parameters"

    @pytest.mark.parametrize(
        "model_id",
        [
            # Claude 4.7 onwards
            "claude-opus-4-7",
            "claude-opus-4-8",
            "claude-sonnet-5",
            "claude-sonnet-5-5",
            "claude-opus-5-5",
            "claude-haiku-5-5",
            "claude-fable-5",
            "claude-mythos-5",
            # An unreleased model is assumed to reject them, not assumed to work
            "claude-sonnet-9-9",
            "claude-something-entirely-new",
        ],
    )
    def test_models_that_reject_them(self, model_id: str):
        assert supports_sampling_params(model_id) is False, f"'{model_id}' rejects the sampling parameters"

    @pytest.mark.parametrize(
        "model_id,expected",
        [
            # Bedrock
            ("us.anthropic.claude-sonnet-4-6-v1:0", True),
            ("global.anthropic.claude-sonnet-4-5-20250929-v1:0", True),
            ("us.anthropic.claude-sonnet-5-5-v1:0", False),
            # Vertex AI
            ("claude-sonnet-4@20250514", True),
            ("claude-sonnet-4-6@20251124", True),
            ("claude-sonnet-5-5@20260928", False),
            # LiteLLM
            ("anthropic/claude-sonnet-4-6", True),
            ("anthropic/claude-sonnet-5-5", False),
        ],
    )
    def test_provider_specific_id_formats(self, model_id: str, expected: bool):
        assert supports_sampling_params(model_id) is expected

    @pytest.mark.parametrize("model_id", ["gpt-5", "gemini-2.5-pro", "my-azure-deployment"])
    def test_non_claude_ids_are_passed_through(self, model_id: str):
        """Only Claude deprecated these; an unrelated model's parameters are left alone."""
        assert supports_sampling_params(model_id) is True
