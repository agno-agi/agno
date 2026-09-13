"""Assistant turns must replay to the Anthropic API exactly as the API produced them.

The API signs thinking blocks and verifies the thinking sequence of an assistant message on
replay. Rebuilding the turn from Message.reasoning_content / content / tool_calls loses block
multiplicity, order and signatures, and merging two assistant responses into one message
produces a thinking sequence no single response generated. Both are rejected with a 400.
"""

import pytest

pytest.importorskip("anthropic")

from anthropic.lib.streaming import MessageStopEvent as StreamingMessageStopEvent
from anthropic.types import Message as AnthropicMessage
from anthropic.types import RedactedThinkingBlock, TextBlock, ThinkingBlock, ToolUseBlock, Usage

from agno.models.anthropic.claude import Claude
from agno.models.message import Message
from agno.utils.models.claude import format_messages


def _block_types(blocks):
    return [b["type"] if isinstance(b, dict) else b.type for b in blocks]


def _signatures(blocks):
    return [b.get("signature") if isinstance(b, dict) else getattr(b, "signature", None) for b in blocks]


def _interleaved_response(stop_reason="tool_use") -> AnthropicMessage:
    """One response with two thinking blocks around a tool call: thinking, tool_use, thinking, text."""
    return AnthropicMessage(
        id="msg_1",
        model="claude-sonnet-4-5",
        role="assistant",
        type="message",
        stop_reason=stop_reason,
        usage=Usage(input_tokens=1, output_tokens=1),
        content=[
            ThinkingBlock(type="thinking", thinking="think A", signature="SIG-A"),
            ToolUseBlock(type="tool_use", id="tu_1", name="f", input={"x": 1}),
            ThinkingBlock(type="thinking", thinking="think B", signature="SIG-B"),
            TextBlock(type="text", text="done"),
        ],
    )


def _assistant_from(model_response) -> Message:
    return Message(
        role="assistant",
        content=model_response.content,
        reasoning_content=model_response.reasoning_content,
        redacted_reasoning_content=model_response.redacted_reasoning_content,
        provider_data=model_response.provider_data,
        tool_calls=model_response.tool_calls,
    )


def test_non_streaming_parse_stores_ordered_content_blocks():
    model = Claude(id="claude-sonnet-4-5", api_key="x")
    parsed = model._parse_provider_response(_interleaved_response())

    stored = parsed.provider_data["content_blocks"]
    assert _block_types(stored) == ["thinking", "tool_use", "thinking", "text"]
    assert [b.get("signature") for b in stored] == ["SIG-A", None, "SIG-B", None]
    # Convenience fields keep working as views.
    assert parsed.content == "done"
    assert parsed.tool_calls[0]["id"] == "tu_1"


def test_round_trip_replays_blocks_verbatim():
    model = Claude(id="claude-sonnet-4-5", api_key="x")
    assistant = _assistant_from(model._parse_provider_response(_interleaved_response()))

    api_messages, _ = format_messages([Message(role="user", content="hi"), assistant])

    blocks = api_messages[1]["content"]
    assert _block_types(blocks) == ["thinking", "tool_use", "thinking", "text"]
    assert _signatures(blocks) == ["SIG-A", None, "SIG-B", None]
    assert blocks[1]["input"] == {"x": 1}


def test_streaming_message_stop_stores_content_blocks():
    model = Claude(id="claude-sonnet-4-5", api_key="x")
    stop_event = StreamingMessageStopEvent(type="message_stop", message=_interleaved_response())

    delta = model._parse_provider_response_delta(stop_event)

    stored = delta.provider_data["content_blocks"]
    assert _block_types(stored) == ["thinking", "tool_use", "thinking", "text"]
    assert [b.get("signature") for b in stored] == ["SIG-A", None, "SIG-B", None]


def test_truncated_tool_use_without_tool_call_is_not_replayed():
    # stop_reason=max_tokens: the tool_use never ran, so no tool_result exists for it. Replaying
    # it would make the API reject the request for a tool_use without a tool_result.
    model = Claude(id="claude-sonnet-4-5", api_key="x")
    assistant = _assistant_from(model._parse_provider_response(_interleaved_response(stop_reason="max_tokens")))
    assert not assistant.tool_calls

    api_messages, _ = format_messages([Message(role="user", content="hi"), assistant])

    assert _block_types(api_messages[1]["content"]) == ["thinking", "thinking", "text"]


def test_replay_keeps_redacted_thinking_in_place():
    model = Claude(id="claude-sonnet-4-5", api_key="x")
    response = AnthropicMessage(
        id="msg_1",
        model="claude-sonnet-4-5",
        role="assistant",
        type="message",
        stop_reason="end_turn",
        usage=Usage(input_tokens=1, output_tokens=1),
        content=[
            RedactedThinkingBlock(type="redacted_thinking", data="ENC-1"),
            ThinkingBlock(type="thinking", thinking="visible", signature="SIG-1"),
            TextBlock(type="text", text="answer"),
        ],
    )
    assistant = _assistant_from(model._parse_provider_response(response))

    api_messages, _ = format_messages([Message(role="user", content="hi"), assistant])

    blocks = api_messages[1]["content"]
    assert _block_types(blocks) == ["redacted_thinking", "thinking", "text"]
    assert blocks[0]["data"] == "ENC-1"


def test_legacy_message_without_stored_blocks_still_rebuilds():
    # Sessions written before blocks were stored only have the convenience fields.
    assistant = Message(
        role="assistant",
        content="Here is the summary.",
        reasoning_content="The report has three sections...",
        provider_data={"signature": "SIG-2"},
    )

    api_messages, _ = format_messages([Message(role="user", content="hi"), assistant])

    blocks = api_messages[1]["content"]
    assert _block_types(blocks) == ["thinking", "text"]
    assert _signatures(blocks) == ["SIG-2", None]


def test_merged_assistant_messages_keep_only_the_later_thinking():
    # A thinking-only response truncated by max_tokens, followed by the continuation response
    # with no user or tool message in between (continue_run without input).
    truncated = Message(
        role="assistant",
        content=None,
        reasoning_content="I will read the report first...",
        provider_data={"signature": "SIG-1"},
    )
    continuation = Message(
        role="assistant",
        content="Here is the summary.",
        reasoning_content="The report has three sections...",
        provider_data={"signature": "SIG-2"},
    )

    api_messages, _ = format_messages([Message(role="user", content="hi"), truncated, continuation])

    assert [m["role"] for m in api_messages] == ["user", "assistant"]
    blocks = api_messages[1]["content"]
    assert _block_types(blocks) == ["thinking", "text"]
    assert _signatures(blocks) == ["SIG-2", None]


def test_merged_assistant_messages_with_stored_blocks_keep_only_the_later_thinking():
    truncated = Message(
        role="assistant",
        content=None,
        reasoning_content="partial",
        provider_data={
            "signature": "SIG-1",
            "content_blocks": [{"type": "thinking", "thinking": "partial", "signature": "SIG-1"}],
        },
    )
    continuation = Message(
        role="assistant",
        content="answer",
        reasoning_content="full",
        provider_data={
            "signature": "SIG-2",
            "content_blocks": [
                {"type": "redacted_thinking", "data": "ENC"},
                {"type": "thinking", "thinking": "full", "signature": "SIG-2"},
                {"type": "text", "text": "answer"},
            ],
        },
    )

    api_messages, _ = format_messages([Message(role="user", content="hi"), truncated, continuation])

    blocks = api_messages[1]["content"]
    assert _block_types(blocks) == ["redacted_thinking", "thinking", "text"]
    assert _signatures(blocks) == [None, "SIG-2", None]
    # Merging must not mutate the stored blocks of either message.
    assert len(truncated.provider_data["content_blocks"]) == 1
    assert len(continuation.provider_data["content_blocks"]) == 3


def test_merged_user_messages_are_untouched():
    first = Message(role="user", content="FIRST")
    second = Message(role="user", content="SECOND")

    api_messages, _ = format_messages([first, second])

    assert api_messages == [
        {"role": "user", "content": [{"type": "text", "text": "FIRST"}, {"type": "text", "text": "SECOND"}]}
    ]


def test_reasoning_without_signature_is_omitted_instead_of_raising():
    # Reasoning stored by another provider (or a partially stored response) has no signature the
    # API could verify. Previously this raised a pydantic ValidationError building ThinkingBlock.
    assistant = Message(
        role="assistant",
        content="x",
        reasoning_content="r",
        provider_data={"response_id": "resp_123"},
    )

    api_messages, _ = format_messages([Message(role="user", content="hi"), assistant])

    assert _block_types(api_messages[1]["content"]) == ["text"]


def test_stored_blocks_take_precedence_over_convenience_fields():
    # Two text blocks in the original response must replay as two blocks, not one concatenation.
    assistant = Message(
        role="assistant",
        content="onetwo",
        provider_data={
            "content_blocks": [
                {"type": "text", "text": "one"},
                {"type": "text", "text": "two"},
            ]
        },
    )

    api_messages, _ = format_messages([Message(role="user", content="hi"), assistant])

    assert api_messages[1]["content"] == [{"type": "text", "text": "one"}, {"type": "text", "text": "two"}]


def test_stored_blocks_that_filter_to_nothing_skip_the_assistant_message():
    # A max_tokens response holding only a tool_use that never ran: after filtering, nothing is
    # left to replay, and an assistant message with empty content must not be sent.
    assistant = Message(
        role="assistant",
        content=None,
        provider_data={"content_blocks": [{"type": "tool_use", "id": "tu_1", "name": "f", "input": {}}]},
    )

    api_messages, _ = format_messages([Message(role="user", content="hi"), assistant])

    assert [m["role"] for m in api_messages] == ["user"]


def test_streamed_omitted_display_thinking_round_trips():
    # With display omitted, a thinking block streams no thinking_delta at all: only the signature
    # arrives. reasoning_content stays empty on the message, so the legacy rebuild would drop the
    # block, but the stored blocks still carry it and it must accompany the tool_use it belongs to.
    model = Claude(id="claude-sonnet-4-5", api_key="x")
    response = AnthropicMessage(
        id="msg_1",
        model="claude-sonnet-4-5",
        role="assistant",
        type="message",
        stop_reason="tool_use",
        usage=Usage(input_tokens=1, output_tokens=1),
        content=[
            ThinkingBlock(type="thinking", thinking="", signature="SIG-ONLY"),
            ToolUseBlock(type="tool_use", id="tu_1", name="f", input={}),
        ],
    )
    delta = model._parse_provider_response_delta(StreamingMessageStopEvent(type="message_stop", message=response))
    assistant = Message(
        role="assistant",
        content=None,
        reasoning_content=None,
        provider_data=delta.provider_data,
        tool_calls=[{"id": "tu_1", "type": "function", "function": {"name": "f", "arguments": "{}"}}],
    )

    api_messages, _ = format_messages([Message(role="user", content="hi"), assistant])

    blocks = api_messages[1]["content"]
    assert _block_types(blocks) == ["thinking", "tool_use"]
    assert blocks[0]["thinking"] == ""
    assert blocks[0]["signature"] == "SIG-ONLY"


def test_stored_blocks_survive_message_serialization():
    # Session storage goes through Message.to_dict / from_dict; the blocks must come back intact.
    model = Claude(id="claude-sonnet-4-5", api_key="x")
    assistant = _assistant_from(model._parse_provider_response(_interleaved_response()))

    restored = Message.from_dict(assistant.to_dict())

    api_messages, _ = format_messages([Message(role="user", content="hi"), restored])
    assert _signatures(api_messages[1]["content"]) == ["SIG-A", None, "SIG-B", None]


def test_replayed_blocks_do_not_alias_stored_blocks():
    assistant = Message(
        role="assistant",
        content="x",
        provider_data={"content_blocks": [{"type": "text", "text": "x"}]},
    )

    api_messages, _ = format_messages([Message(role="user", content="hi"), assistant])
    api_messages[1]["content"][0]["cache_control"] = {"type": "ephemeral"}

    assert "cache_control" not in assistant.provider_data["content_blocks"][0]


def test_legacy_redacted_block_type_is_normalized_when_stored():
    # The parser accepts the legacy redacted_reasoning_content spelling from rehydrated events.
    # The API only accepts redacted_thinking, so the stored list must carry the canonical type.
    from agno.utils.models.claude import serialize_content_blocks

    stored = serialize_content_blocks(
        [
            {"type": "redacted_reasoning_content", "data": "ENC-LEGACY"},
            RedactedThinkingBlock(type="redacted_thinking", data="ENC-SDK"),
            {"type": "text", "text": "answer"},
        ]
    )

    assert stored == [
        {"type": "redacted_thinking", "data": "ENC-LEGACY"},
        {"type": "redacted_thinking", "data": "ENC-SDK"},
        {"type": "text", "text": "answer"},
    ]


def test_legacy_redacted_block_type_in_stored_blocks_replays_as_redacted_thinking():
    # Sessions that stored the legacy spelling before normalization must still replay a valid type.
    assistant = Message(
        role="assistant",
        content="answer",
        provider_data={
            "content_blocks": [
                {"type": "redacted_reasoning_content", "data": "ENC-LEGACY"},
                {"type": "text", "text": "answer"},
            ]
        },
    )

    api_messages, _ = format_messages([Message(role="user", content="hi"), assistant])

    blocks = api_messages[1]["content"]
    assert _block_types(blocks) == ["redacted_thinking", "text"]
    assert blocks[0]["data"] == "ENC-LEGACY"
    # The stored session data is left as it was written.
    assert assistant.provider_data["content_blocks"][0]["type"] == "redacted_reasoning_content"


def test_merged_assistant_messages_keep_earlier_text_and_later_thinking():
    # A response truncated after thinking and partial text, followed by the continuation response.
    # Only the later response's thinking survives; the earlier text is kept for context. The API
    # verifies the thinking sequence, not its position relative to text: this exact shape, followed
    # by a user turn, was accepted live by claude-sonnet-4-5.
    truncated = Message(
        role="assistant",
        content="The bicycle began",
        reasoning_content="brief plan",
        provider_data={
            "signature": "SIG-1",
            "content_blocks": [
                {"type": "thinking", "thinking": "brief plan", "signature": "SIG-1"},
                {"type": "text", "text": "The bicycle began"},
            ],
        },
    )
    continuation = Message(
        role="assistant",
        content="in the 1810s.",
        reasoning_content="continue the essay",
        provider_data={
            "signature": "SIG-2",
            "content_blocks": [
                {"type": "thinking", "thinking": "continue the essay", "signature": "SIG-2"},
                {"type": "text", "text": "in the 1810s."},
            ],
        },
    )

    api_messages, _ = format_messages(
        [Message(role="user", content="hi"), truncated, continuation, Message(role="user", content="ok?")]
    )

    blocks = api_messages[1]["content"]
    assert _block_types(blocks) == ["text", "thinking", "text"]
    assert _signatures(blocks) == [None, "SIG-2", None]
