"""Tests for CONTEXT_WINDOW_PATTERNS and ModelProviderError.classify() context window detection."""

import pytest

from agno.exceptions import ContextWindowExceededError, ModelProviderError

# =============================================================================
# Anthropic context window patterns
# =============================================================================


class TestAnthropicContextWindowPatterns:
    """Verify that Anthropic-specific error messages are classified as ContextWindowExceededError."""

    @pytest.mark.parametrize(
        "error_message",
        [
            "prompt is too long: 250000 tokens > 200000 maximum",
            "prompt is too long: 150000 tokens > 100000 maximum",
            "prompt is too long",
            "Prompt is too long: 300000 tokens > 200000 maximum",
            "prompt too long",
            "Prompt too long for this model",
        ],
        ids=[
            "anthropic_exact_format_250k",
            "anthropic_exact_format_150k",
            "anthropic_short_form",
            "anthropic_capitalized",
            "prompt_too_long_bare",
            "prompt_too_long_with_suffix",
        ],
    )
    def test_classify_anthropic_context_window_errors(self, error_message: str):
        """Anthropic context window errors should be classified as ContextWindowExceededError."""
        error = ModelProviderError(message=error_message, status_code=400)
        classified = ModelProviderError.classify(error)

        assert isinstance(classified, ContextWindowExceededError)
        assert classified.message == error_message
        assert classified.status_code == 400

    def test_classify_anthropic_error_preserves_model_info(self):
        """Classification should preserve model_name and model_id from the original error."""
        error = ModelProviderError(
            message="prompt is too long: 250000 tokens > 200000 maximum",
            status_code=400,
            model_name="claude-sonnet-4-20250514",
            model_id="anthropic/claude-sonnet-4-20250514",
        )
        classified = ModelProviderError.classify(error)

        assert isinstance(classified, ContextWindowExceededError)
        assert classified.model_name == "claude-sonnet-4-20250514"
        assert classified.model_id == "anthropic/claude-sonnet-4-20250514"


# =============================================================================
# Existing patterns (regression tests)
# =============================================================================


class TestExistingContextWindowPatterns:
    """Ensure existing CONTEXT_WINDOW_PATTERNS still work correctly."""

    @pytest.mark.parametrize(
        "error_message",
        [
            "context_length_exceeded",
            "maximum context length exceeded",
            "token limit reached",
            "too many tokens in the request",
            "payload too large",
            "content_too_large",
            "request too large for model",
            "input too long for processing",
            "exceeds the model's context window",
        ],
        ids=[
            "openai_error_code",
            "openai_verbose",
            "token_limit",
            "too_many_tokens",
            "payload_too_large",
            "anthropic_content_too_large",
            "request_too_large",
            "input_too_long",
            "exceeds_the_model",
        ],
    )
    def test_classify_existing_patterns(self, error_message: str):
        """Existing context window patterns should still be classified correctly."""
        error = ModelProviderError(message=error_message, status_code=400)
        classified = ModelProviderError.classify(error)

        assert isinstance(classified, ContextWindowExceededError)


# =============================================================================
# Negative cases
# =============================================================================


class TestNonContextWindowErrors:
    """Errors that should NOT be classified as ContextWindowExceededError."""

    @pytest.mark.parametrize(
        "error_message",
        [
            "invalid api key",
            "model not found",
            "internal server error",
            "connection timeout",
            "invalid request body",
        ],
        ids=[
            "auth_error",
            "model_not_found",
            "server_error",
            "timeout",
            "invalid_request",
        ],
    )
    def test_classify_non_context_window_errors(self, error_message: str):
        """Non-context-window errors should remain as ModelProviderError."""
        error = ModelProviderError(message=error_message, status_code=502)
        classified = ModelProviderError.classify(error)

        assert not isinstance(classified, ContextWindowExceededError)
        assert type(classified) is ModelProviderError

    def test_already_classified_context_window_error_unchanged(self):
        """An already-classified ContextWindowExceededError should be returned as-is."""
        error = ContextWindowExceededError(message="prompt is too long", status_code=400)
        classified = ModelProviderError.classify(error)

        assert classified is error
