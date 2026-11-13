"""Tests for zero-argument Anthropic tool calls."""

from unittest.mock import MagicMock

from anthropic.types import ContentBlockStopEvent, Message, ToolUseBlock, Usage

from agno.models.anthropic.claude import Claude


def _empty_tool_use() -> ToolUseBlock:
    return ToolUseBlock(id="toolu_1", input={}, name="get_status", type="tool_use")


def test_non_streaming_empty_tool_input_is_serialized() -> None:
    response = Message(
        id="msg_1",
        content=[_empty_tool_use()],
        model="claude-sonnet-4-5-20250929",
        role="assistant",
        stop_reason="tool_use",
        stop_sequence=None,
        type="message",
        usage=Usage(input_tokens=10, output_tokens=5),
    )

    result = Claude()._parse_provider_response(response)

    assert result.tool_calls == [
        {
            "id": "toolu_1",
            "type": "function",
            "function": {"name": "get_status", "arguments": "{}"},
        }
    ]


def test_streaming_empty_tool_input_is_serialized() -> None:
    event = MagicMock(spec=ContentBlockStopEvent)
    event.content_block = _empty_tool_use()

    result = Claude()._parse_provider_response_delta(event)

    assert result.tool_calls == [
        {
            "id": "toolu_1",
            "type": "function",
            "function": {"name": "get_status", "arguments": "{}"},
        }
    ]
