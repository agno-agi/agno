"""format_messages must mark failed tool calls with is_error on the tool_result block.

When a tool call fails, agno records Message.tool_call_error = True. The
Anthropic formatter used to drop that flag, so Claude could not tell a failed
tool call from a successful one. The Anthropic API defines is_error on
tool_result for exactly this case.
"""

import pytest

pytest.importorskip("anthropic")

from agno.models.message import Message
from agno.utils.models.claude import format_messages


def _tool_message(**kwargs):
    kwargs.setdefault("role", "tool")
    kwargs.setdefault("content", "order service unavailable")
    kwargs.setdefault("tool_call_id", "toolu_123")
    return Message(**kwargs)


def test_tool_result_marks_failed_call_with_is_error():
    msg = _tool_message(tool_call_error=True)

    chat_messages, _ = format_messages([msg])

    assert chat_messages == [
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "toolu_123",
                    "content": "order service unavailable",
                    "is_error": True,
                }
            ],
        }
    ]


def test_tool_result_omits_is_error_on_success():
    msg = _tool_message(tool_call_error=False)

    chat_messages, _ = format_messages([msg])

    block = chat_messages[0]["content"][0]
    assert block["type"] == "tool_result"
    assert "is_error" not in block


def test_tool_result_omits_is_error_when_flag_unset():
    msg = _tool_message()

    chat_messages, _ = format_messages([msg])

    block = chat_messages[0]["content"][0]
    assert block["type"] == "tool_result"
    assert "is_error" not in block


def test_merged_tool_results_keep_is_error_per_block():
    failed = _tool_message(tool_call_error=True, tool_call_id="toolu_123", content="order service unavailable")
    ok = _tool_message(tool_call_error=False, tool_call_id="toolu_456", content="order placed")

    chat_messages, _ = format_messages([failed, ok])

    # Same-turn tool results merge into one user message; each block must keep
    # its own is_error flag.
    assert len(chat_messages) == 1
    blocks = chat_messages[0]["content"]
    assert [b["tool_use_id"] for b in blocks] == ["toolu_123", "toolu_456"]
    assert blocks[0]["is_error"] is True
    assert "is_error" not in blocks[1]
