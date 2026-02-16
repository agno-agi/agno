"""
Regression test for parse_tool_calls shared-dict bug (#6542).

`[{}] * N` creates N references to the *same* dict object.
The fix uses `[{} for _ in range(N)]` to create independent dicts.
"""

from unittest.mock import MagicMock

from agno.models.openai.chat import OpenAIChat


def _make_delta(index, tool_id=None, tool_type=None, func_name=None, func_args=None):
    """Create a mock ChoiceDeltaToolCall."""
    delta = MagicMock()
    delta.index = index
    delta.id = tool_id
    delta.type = tool_type
    if func_name is not None or func_args is not None:
        delta.function.name = func_name
        delta.function.arguments = func_args
    else:
        delta.function = None
    return delta


def test_parse_tool_calls_non_zero_index_creates_independent_dicts():
    """Ensure non-zero-based tool call index does not create shared dict references."""
    deltas = [
        _make_delta(
            index=1, tool_id="call_abc", tool_type="function", func_name="get_weather", func_args='{"city":"NYC"}'
        ),
    ]
    result = OpenAIChat.parse_tool_calls(deltas)

    assert len(result) == 2
    # index 0 should be an empty placeholder, index 1 should have the tool call
    assert result[0] == {}
    assert result[1]["id"] == "call_abc"
    assert result[1]["function"]["name"] == "get_weather"
    # Critical: the two entries must NOT be the same object
    assert result[0] is not result[1]


def test_parse_tool_calls_zero_index_works_normally():
    """Ensure standard zero-based tool calls still work."""
    deltas = [
        _make_delta(index=0, tool_id="call_1", tool_type="function", func_name="search", func_args='{"q":"test"}'),
    ]
    result = OpenAIChat.parse_tool_calls(deltas)

    assert len(result) == 1
    assert result[0]["id"] == "call_1"
    assert result[0]["function"]["name"] == "search"


def test_parse_tool_calls_multiple_tools_independent():
    """Ensure multiple tool calls at different indices are independent."""
    deltas = [
        _make_delta(index=0, tool_id="call_1", tool_type="function", func_name="tool_a", func_args="{}"),
        _make_delta(index=1, tool_id="call_2", tool_type="function", func_name="tool_b", func_args="{}"),
    ]
    result = OpenAIChat.parse_tool_calls(deltas)

    assert len(result) == 2
    assert result[0]["function"]["name"] == "tool_a"
    assert result[1]["function"]["name"] == "tool_b"
    assert result[0] is not result[1]
