"""Unit tests for close_incomplete_tool_calls().

A run cancelled mid tool-execution can leave an assistant message whose tool_call
has no matching tool result. Providers reject a tool_call with no response, so the
helper inserts a synthetic result for each unanswered call.
"""

from agno.models.message import Message
from agno.utils.message import close_incomplete_tool_calls


def _assistant_with_call(tool_call_id: str, name: str = "search") -> Message:
    return Message(
        role="assistant",
        content="working...",
        tool_calls=[{"id": tool_call_id, "type": "function", "function": {"name": name, "arguments": "{}"}}],
    )


def test_empty_list_returned_unchanged():
    """Test that an empty message list is returned unchanged."""
    assert close_incomplete_tool_calls([]) == []


def test_no_tool_calls_passthrough():
    """Test that messages without tool calls pass through unchanged."""
    messages = [Message(role="user", content="hi"), Message(role="assistant", content="hello")]
    out = close_incomplete_tool_calls(messages)
    assert len(out) == 2
    assert [m.role for m in out] == ["user", "assistant"]


def test_dangling_tool_call_gets_synthetic_result():
    """Test that an unanswered tool call gets a synthetic result inserted after it."""
    messages = [
        Message(role="user", content="weather?"),
        _assistant_with_call("call_1", name="get_weather"),
        # cancelled before the tool returned -> dangling tool call
        Message(role="user", content="never mind"),
    ]
    out = close_incomplete_tool_calls(messages)
    # synthetic result inserted directly after the assistant message
    assert [m.role for m in out] == ["user", "assistant", "tool", "user"]
    synthetic = out[2]
    assert synthetic.role == "tool"
    assert synthetic.tool_call_id == "call_1"
    assert synthetic.tool_name == "get_weather"
    assert synthetic.content == '{"status": "cancelled"}'


def test_complete_pair_is_untouched():
    """Test that a tool call with a matching result is left untouched."""
    messages = [
        _assistant_with_call("call_2"),
        Message(role="tool", tool_call_id="call_2", content="result"),
    ]
    out = close_incomplete_tool_calls(messages)
    assert len(out) == 2
    assert out[1].content == "result"


def test_multiple_unanswered_calls_each_get_a_result():
    """Test that each unanswered call in a multi-call assistant message gets its own result."""
    messages = [
        Message(
            role="assistant",
            content="multi",
            tool_calls=[
                {"id": "a", "type": "function", "function": {"name": "f1", "arguments": "{}"}},
                {"id": "b", "type": "function", "function": {"name": "f2", "arguments": "{}"}},
            ],
        ),
    ]
    out = close_incomplete_tool_calls(messages)
    tool_ids = [m.tool_call_id for m in out if m.role == "tool"]
    assert tool_ids == ["a", "b"]


def test_mixed_only_unanswered_gets_synthetic():
    """Test that only the unanswered call gets a synthetic result when another is answered."""
    messages = [
        Message(
            role="assistant",
            content="multi",
            tool_calls=[
                {"id": "answered", "type": "function", "function": {"name": "f1", "arguments": "{}"}},
                {"id": "missing", "type": "function", "function": {"name": "f2", "arguments": "{}"}},
            ],
        ),
        Message(role="tool", tool_call_id="answered", content="real result"),
    ]
    out = close_incomplete_tool_calls(messages)
    synthetic = [m for m in out if m.role == "tool" and m.content == '{"status": "cancelled"}']
    real = [m for m in out if m.role == "tool" and m.content == "real result"]
    assert len(synthetic) == 1 and synthetic[0].tool_call_id == "missing"
    assert len(real) == 1


def test_combined_format_result_is_recognized_as_resolved():
    """Older Gemini combined format stores ids inside tool_calls with a None message-level
    tool_call_id; such a result must still count as resolved (no spurious synthetic)."""
    messages = [
        _assistant_with_call("g1", name="get_weather"),
        Message(
            role="tool",
            tool_call_id=None,
            content=["sunny"],
            tool_calls=[{"tool_call_id": "g1", "tool_name": "get_weather", "content": "sunny"}],
        ),
    ]
    out = close_incomplete_tool_calls(messages)
    synthetic = [m for m in out if m.role == "tool" and m.content == '{"status": "cancelled"}']
    assert synthetic == []
    assert len(out) == 2


def test_every_tool_call_has_a_result_after_sanitizing():
    """Test that every tool call has a matching result after the helper runs."""
    messages = [
        _assistant_with_call("x"),
        _assistant_with_call("y"),
    ]
    out = close_incomplete_tool_calls(messages)
    result_ids = {m.tool_call_id for m in out if m.role == "tool"}
    for m in out:
        if m.role == "assistant" and m.tool_calls:
            for tc in m.tool_calls:
                assert tc["id"] in result_ids
