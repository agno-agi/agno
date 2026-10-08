"""Claude formatter must remap foreign tool call IDs before sending.

Anthropic rejects any tool_use.id outside `^[a-zA-Z0-9_-]+$` with a
non-retryable 400 (including count_tokens). History replayed from another
provider (e.g. an OpenAI-compatible host returning "query:2") must be remapped
to the toolu_ prefix, and the matching tool_result.tool_use_id must follow.
"""

import pytest

pytest.importorskip("anthropic")

import re

from agno.models.message import Message
from agno.utils.models.claude import format_messages

ANTHROPIC_ID_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def _history_with_foreign_id():
    return [
        Message(role="user", content="What's the weather in Paris?"),
        Message(
            role="assistant",
            content="",
            tool_calls=[
                {
                    "id": "query:2",
                    "type": "function",
                    "function": {"name": "get_weather", "arguments": '{"city": "Paris"}'},
                }
            ],
        ),
        Message(role="tool", tool_call_id="query:2", tool_name="get_weather", content="Sunny, 22C"),
        Message(role="user", content="Summarize that in one line."),
    ]


def test_foreign_tool_call_id_is_remapped_to_valid_anthropic_id():
    chat_messages, _ = format_messages(_history_with_foreign_id())

    tool_use_ids = []
    tool_result_ids = []
    for msg in chat_messages:
        for block in msg["content"]:
            btype = block.get("type") if isinstance(block, dict) else getattr(block, "type", None)
            if btype == "tool_use":
                tool_use_ids.append(block["id"] if isinstance(block, dict) else block.id)
            elif btype == "tool_result":
                tool_result_ids.append(block["tool_use_id"] if isinstance(block, dict) else block.tool_use_id)

    assert len(tool_use_ids) == 1
    assert len(tool_result_ids) == 1
    # Every emitted id must satisfy Anthropic's constraint.
    for i in tool_use_ids + tool_result_ids:
        assert ANTHROPIC_ID_RE.match(i), f"invalid id {i!r}"
    # The tool result must reference the remapped id, not the foreign one.
    assert tool_result_ids == tool_use_ids
    assert tool_use_ids[0].startswith("toolu_")


def test_native_anthropic_ids_are_untouched():
    chat_messages, _ = format_messages(
        [
            Message(role="user", content="What's the weather?"),
            Message(
                role="assistant",
                content="",
                tool_calls=[
                    {
                        "id": "toolu_01abc",
                        "type": "function",
                        "function": {"name": "get_weather", "arguments": '{"city": "Paris"}'},
                    }
                ],
            ),
            Message(role="tool", tool_call_id="toolu_01abc", tool_name="get_weather", content="Sunny"),
            Message(role="user", content="Thanks"),
        ]
    )

    ids = []
    for msg in chat_messages:
        for block in msg["content"]:
            btype = block.get("type") if isinstance(block, dict) else getattr(block, "type", None)
            if btype == "tool_use":
                ids.append(block["id"] if isinstance(block, dict) else block.id)
    assert ids == ["toolu_01abc"]
