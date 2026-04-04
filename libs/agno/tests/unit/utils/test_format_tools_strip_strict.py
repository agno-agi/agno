"""Tests for strip_strict parameter in format_tools_for_model.

Verifies that providers which do not support native structured outputs
(VertexAI Claude, AWS Bedrock Claude) correctly strip the strict field
from tool definitions, while providers that do support it (direct
Anthropic Claude) preserve it.
"""

from agno.utils.models.claude import format_tools_for_model


def _make_tool_def(name: str = "my_tool", strict: bool = True) -> dict:
    """Create a tool definition dict with strict set."""
    tool = {
        "type": "function",
        "function": {
            "name": name,
            "description": "A test tool",
            "strict": strict,
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "string", "description": "input"},
                },
                "required": ["x"],
            },
        },
    }
    return tool


class TestFormatToolsStripStrict:
    def test_strict_preserved_by_default(self):
        """Default behavior: strict=True is included in formatted output."""
        tools = [_make_tool_def(strict=True)]
        result = format_tools_for_model(tools)
        assert result is not None
        assert result[0].get("strict") is True

    def test_strict_stripped_when_requested(self):
        """When strip_strict=True, strict field is omitted from output."""
        tools = [_make_tool_def(strict=True)]
        result = format_tools_for_model(tools, strip_strict=True)
        assert result is not None
        assert "strict" not in result[0]

    def test_strip_strict_with_no_strict_set(self):
        """strip_strict=True with no strict in input is a no-op."""
        tools = [_make_tool_def(strict=False)]
        result = format_tools_for_model(tools, strip_strict=True)
        assert result is not None
        assert "strict" not in result[0]

    def test_strict_false_not_included(self):
        """strict=False should not appear in the output regardless."""
        tools = [_make_tool_def(strict=False)]
        result = format_tools_for_model(tools)
        assert result is not None
        assert "strict" not in result[0]

    def test_multiple_tools_strip_strict(self):
        """All tools have strict stripped when strip_strict=True."""
        tools = [
            _make_tool_def(name="tool_a", strict=True),
            _make_tool_def(name="tool_b", strict=True),
        ]
        result = format_tools_for_model(tools, strip_strict=True)
        assert result is not None
        assert len(result) == 2
        for tool in result:
            assert "strict" not in tool

    def test_multiple_tools_preserve_strict(self):
        """All tools preserve strict when strip_strict=False (default)."""
        tools = [
            _make_tool_def(name="tool_a", strict=True),
            _make_tool_def(name="tool_b", strict=True),
        ]
        result = format_tools_for_model(tools)
        assert result is not None
        assert len(result) == 2
        for tool in result:
            assert tool.get("strict") is True

    def test_tool_structure_preserved_when_stripping(self):
        """Stripping strict doesn't affect other tool fields."""
        tools = [_make_tool_def(name="test_tool", strict=True)]
        result = format_tools_for_model(tools, strip_strict=True)
        assert result is not None
        tool = result[0]
        assert tool["name"] == "test_tool"
        assert tool["description"] == "A test tool"
        assert "input_schema" in tool
        assert tool["input_schema"]["properties"]["x"]["type"] == "string"

    def test_none_tools_returns_none(self):
        """None input returns None regardless of strip_strict."""
        assert format_tools_for_model(None, strip_strict=True) is None
        assert format_tools_for_model(None, strip_strict=False) is None

    def test_empty_tools_returns_none(self):
        """Empty list returns None regardless of strip_strict."""
        assert format_tools_for_model([], strip_strict=True) is None
        assert format_tools_for_model([], strip_strict=False) is None
