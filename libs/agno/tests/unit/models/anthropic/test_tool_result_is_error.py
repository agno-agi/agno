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
