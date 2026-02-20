import os

import pytest

pytest.importorskip("anthropic")

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-for-testing")

from anthropic.types import MessageStartEvent, MessageStopEvent, Usage

from agno.models.anthropic.claude import Claude
from agno.models.base import MessageData
from agno.models.metrics import Metrics
from agno.models.response import ModelResponse


def test_message_start_event_has_usage():
    """MessageStartEvent carries .message.usage with input_tokens."""
    assert "message" in MessageStartEvent.model_fields


def test_raw_message_stop_event_lacks_message():
    """Raw MessageStopEvent does not have .message field."""
    assert "message" not in MessageStopEvent.model_fields


def test_sdk_builds_stop_event_with_message_snapshot():
    """SDK's build_events injects message_snapshot into the stop event."""
    from anthropic.lib.streaming._messages import build_events
    from anthropic.types import Message, RawMessageStopEvent

    msg = Message(
        id="msg_test",
        type="message",
        role="assistant",
        content=[],
        model="claude-sonnet-4-5-20250929",
        stop_reason="end_turn",
        stop_sequence=None,
        usage=Usage(
            input_tokens=100,
            output_tokens=50,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=0,
        ),
    )

    raw_stop = RawMessageStopEvent(type="message_stop")
    events = build_events(event=raw_stop, message_snapshot=msg)

    assert len(events) == 1
    assert hasattr(events[0], "message")
    assert events[0].message.usage.input_tokens == 100
    assert events[0].message.usage.output_tokens == 50


def test_hasattr_gate_passes_for_message_start():
    """The hasattr check in claude.py passes for MessageStartEvent."""
    from anthropic.types import Message

    start = MessageStartEvent(
        type="message_start",
        message=Message(
            id="msg_test",
            type="message",
            role="assistant",
            content=[],
            model="claude-sonnet-4-5-20250929",
            stop_reason=None,
            stop_sequence=None,
            usage=Usage(
                input_tokens=100,
                output_tokens=0,
                cache_creation_input_tokens=0,
                cache_read_input_tokens=0,
            ),
        ),
    )

    assert hasattr(start, "message")
    assert hasattr(start.message, "usage")
    assert start.message.usage.input_tokens == 100


def test_cumulative_flag_prevents_double_count():
    """Two usage emissions produce correct final metrics, not 2X input_tokens."""
    model = Claude(id="claude-sonnet-4-5-20250929")
    assert model.is_cumulative_usage is True

    stream_data = MessageData()

    # Emission 1: MessageStartEvent (input_tokens=100, output_tokens=0)
    list(
        model._populate_stream_data(
            stream_data,
            ModelResponse(
                response_usage=Metrics(input_tokens=100, output_tokens=0),
            ),
        )
    )

    assert stream_data.response_metrics is not None
    assert stream_data.response_metrics.input_tokens == 100
    assert stream_data.response_metrics.output_tokens == 0

    # Emission 2: MessageStopEvent (input_tokens=100, output_tokens=50)
    list(
        model._populate_stream_data(
            stream_data,
            ModelResponse(
                response_usage=Metrics(input_tokens=100, output_tokens=50),
            ),
        )
    )

    assert stream_data.response_metrics.input_tokens == 100
    assert stream_data.response_metrics.output_tokens == 50


def test_cumulative_assignment_does_not_alias():
    """The cumulative path creates an independent copy, not an alias."""
    model = Claude(id="claude-sonnet-4-5-20250929")
    stream_data = MessageData()

    original_metrics = Metrics(input_tokens=100, output_tokens=50)
    delta = ModelResponse(response_usage=original_metrics)
    list(model._populate_stream_data(stream_data, delta))

    # Mutating the original should NOT affect stream_data
    original_metrics.input_tokens = 999

    assert stream_data.response_metrics.input_tokens == 100
