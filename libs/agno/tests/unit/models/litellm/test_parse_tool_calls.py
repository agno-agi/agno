"""Tests for LiteLLM parse_tool_calls streaming chunk reassembly."""

from agno.models.litellm import LiteLLM


def test_parse_tool_calls_preserves_name_across_chunks():
    """Empty name strings in later chunks must not overwrite a valid name from an earlier chunk."""
    chunks = [
        {"index": 0, "id": "tooluse_1", "type": "function", "function": {"name": "add", "arguments": ""}},
        {"index": 0, "id": None, "type": "function", "function": {"name": "", "arguments": '{"a": 5'}},
        {"index": 0, "id": None, "type": "function", "function": {"name": "", "arguments": ', "b": 3}'}},
    ]

    result = LiteLLM.parse_tool_calls(chunks)

    assert len(result) == 1
    assert result[0]["function"]["name"] == "add"
    assert result[0]["function"]["arguments"] == '{"a": 5, "b": 3}'


def test_parse_tool_calls_multiple_tools():
    """Multiple tool calls at different indices should each preserve their names."""
    chunks = [
        {"index": 0, "id": "id_1", "type": "function", "function": {"name": "search", "arguments": ""}},
        {"index": 1, "id": "id_2", "type": "function", "function": {"name": "calculate", "arguments": ""}},
        {"index": 0, "function": {"name": "", "arguments": '{"q": "test"}'}},
        {"index": 1, "function": {"name": "", "arguments": '{"expr": "1+1"}'}},
    ]

    result = LiteLLM.parse_tool_calls(chunks)

    assert len(result) == 2
    names = {tc["function"]["name"] for tc in result}
    assert names == {"search", "calculate"}
