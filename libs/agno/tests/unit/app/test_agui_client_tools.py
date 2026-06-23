"""Tests for AG-UI client_tools (frontend tools) support."""

import pytest
from ag_ui.core import EventType
from ag_ui.core.types import Tool as AGUITool, ToolMessage, UserMessage

from agno.os.interfaces.agui.input import agui_tools_to_external_functions, extract_tool_messages
from agno.tools.function import Function


def test_extract_tool_messages_empty():
    """No tool messages returns empty list."""
    messages = [UserMessage(id="u1", content="hello")]
    result = extract_tool_messages(messages)
    assert result == []


def test_extract_tool_messages_trailing_tools():
    """Trailing tool messages are extracted in order."""
    messages = [
        UserMessage(id="u1", content="hello"),
        ToolMessage(id="t1", tool_call_id="call_1", content="result 1"),
        ToolMessage(id="t2", tool_call_id="call_2", content="result 2"),
    ]
    result = extract_tool_messages(messages)
    assert len(result) == 2
    assert result[0].tool_call_id == "call_1"
    assert result[1].tool_call_id == "call_2"


def test_extract_tool_messages_non_trailing_ignored():
    """Tool messages not at the end are NOT extracted (only trailing)."""
    messages = [
        ToolMessage(id="t1", tool_call_id="call_1", content="old result"),
        UserMessage(id="u1", content="follow up"),
    ]
    result = extract_tool_messages(messages)
    assert result == []


def test_agui_tools_to_external_functions_empty():
    """Empty tools list returns empty list."""
    assert agui_tools_to_external_functions(None) == []
    assert agui_tools_to_external_functions([]) == []


def test_agui_tools_to_external_functions_converts():
    """AG-UI tools are converted to Functions with external_execution=True."""
    agui_tools = [
        AGUITool(
            name="change_background",
            description="Change the page background color",
            parameters={"type": "object", "properties": {"color": {"type": "string"}}},
        ),
        AGUITool(
            name="show_modal",
            description="Show a modal dialog",
        ),
    ]

    result = agui_tools_to_external_functions(agui_tools)

    assert len(result) == 2
    assert all(isinstance(f, Function) for f in result)

    # Check first tool
    assert result[0].name == "change_background"
    assert result[0].description == "Change the page background color"
    assert result[0].external_execution is True
    assert result[0].external_execution_silent is True
    assert result[0].parameters == {"type": "object", "properties": {"color": {"type": "string"}}}

    # Check second tool (no parameters)
    assert result[1].name == "show_modal"
    assert result[1].parameters == {"type": "object", "properties": {}}
