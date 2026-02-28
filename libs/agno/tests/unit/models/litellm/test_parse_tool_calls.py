"""
Tests for LiteLLM.parse_tool_calls streaming chunk handling.

Regression test for https://github.com/phidatahq/phidata/issues/6757:
In streaming mode, tool function names from earlier chunks were overwritten
by empty strings in subsequent chunks, causing API validation errors.
"""

from agno.models.litellm import LiteLLM


class TestParseToolCallsStreamingName:
    """Verify that empty-string names in later chunks do not overwrite valid names."""

    def test_empty_name_does_not_overwrite_valid_name(self):
        """Chunks 2+ carry name="" which must not replace the real name from chunk 1."""
        chunks = [
            {"index": 0, "id": "tooluse_abc", "type": "function", "function": {"name": "add", "arguments": ""}},
            {"index": 0, "id": None, "type": "function", "function": {"name": "", "arguments": '{"a": 5'}},
            {"index": 0, "id": None, "type": "function", "function": {"name": "", "arguments": ', "b": 3}'}},
        ]

        result = LiteLLM.parse_tool_calls(chunks)

        assert len(result) == 1
        assert result[0]["function"]["name"] == "add"
        assert result[0]["id"] == "tooluse_abc"

    def test_arguments_concatenated_across_chunks(self):
        """Arguments from multiple chunks must be joined into valid JSON."""
        chunks = [
            {"index": 0, "id": "id_1", "type": "function", "function": {"name": "get_weather", "arguments": ""}},
            {"index": 0, "function": {"name": "", "arguments": '{"city"'}},
            {"index": 0, "function": {"name": "", "arguments": ': "Tokyo"}'}},
        ]

        result = LiteLLM.parse_tool_calls(chunks)

        assert result[0]["function"]["name"] == "get_weather"
        assert result[0]["function"]["arguments"] == '{"city": "Tokyo"}'

    def test_multiple_tool_calls_with_different_indices(self):
        """Each tool call index preserves its own name independently."""
        chunks = [
            {"index": 0, "id": "id_a", "type": "function", "function": {"name": "add", "arguments": ""}},
            {"index": 1, "id": "id_b", "type": "function", "function": {"name": "multiply", "arguments": ""}},
            {"index": 0, "function": {"name": "", "arguments": '{"a": 1, "b": 2}'}},
            {"index": 1, "function": {"name": "", "arguments": '{"x": 3, "y": 4}'}},
        ]

        result = LiteLLM.parse_tool_calls(chunks)

        assert len(result) == 2
        names = {r["function"]["name"] for r in result}
        assert names == {"add", "multiply"}

    def test_name_absent_from_function_data(self):
        """When name key is entirely absent (not just empty), no overwrite happens."""
        chunks = [
            {"index": 0, "id": "id_1", "type": "function", "function": {"name": "search", "arguments": ""}},
            {"index": 0, "function": {"arguments": '{"q": "test"}'}},
        ]

        result = LiteLLM.parse_tool_calls(chunks)

        assert result[0]["function"]["name"] == "search"

    def test_empty_tool_calls_returns_empty_list(self):
        """Empty input returns empty list."""
        assert LiteLLM.parse_tool_calls([]) == []

    def test_single_chunk_with_complete_data(self):
        """A single chunk with all data should work without issues."""
        chunks = [
            {
                "index": 0,
                "id": "id_1",
                "type": "function",
                "function": {"name": "greet", "arguments": '{"name": "Alice"}'},
            },
        ]

        result = LiteLLM.parse_tool_calls(chunks)

        assert len(result) == 1
        assert result[0]["function"]["name"] == "greet"
        assert result[0]["function"]["arguments"] == '{"name": "Alice"}'
