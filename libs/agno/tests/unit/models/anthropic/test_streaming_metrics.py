"""
Regression test for Anthropic streaming metrics double-counting bug (#6537).

Both MessageStartEvent and MessageStopEvent carry .message.usage with full
token counts. The old code extracted usage from both, causing input_tokens
to be summed twice via the += accumulation in base.py._populate_stream_data.

The fix restricts usage extraction to MessageStopEvent only.
"""

from unittest.mock import MagicMock

from anthropic.types import MessageStartEvent, MessageStopEvent, Usage

from agno.models.anthropic.claude import Claude


def _make_usage(input_tokens: int, output_tokens: int) -> Usage:
    """Create an Anthropic Usage object."""
    return Usage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
        server_tool_use=None,
    )


def _make_message_event(event_cls, input_tokens: int, output_tokens: int):
    """Create a mock MessageStartEvent or MessageStopEvent with usage."""
    event = MagicMock(spec=event_cls)
    event.message = MagicMock()
    event.message.usage = _make_usage(input_tokens, output_tokens)
    event.message.content = []
    return event


def test_message_start_event_does_not_emit_usage():
    """MessageStartEvent should NOT produce response_usage (would cause double-counting)."""
    claude = Claude(id="claude-sonnet-4-5-20250929")
    start_event = _make_message_event(MessageStartEvent, input_tokens=50000, output_tokens=0)

    result = claude._parse_provider_response_delta(start_event)

    assert result.response_usage is None, (
        "MessageStartEvent should not emit response_usage; "
        "only MessageStopEvent should, to prevent double-counting input_tokens"
    )


def test_message_stop_event_emits_usage():
    """MessageStopEvent SHOULD produce response_usage with correct token counts."""
    claude = Claude(id="claude-sonnet-4-5-20250929")
    stop_event = _make_message_event(MessageStopEvent, input_tokens=50000, output_tokens=1200)

    result = claude._parse_provider_response_delta(stop_event)

    assert result.response_usage is not None, "MessageStopEvent should emit response_usage"
    assert result.response_usage.input_tokens == 50000
    assert result.response_usage.output_tokens == 1200
    assert result.response_usage.total_tokens == 51200


def test_streaming_metrics_not_doubled():
    """Simulate a full streaming sequence and verify input_tokens is NOT doubled."""
    claude = Claude(id="claude-sonnet-4-5-20250929")

    start_event = _make_message_event(MessageStartEvent, input_tokens=50000, output_tokens=0)
    stop_event = _make_message_event(MessageStopEvent, input_tokens=50000, output_tokens=1200)

    start_result = claude._parse_provider_response_delta(start_event)
    stop_result = claude._parse_provider_response_delta(stop_event)

    # Only stop_result should have usage
    assert start_result.response_usage is None
    assert stop_result.response_usage is not None

    # If both emitted usage, accumulation via += would give 100000 input_tokens
    # With the fix, only 50000 is reported
    assert stop_result.response_usage.input_tokens == 50000
