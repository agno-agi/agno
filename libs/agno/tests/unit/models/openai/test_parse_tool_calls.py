from typing import Optional

from agno.models.openai.chat import OpenAIChat


class _FakeChoiceDeltaToolCallFunction:
    def __init__(self, name: Optional[str] = None, arguments: Optional[str] = None):
        self.name = name
        self.arguments = arguments


class _FakeChoiceDeltaToolCall:
    def __init__(
        self,
        index: int,
        tool_id: Optional[str] = None,
        tool_type: Optional[str] = None,
        func_name: Optional[str] = None,
        func_args: Optional[str] = None,
    ):
        self.index = index
        self.id = tool_id
        self.type = tool_type
        if func_name is not None or func_args is not None:
            self.function = _FakeChoiceDeltaToolCallFunction(name=func_name, arguments=func_args)
        else:
            self.function = None


def test_parse_tool_calls_non_zero_index_creates_independent_dicts():
    """Ensure non-zero-based tool call index does not create shared dict references."""
    deltas = [
        _FakeChoiceDeltaToolCall(
            index=1, tool_id="call_abc", tool_type="function", func_name="get_weather", func_args='{"city":"NYC"}'
        ),
    ]
    result = OpenAIChat.parse_tool_calls(deltas)

    assert len(result) == 2
    assert result[0] == {}
    assert result[1]["id"] == "call_abc"
    assert result[1]["function"]["name"] == "get_weather"
    assert result[0] is not result[1]


def test_parse_tool_calls_zero_index_works_normally():
    """Ensure standard zero-based tool calls still work."""
    deltas = [
        _FakeChoiceDeltaToolCall(
            index=0, tool_id="call_1", tool_type="function", func_name="search", func_args='{"q":"test"}'
        ),
    ]
    result = OpenAIChat.parse_tool_calls(deltas)

    assert len(result) == 1
    assert result[0]["id"] == "call_1"
    assert result[0]["function"]["name"] == "search"


def test_parse_tool_calls_multiple_tools_independent():
    """Ensure multiple tool calls at different indices are independent."""
    deltas = [
        _FakeChoiceDeltaToolCall(index=0, tool_id="call_1", tool_type="function", func_name="tool_a", func_args="{}"),
        _FakeChoiceDeltaToolCall(index=1, tool_id="call_2", tool_type="function", func_name="tool_b", func_args="{}"),
    ]
    result = OpenAIChat.parse_tool_calls(deltas)

    assert len(result) == 2
    assert result[0]["function"]["name"] == "tool_a"
    assert result[1]["function"]["name"] == "tool_b"
    assert result[0] is not result[1]
