from agno.models.message import Message
from agno.utils.session_loader import ensure_message_continuity, ensure_message_dict_continuity


def _assistant_with_tool_call(tool_call_id: str) -> Message:
    return Message(
        role="assistant",
        content="Let me check that for you.",
        tool_calls=[
            {
                "id": tool_call_id,
                "type": "function",
                "function": {"name": "search_docs", "arguments": '{"query": "status"}'},
            }
        ],
    )


def test_ensure_message_continuity_adds_synthetic_tool_result():
    messages = [
        Message(role="user", content="Hello?"),
        _assistant_with_tool_call("tool-123"),
        Message(role="assistant", content="Here is the answer"),
    ]

    fixed = ensure_message_continuity(messages)

    assert len(fixed) == 4
    assert fixed[2].role == "tool"
    assert fixed[2].tool_call_id == "tool-123"
    assert fixed[2].tool_call_error is True
    assert "not persisted" in fixed[2].content
    assert fixed[3].content == "Here is the answer"


def test_ensure_message_dict_continuity_handles_raw_dicts():
    messages = [
        Message(role="user", content="Hello?").to_dict(),
        _assistant_with_tool_call("tool-999").to_dict(),
        Message(role="assistant", content="Thanks!").to_dict(),
    ]

    fixed = ensure_message_dict_continuity(messages)
    assert len(fixed) == 4
    assert fixed[2]["role"] == "tool"
    assert fixed[2]["tool_call_id"] == "tool-999"

