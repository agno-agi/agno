"""strip_reasoning removes earlier runs' reasoning from history copies, for every provider shape.

Providers bind replayed reasoning to the request it came from (Anthropic verifies signed thinking
blocks against the system prompt and earlier messages). When a history turn's reasoning no longer
matches, the whole request is rejected. Earlier turns' reasoning is optional, so history can be
replayed as text and tool calls only.
"""

import pytest

from agno.models.message import Message
from agno.utils.message import copy_history_message, strip_reasoning


def _types(blocks):
    return [b["type"] if isinstance(b, dict) else b.type for b in blocks]


def _anthropic_assistant() -> Message:
    return Message(
        role="assistant",
        content="done",
        reasoning_content="think A",
        provider_data={
            "signature": "SIG-A",
            "content_blocks": [
                {"type": "thinking", "thinking": "think A", "signature": "SIG-A"},
                {"type": "tool_use", "id": "tu_1", "name": "f", "input": {"x": 1}},
                {"type": "redacted_thinking", "data": "REDACTED"},
                {"type": "text", "text": "done"},
            ],
        },
        tool_calls=[{"id": "tu_1", "type": "function", "function": {"name": "f", "arguments": '{"x": 1}'}}],
    )


def test_anthropic_thinking_blocks_and_signature_are_removed():
    history = [Message(role="user", content="hi"), copy_history_message(_anthropic_assistant())]

    strip_reasoning(history)

    assistant = history[1]
    assert assistant.reasoning_content is None
    assert "signature" not in assistant.provider_data
    assert _types(assistant.provider_data["content_blocks"]) == ["tool_use", "text"]
    assert assistant.tool_calls[0]["id"] == "tu_1"
    assert assistant.content == "done"


def test_anthropic_request_has_no_thinking_after_strip():
    pytest.importorskip("anthropic")
    from agno.utils.models.claude import format_messages

    history = [
        Message(role="user", content="hi"),
        copy_history_message(_anthropic_assistant()),
        Message(role="tool", tool_call_id="tu_1", tool_name="f", content="ok"),
    ]
    strip_reasoning(history)

    api_messages, _ = format_messages([*history, Message(role="user", content="again")])

    assert _types(api_messages[1]["content"]) == ["tool_use", "text"]


def test_thinking_only_turn_falls_back_to_plain_fields():
    assistant = Message(
        role="assistant",
        content="hello",
        reasoning_content="t",
        provider_data={"content_blocks": [{"type": "thinking", "thinking": "t", "signature": "S"}]},
    )
    history = [copy_history_message(assistant)]

    strip_reasoning(history)

    assert history[0].provider_data is None
    assert history[0].content == "hello"


def test_gemini_thought_signatures_are_removed():
    assistant = Message(
        role="assistant",
        content="text",
        provider_data={"thought_signature": "U0lH"},
        tool_calls=[
            {
                "id": "c1",
                "type": "function",
                "function": {"name": "f", "arguments": "{}"},
                "thought_signature": "U0lH",
            }
        ],
    )
    history = [copy_history_message(assistant)]

    strip_reasoning(history)

    assert history[0].provider_data is None
    assert history[0].tool_calls == [{"id": "c1", "type": "function", "function": {"name": "f", "arguments": "{}"}}]


def test_openai_reasoning_item_is_removed_and_other_provider_data_kept():
    assistant = Message(
        role="assistant",
        content="text",
        reasoning_content="summary",
        provider_data={"reasoning_output": {"type": "reasoning", "id": "rs_1"}, "response_id": "resp_1"},
    )
    history = [copy_history_message(assistant)]

    strip_reasoning(history)

    assert history[0].reasoning_content is None
    assert history[0].provider_data == {"response_id": "resp_1"}


def test_stored_session_messages_are_not_mutated():
    """History copies are shallow: the strip must rebind, never edit shared dicts and lists."""
    stored = _anthropic_assistant()
    stored_gemini = Message(
        role="assistant",
        content="x",
        tool_calls=[{"id": "c1", "function": {"name": "f", "arguments": "{}"}, "thought_signature": "U0lH"}],
    )
    history = [copy_history_message(stored), copy_history_message(stored_gemini)]

    strip_reasoning(history)

    assert stored.reasoning_content == "think A"
    assert stored.provider_data["signature"] == "SIG-A"
    assert len(stored.provider_data["content_blocks"]) == 4
    assert stored_gemini.tool_calls[0]["thought_signature"] == "U0lH"


def test_other_roles_and_plain_turns_are_left_alone():
    user = Message(role="user", content="hi", provider_data={"signature": "keep"})
    tool = Message(role="tool", tool_call_id="c1", content="ok")
    plain = Message(role="assistant", content="hello", provider_data={"response_id": "resp_1"})
    history = [user, tool, plain]

    strip_reasoning(history)

    assert user.provider_data == {"signature": "keep"}
    assert tool.content == "ok"
    assert plain.provider_data == {"response_id": "resp_1"}
