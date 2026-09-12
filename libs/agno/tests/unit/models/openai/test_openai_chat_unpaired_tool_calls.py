"""Unpaired tool calls must be paired with a placeholder tool message at format time.

Chat Completions rejects an assistant message whose ``tool_calls`` are not followed by
tool messages responding to each ``tool_call_id``:

    An assistant message with 'tool_calls' must be followed by tool messages
    responding to each tool_call_id.

Sessions can hold runs whose tool result was never recorded (e.g. a run that was
interrupted mid-tool-execution). Formatting pairs such calls with a placeholder tool
message so the session stays usable and the model can see the call never completed.
"""

from typing import Any, Dict, List

from agno.models.message import Message
from agno.models.openai.chat import OpenAIChat
from agno.utils.message import MISSING_TOOL_RESULT_PLACEHOLDER

# Shape observed in affected sessions: uuid id, no call_id.
DELEGATE_CALL_ID = "d4f8a1b2-3c5e-4a91-b7d2-8e6f0a1c2b3d"


def _delegate_tool_call(call_id: str = DELEGATE_CALL_ID) -> Dict[str, Any]:
    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": "delegate_task_to_member",
            "arguments": '{"member_id": "researcher", "task": "Research X"}',
        },
    }


def _placeholder_messages(formatted: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [m for m in formatted if m.get("content") == MISSING_TOOL_RESULT_PLACEHOLDER]


class TestUnpairedToolCalls:
    def test_complete_turn_is_preserved(self):
        """A call with its result must still be sent — both halves, correctly paired."""
        model = OpenAIChat(id="gpt-4o-mini")

        formatted = model._format_all_messages(
            messages=[
                Message(role="user", content="Research X"),
                Message(role="assistant", content="", tool_calls=[_delegate_tool_call()]),
                Message(
                    role="tool",
                    tool_call_id=DELEGATE_CALL_ID,
                    tool_name="delegate_task_to_member",
                    content="Researcher: findings for X",
                ),
                Message(role="assistant", content="Here are the findings."),
            ]
        )

        assistant_with_calls = [m for m in formatted if m.get("tool_calls")]
        tool_messages = [m for m in formatted if m.get("role") == "tool"]
        assert len(assistant_with_calls) == 1
        assert len(tool_messages) == 1
        # IDs are reformatted to the call_ prefix; the tool message must answer the emitted call.
        emitted_id = assistant_with_calls[0]["tool_calls"][0]["id"]
        assert tool_messages[0]["tool_call_id"] == emitted_id
        assert tool_messages[0]["content"] == "Researcher: findings for X"
        assert _placeholder_messages(formatted) == []

    def test_call_with_no_recorded_result_gets_placeholder(self):
        """The reported bug: a run persisted with a tool call and no tool message."""
        model = OpenAIChat(id="gpt-4o-mini")

        formatted = model._format_all_messages(
            messages=[
                Message(role="user", content="Research X"),
                Message(role="assistant", content="", tool_calls=[_delegate_tool_call()]),
                # No tool message was ever recorded for the call above.
                Message(role="assistant", content="Here are the findings."),
            ]
        )

        assistant_with_calls = [m for m in formatted if m.get("tool_calls")]
        assert len(assistant_with_calls) == 1, "the call must still be sent"
        assert assistant_with_calls[0]["tool_calls"][0]["function"]["name"] == "delegate_task_to_member"
        placeholders = _placeholder_messages(formatted)
        assert len(placeholders) == 1
        # The placeholder tool message answers the emitted call.
        emitted_id = assistant_with_calls[0]["tool_calls"][0]["id"]
        assert placeholders[0]["tool_call_id"] == emitted_id
        # The recorded tool message must not be placeholder-repaired.
        tool_messages = [m for m in formatted if m.get("role") == "tool"]
        assert len(tool_messages) == 1  # only the placeholder

    def test_result_without_tool_call_id_gets_placeholder(self):
        """A tool result that cannot be formatted is dropped; its call gets a placeholder."""
        model = OpenAIChat(id="gpt-4o-mini")

        formatted = model._format_all_messages(
            messages=[
                Message(role="user", content="Research X"),
                Message(role="assistant", content="", tool_calls=[_delegate_tool_call()]),
                Message(role="tool", tool_call_id=None, tool_name="delegate_task_to_member", content="findings"),
            ]
        )

        assistant_with_calls = [m for m in formatted if m.get("tool_calls")]
        assert len(assistant_with_calls) == 1
        emitted_id = assistant_with_calls[0]["tool_calls"][0]["id"]
        placeholders = _placeholder_messages(formatted)
        assert len(placeholders) == 1
        assert placeholders[0]["tool_call_id"] == emitted_id

    def test_tool_message_with_none_content_counts_as_recorded(self):
        """A tool message with a call id and None content is still emitted (as ""), so its
        call must not get a duplicate placeholder result."""
        model = OpenAIChat(id="gpt-4o-mini")

        formatted = model._format_all_messages(
            messages=[
                Message(role="user", content="Research X"),
                Message(role="assistant", content="", tool_calls=[_delegate_tool_call()]),
                Message(role="tool", tool_call_id=DELEGATE_CALL_ID, tool_name="delegate_task_to_member", content=None),
            ]
        )

        assert _placeholder_messages(formatted) == []

    def test_mixed_turn_pairs_real_and_placeholder_results(self):
        """A mixed turn: one recorded result and one missing result both stay valid."""
        model = OpenAIChat(id="gpt-4o-mini")
        paired_id = "call_paired"
        unpaired_id = "call_unpaired"

        formatted = model._format_all_messages(
            messages=[
                Message(role="user", content="Do both tasks"),
                Message(
                    role="assistant",
                    content="",
                    tool_calls=[_delegate_tool_call(paired_id), _delegate_tool_call(unpaired_id)],
                ),
                Message(role="tool", tool_call_id=paired_id, tool_name="delegate_task_to_member", content="Paired result"),
                Message(role="assistant", content="Done."),
            ]
        )

        tool_messages = [m for m in formatted if m.get("role") == "tool"]
        by_id = {m["tool_call_id"]: m for m in tool_messages}
        assert by_id[paired_id]["content"] == "Paired result"
        assert by_id[unpaired_id]["content"] == MISSING_TOOL_RESULT_PLACEHOLDER
