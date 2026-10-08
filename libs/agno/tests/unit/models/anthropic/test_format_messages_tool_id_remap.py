"""Claude ``format_messages`` must remap foreign tool call IDs (e.g. ``query:2``
emitted by other providers) into a format Anthropic accepts
(``^[a-zA-Z0-9_-]+$``), and keep the assistant ``tool_use`` id and the matching
``tool_result`` id in sync.

Regression test for agno-agi/agno#10887.
"""

import pytest

pytest.importorskip("anthropic")

from agno.models.message import Message
from agno.utils.models.claude import format_messages


def _collect_block_ids(chat_messages):
    """Return (tool_use_ids, tool_result_ids) from a formatted message list."""
    tool_use_ids = []
    tool_result_ids = []
    for msg in chat_messages:
        for block in msg["content"]:
            if isinstance(block, dict):
                btype = block.get("type")
                if btype == "tool_use":
                    tool_use_ids.append(block.get("id"))
                elif btype == "tool_result":
                    tool_result_ids.append(block.get("tool_use_id"))
            else:
                btype = getattr(block, "type", None)
                if btype == "tool_use":
                    tool_use_ids.append(block.id)
                elif btype == "tool_result":
                    tool_result_ids.append(block.tool_use_id)
    return tool_use_ids, tool_result_ids


def test_foreign_tool_call_id_is_remapped_for_claude():
    messages = [
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

    chat_messages, _ = format_messages(messages)

    tool_use_ids, tool_result_ids = _collect_block_ids(chat_messages)

    assert tool_use_ids, "expected a tool_use block"
    assert tool_result_ids, "expected a tool_result block"
    # Foreign IDs must be remapped to a toolu_ id Anthropic accepts.
    assert all(tid.startswith("toolu_") for tid in tool_use_ids), tool_use_ids
    assert all(rid.startswith("toolu_") for rid in tool_result_ids), tool_result_ids
    # The assistant tool_use id and the tool_result tool_use_id must match.
    assert tool_use_ids[0] == tool_result_ids[0]


def test_original_messages_are_not_mutated():
    assistant = Message(
        role="assistant",
        content="",
        tool_calls=[
            {
                "id": "query:2",
                "type": "function",
                "function": {"name": "get_weather", "arguments": '{"city": "Paris"}'},
            }
        ],
    )
    tool = Message(role="tool", tool_call_id="query:2", tool_name="get_weather", content="Sunny, 22C")

    format_messages([assistant, tool])

    # reformat_tool_call_ids returns deep copies; originals must be untouched.
    assert assistant.tool_calls[0]["id"] == "query:2"
    assert tool.tool_call_id == "query:2"


def test_already_valid_tool_call_id_stays_consistent():
    # An ID that already passes Anthropic's rule must not be dropped or desynced.
    messages = [
        Message(
            role="assistant",
            content="",
            tool_calls=[
                {
                    "id": "call_abc123",
                    "type": "function",
                    "function": {"name": "get_weather", "arguments": '{"city": "Paris"}'},
                }
            ],
        ),
        Message(role="tool", tool_call_id="call_abc123", tool_name="get_weather", content="Sunny, 22C"),
    ]

    chat_messages, _ = format_messages(messages)

    tool_use_ids, tool_result_ids = _collect_block_ids(chat_messages)

    assert tool_use_ids and tool_result_ids
    assert tool_use_ids[0] == tool_result_ids[0]
    # Must remain a valid Anthropic id (alphanumeric + underscore/dash).
    assert all(tid and all(c.isalnum() or c in "_-" for c in tid) for tid in tool_use_ids + tool_result_ids)
