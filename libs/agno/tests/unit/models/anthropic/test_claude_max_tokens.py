"""
Regression test for Claude returning empty response when stop_reason is "max_tokens" (#6179).

When Claude hits the max_tokens limit, the stop_reason is "max_tokens" but agno
was returning an empty response instead of the partial content that was generated.
The fix ensures:
1. Partial content is still returned when stop_reason is "max_tokens"
2. A warning log message is emitted when truncation occurs
3. Both sync (non-streaming) and streaming response paths are covered
"""

from unittest.mock import MagicMock, patch

from anthropic.types import (
    ContentBlockDeltaEvent,
    MessageStopEvent,
    TextBlock,
    Usage,
)

from agno.models.anthropic.claude import Claude


def _make_usage(input_tokens: int = 100, output_tokens: int = 50) -> Usage:
    """Create an Anthropic Usage object."""
    return Usage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
        server_tool_use=None,
    )


def _make_text_block(text: str) -> TextBlock:
    """Create an Anthropic TextBlock."""
    return TextBlock(type="text", text=text, citations=None)


def _make_anthropic_message(
    content_text: str,
    stop_reason: str = "end_turn",
    input_tokens: int = 100,
    output_tokens: int = 50,
):
    """Create a mock AnthropicMessage with the given content and stop_reason."""
    msg = MagicMock()
    msg.role = "assistant"
    msg.stop_reason = stop_reason
    msg.content = [_make_text_block(content_text)]
    msg.usage = _make_usage(input_tokens, output_tokens)
    # Ensure no context_management attribute to avoid attribute checks
    msg.context_management = None
    return msg


class TestMaxTokensNonStreaming:
    """Tests for the non-streaming (invoke) response path."""

    def test_max_tokens_returns_partial_content(self):
        """When stop_reason is 'max_tokens', partial content should still be returned."""
        claude = Claude(id="claude-sonnet-4-5-20250929", max_tokens=100)
        partial_text = "This is a partial response that was cut off because"
        response = _make_anthropic_message(partial_text, stop_reason="max_tokens")

        model_response = claude._parse_provider_response(response)

        assert model_response.content == partial_text
        assert model_response.content is not None
        assert len(model_response.content) > 0

    def test_max_tokens_content_not_empty(self):
        """Verify that content is not empty or None when stop_reason is 'max_tokens'."""
        claude = Claude(id="claude-sonnet-4-5-20250929", max_tokens=50)
        response = _make_anthropic_message("Hello", stop_reason="max_tokens")

        model_response = claude._parse_provider_response(response)

        assert model_response.content is not None
        assert model_response.content != ""
        assert model_response.content == "Hello"

    def test_max_tokens_logs_warning(self):
        """When stop_reason is 'max_tokens', a warning should be logged."""
        claude = Claude(id="claude-sonnet-4-5-20250929", max_tokens=100)
        response = _make_anthropic_message("Partial content", stop_reason="max_tokens")

        with patch("agno.models.anthropic.claude.log_warning") as mock_warning:
            claude._parse_provider_response(response)

            mock_warning.assert_called_once()
            warning_msg = mock_warning.call_args[0][0]
            assert "truncated" in warning_msg.lower()
            assert "max_tokens" in warning_msg

    def test_end_turn_no_warning(self):
        """When stop_reason is 'end_turn', no truncation warning should be logged."""
        claude = Claude(id="claude-sonnet-4-5-20250929", max_tokens=8192)
        response = _make_anthropic_message("Complete response", stop_reason="end_turn")

        with patch("agno.models.anthropic.claude.log_warning") as mock_warning:
            claude._parse_provider_response(response)

            mock_warning.assert_not_called()

    def test_end_turn_returns_full_content(self):
        """Normal end_turn responses should still work correctly."""
        claude = Claude(id="claude-sonnet-4-5-20250929", max_tokens=8192)
        full_text = "This is a complete response from Claude."
        response = _make_anthropic_message(full_text, stop_reason="end_turn")

        model_response = claude._parse_provider_response(response)

        assert model_response.content == full_text

    def test_max_tokens_preserves_usage_metrics(self):
        """Usage metrics should be present even when stop_reason is 'max_tokens'."""
        claude = Claude(id="claude-sonnet-4-5-20250929", max_tokens=100)
        response = _make_anthropic_message(
            "Truncated text",
            stop_reason="max_tokens",
            input_tokens=500,
            output_tokens=100,
        )

        model_response = claude._parse_provider_response(response)

        assert model_response.response_usage is not None
        assert model_response.response_usage.input_tokens == 500
        assert model_response.response_usage.output_tokens == 100

    def test_max_tokens_with_multiple_content_blocks(self):
        """When there are multiple text blocks and stop_reason is 'max_tokens', all text should be concatenated."""
        claude = Claude(id="claude-sonnet-4-5-20250929", max_tokens=100)

        msg = MagicMock()
        msg.role = "assistant"
        msg.stop_reason = "max_tokens"
        msg.content = [
            _make_text_block("First part. "),
            _make_text_block("Second part that was cut"),
        ]
        msg.usage = _make_usage()
        msg.context_management = None

        model_response = claude._parse_provider_response(msg)

        assert model_response.content == "First part. Second part that was cut"

    def test_max_tokens_with_empty_content_blocks(self):
        """When stop_reason is 'max_tokens' but content is empty (edge case), content should be None."""
        claude = Claude(id="claude-sonnet-4-5-20250929", max_tokens=100)

        msg = MagicMock()
        msg.role = "assistant"
        msg.stop_reason = "max_tokens"
        msg.content = []
        msg.usage = _make_usage()
        msg.context_management = None

        model_response = claude._parse_provider_response(msg)

        # With no content blocks, content should remain None
        assert model_response.content is None


class TestMaxTokensStreaming:
    """Tests for the streaming (invoke_stream) response path via _parse_provider_response_delta."""

    def test_streaming_max_tokens_logs_warning(self):
        """MessageStopEvent with stop_reason 'max_tokens' should log a warning."""
        claude = Claude(id="claude-sonnet-4-5-20250929", max_tokens=100)

        stop_event = MagicMock(spec=MessageStopEvent)
        stop_event.message = MagicMock()
        stop_event.message.stop_reason = "max_tokens"
        stop_event.message.content = [_make_text_block("Partial streaming content")]
        stop_event.message.usage = _make_usage()
        stop_event.message.context_management = None

        with patch("agno.models.anthropic.claude.log_warning") as mock_warning:
            claude._parse_provider_response_delta(stop_event)

            mock_warning.assert_called_once()
            warning_msg = mock_warning.call_args[0][0]
            assert "truncated" in warning_msg.lower()
            assert "max_tokens" in warning_msg

    def test_streaming_end_turn_no_warning(self):
        """MessageStopEvent with stop_reason 'end_turn' should NOT log a truncation warning."""
        claude = Claude(id="claude-sonnet-4-5-20250929", max_tokens=8192)

        stop_event = MagicMock(spec=MessageStopEvent)
        stop_event.message = MagicMock()
        stop_event.message.stop_reason = "end_turn"
        stop_event.message.content = [_make_text_block("Complete streaming content")]
        stop_event.message.usage = _make_usage()
        stop_event.message.context_management = None

        with patch("agno.models.anthropic.claude.log_warning") as mock_warning:
            claude._parse_provider_response_delta(stop_event)

            mock_warning.assert_not_called()

    def test_streaming_content_delta_still_works(self):
        """ContentBlockDeltaEvent with text_delta should still correctly emit content."""
        claude = Claude(id="claude-sonnet-4-5-20250929", max_tokens=100)

        delta_event = MagicMock(spec=ContentBlockDeltaEvent)
        delta_event.delta = MagicMock()
        delta_event.delta.type = "text_delta"
        delta_event.delta.text = "Some streaming text"

        result = claude._parse_provider_response_delta(delta_event)

        assert result.content == "Some streaming text"

    def test_streaming_stop_event_preserves_usage(self):
        """MessageStopEvent should still emit response_usage even with max_tokens."""
        claude = Claude(id="claude-sonnet-4-5-20250929", max_tokens=100)

        stop_event = MagicMock(spec=MessageStopEvent)
        stop_event.message = MagicMock()
        stop_event.message.stop_reason = "max_tokens"
        stop_event.message.content = [_make_text_block("Partial")]
        stop_event.message.usage = _make_usage(input_tokens=200, output_tokens=100)
        stop_event.message.context_management = None

        result = claude._parse_provider_response_delta(stop_event)

        assert result.response_usage is not None
        assert result.response_usage.input_tokens == 200
        assert result.response_usage.output_tokens == 100


class TestMaxTokensWarningMessage:
    """Tests to verify the warning message content is useful."""

    def test_warning_includes_max_tokens_value(self):
        """The warning should include the configured max_tokens value."""
        claude = Claude(id="claude-sonnet-4-5-20250929", max_tokens=256)
        response = _make_anthropic_message("Truncated", stop_reason="max_tokens")

        with patch("agno.models.anthropic.claude.log_warning") as mock_warning:
            claude._parse_provider_response(response)

            mock_warning.assert_called_once()
            warning_msg = mock_warning.call_args[0][0]
            assert "256" in warning_msg, f"Expected '256' in warning message, got: {warning_msg}"

    def test_warning_suggests_increasing_max_tokens(self):
        """The warning should suggest increasing max_tokens."""
        claude = Claude(id="claude-sonnet-4-5-20250929", max_tokens=100)
        response = _make_anthropic_message("Truncated", stop_reason="max_tokens")

        with patch("agno.models.anthropic.claude.log_warning") as mock_warning:
            claude._parse_provider_response(response)

            mock_warning.assert_called_once()
            warning_msg = mock_warning.call_args[0][0]
            assert "increas" in warning_msg.lower(), f"Expected suggestion to increase max_tokens, got: {warning_msg}"
