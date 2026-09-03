"""Unpaired tool use blocks must be paired with a placeholder tool_result at format time.

Anthropic rejects a ``tool_use`` block that has no corresponding ``tool_result`` block:

    Each tool_use block must have a corresponding tool_result block.

Sessions can hold runs whose tool result was never recorded (e.g. a run that was
interrupted mid-tool-execution). Formatting pairs such calls with a placeholder
tool_result so the session stays usable and the model can see the call never completed.
"""

from typing import Any, Dict, List, Optional

from agno.models.message import Message
from agno.utils.message import MISSING_TOOL_RESULT_PLACEHOLDER
from agno.utils.models.claude import format_messages

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


def _block_type(block: Any) -> Optional[str]:
    if isinstance(block, dict):
        return block.get("type")
    return getattr(block, "type", None)


def _block_id(block: Any) -> Optional[str]:
    if isinstance(block, dict):
        return block.get("id") or block.get("tool_use_id")
    return getattr(block, "id", None)


def _block_content(block: Any) -> Any:
    if isinstance(block, dict):
        return block.get("content")
    return getattr(block, "content", None)


def _all_blocks(chat_messages: List[Dict[str, Any]]) -> List[Any]:
    return [block for message in chat_messages for block in message["content"]]


def _tool_results(chat_messages: List[Dict[str, Any]]) -> List[Any]:
    return [b for b in _all_blocks(chat_messages) if _block_type(b) == "tool_result"]


def _tool_uses(chat_messages: List[Dict[str, Any]]) -> List[Any]:
    return [b for b in _all_blocks(chat_messages) if _block_type(b) == "tool_use"]


class TestUnpairedToolCalls:
    def test_complete_turn_is_preserved(self):
        """A call with its result must still be sent — both halves, correctly paired."""
        formatted, _ = format_messages(
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

        tool_uses = _tool_uses(formatted)
        tool_results = _tool_results(formatted)
        assert len(tool_uses) == 1
        assert _block_id(tool_uses[0]) == DELEGATE_CALL_ID
        assert len(tool_results) == 1
        assert tool_results[0]["tool_use_id"] == DELEGATE_CALL_ID
        assert tool_results[0]["content"] == "Researcher: findings for X"

    def test_call_with_no_recorded_result_gets_placeholder(self):
        """The reported bug: a run persisted with a tool call and no tool message."""
        formatted, _ = format_messages(
            messages=[
                Message(role="user", content="Research X"),
                Message(role="assistant", content="", tool_calls=[_delegate_tool_call()]),
                # No tool message was ever recorded for the call above.
                Message(role="assistant", content="Here are the findings."),
            ]
        )

        tool_uses = _tool_uses(formatted)
        tool_results = _tool_results(formatted)
        assert len(tool_uses) == 1, "the call must still be sent"
        assert len(tool_results) == 1
        assert tool_results[0]["tool_use_id"] == _block_id(tool_uses[0])
        assert tool_results[0]["content"] == MISSING_TOOL_RESULT_PLACEHOLDER

    def test_mixed_turn_pairs_real_and_placeholder_results(self):
        """A mixed turn: one recorded result and one missing result both stay valid."""
        paired_id = "call_paired"
        unpaired_id = "call_unpaired"

        formatted, _ = format_messages(
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

        tool_uses = _tool_uses(formatted)
        tool_results = _tool_results(formatted)
        assert len(tool_uses) == 2
        by_use_id = {r["tool_use_id"]: r for r in tool_results}
        assert by_use_id[paired_id]["content"] == "Paired result"
        assert by_use_id[unpaired_id]["content"] == MISSING_TOOL_RESULT_PLACEHOLDER
