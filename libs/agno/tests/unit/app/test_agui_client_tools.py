from ag_ui.core.types import Tool as AGUITool
from ag_ui.core.types import ToolMessage, UserMessage

from agno.models.response import ToolExecution
from agno.os.interfaces.agui.input import (
    extract_tool_messages,
    parse_client_tools,
)
from agno.os.interfaces.agui.resume import apply_tool_results_to_requirements
from agno.os.interfaces.agui.utils import to_json_str
from agno.run.requirement import RunRequirement
from agno.tools.function import Function

# extract_tool_messages tests


def test_extract_tool_messages_empty_list():
    result = extract_tool_messages([])
    assert result == []


def test_extract_tool_messages_no_tools():
    messages = [UserMessage(id="u1", content="hello")]
    result = extract_tool_messages(messages)
    assert result == []


def test_extract_tool_messages_trailing_tools():
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
    messages = [
        ToolMessage(id="t1", tool_call_id="call_1", content="old result"),
        UserMessage(id="u1", content="follow up"),
    ]
    result = extract_tool_messages(messages)
    assert result == []


def test_extract_tool_messages_all_tools():
    messages = [
        ToolMessage(id="t1", tool_call_id="call_1", content="result 1"),
        ToolMessage(id="t2", tool_call_id="call_2", content="result 2"),
    ]
    result = extract_tool_messages(messages)
    assert len(result) == 2
    assert result[0].tool_call_id == "call_1"
    assert result[1].tool_call_id == "call_2"


def test_extract_tool_messages_only_trailing_block():
    # Only the trailing contiguous tool block should be returned
    messages = [
        UserMessage(id="u1", content="first"),
        ToolMessage(id="t1", tool_call_id="call_old", content="old"),
        UserMessage(id="u2", content="second"),
        ToolMessage(id="t2", tool_call_id="call_new", content="new"),
    ]
    result = extract_tool_messages(messages)
    assert len(result) == 1
    assert result[0].tool_call_id == "call_new"


def test_extract_tool_messages_with_error():
    messages = [
        UserMessage(id="u1", content="hello"),
        ToolMessage(id="t1", tool_call_id="call_1", content="", error="something failed"),
    ]
    result = extract_tool_messages(messages)
    assert len(result) == 1
    assert result[0].error == "something failed"


def test_extract_tool_messages_empty_content():
    messages = [
        UserMessage(id="u1", content="hello"),
        ToolMessage(id="t1", tool_call_id="call_1", content=""),
    ]
    result = extract_tool_messages(messages)
    assert len(result) == 1
    assert result[0].content == ""


# parse_client_tools tests


def test_parse_client_tools_empty():
    assert parse_client_tools(None) == []
    assert parse_client_tools([]) == []


def test_parse_client_tools_converts():
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

    result = parse_client_tools(agui_tools)

    assert len(result) == 2
    assert all(isinstance(f, Function) for f in result)

    assert result[0].name == "change_background"
    assert result[0].description == "Change the page background color"
    assert result[0].external_execution is True
    assert result[0].external_execution_silent is True
    assert result[0].parameters == {"type": "object", "properties": {"color": {"type": "string"}}}

    assert result[1].name == "show_modal"
    assert result[1].parameters == {"type": "object", "properties": {}}


def test_agui_tools_all_have_external_execution():
    agui_tools = [
        AGUITool(name="tool_1", description="First"),
        AGUITool(name="tool_2", description="Second"),
        AGUITool(name="tool_3", description="Third"),
    ]
    result = parse_client_tools(agui_tools)

    for func in result:
        assert func.external_execution is True
        assert func.external_execution_silent is True


def test_agui_tools_no_entrypoint():
    # Frontend tools execute in browser, not server - no entrypoint
    agui_tools = [AGUITool(name="browser_tool", description="Runs in browser")]
    result = parse_client_tools(agui_tools)

    assert result[0].entrypoint is None


def test_agui_tools_empty_description():
    # AGUITool requires description, test with empty string
    agui_tools = [AGUITool(name="no_desc", description="")]
    result = parse_client_tools(agui_tools)

    assert result[0].name == "no_desc"
    assert result[0].description == ""


def test_agui_tools_preserves_complex_schema():
    complex_params = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "count": {"type": "integer"},
            "options": {
                "type": "object",
                "properties": {"enabled": {"type": "boolean"}},
            },
            "tags": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["name"],
    }
    agui_tools = [AGUITool(name="complex", description="Complex tool", parameters=complex_params)]
    result = parse_client_tools(agui_tools)

    assert result[0].parameters == complex_params


def test_agui_tools_preserves_order():
    agui_tools = [
        AGUITool(name="alpha", description="First"),
        AGUITool(name="beta", description="Second"),
        AGUITool(name="gamma", description="Third"),
    ]
    result = parse_client_tools(agui_tools)

    assert [f.name for f in result] == ["alpha", "beta", "gamma"]


# to_json_str tests


def test_to_json_str_valid_json_passthrough():
    valid_json = '{"city": "Tokyo", "temp": 26}'
    result = to_json_str(valid_json)
    assert result == valid_json


def test_to_json_str_python_repr_dict():
    python_repr = "{'city': 'Tokyo', 'temp': 26}"
    result = to_json_str(python_repr)
    assert result == '{"city": "Tokyo", "temp": 26}'


def test_to_json_str_python_repr_list():
    python_repr = "[1, 2, 3]"
    result = to_json_str(python_repr)
    assert result == "[1, 2, 3]"


def test_to_json_str_python_repr_bool():
    assert to_json_str("True") == "true"
    assert to_json_str("False") == "false"


def test_to_json_str_python_repr_none():
    assert to_json_str("None") == "null"


def test_to_json_str_plain_string():
    result = to_json_str("hello world")
    assert result == '"hello world"'


def test_to_json_str_nested_structure():
    python_repr = "{'user': {'name': 'Bob', 'tags': ['a', 'b']}}"
    result = to_json_str(python_repr)
    assert result == '{"user": {"name": "Bob", "tags": ["a", "b"]}}'


def test_to_json_str_empty_dict():
    assert to_json_str("{}") == "{}"


def test_to_json_str_empty_list():
    assert to_json_str("[]") == "[]"


# apply_tool_results_to_requirements tests


def test_apply_tool_results_basic():
    """Test basic merging of tool results into requirements."""
    stored_requirements = [
        RunRequirement(
            tool_execution=ToolExecution(
                tool_call_id="call_1",
                tool_name="change_background",
                tool_args={"color": "blue"},
                external_execution_required=True,
            )
        )
    ]
    tool_messages = [ToolMessage(id="t1", tool_call_id="call_1", content="Background changed to blue")]

    result = apply_tool_results_to_requirements(stored_requirements, tool_messages)

    assert len(result) == 1
    assert result[0].tool_execution.result == "Background changed to blue"
    assert result[0].external_execution_result == "Background changed to blue"


def test_apply_tool_results_multiple():
    """Test merging multiple tool results."""
    stored_requirements = [
        RunRequirement(
            tool_execution=ToolExecution(
                tool_call_id="call_1",
                tool_name="tool_a",
                tool_args={},
                external_execution_required=True,
            )
        ),
        RunRequirement(
            tool_execution=ToolExecution(
                tool_call_id="call_2",
                tool_name="tool_b",
                tool_args={"x": 1},
                external_execution_required=True,
            )
        ),
    ]
    tool_messages = [
        ToolMessage(id="t1", tool_call_id="call_1", content="result_a"),
        ToolMessage(id="t2", tool_call_id="call_2", content="result_b"),
    ]

    result = apply_tool_results_to_requirements(stored_requirements, tool_messages)

    assert result[0].tool_execution.result == "result_a"
    assert result[1].tool_execution.result == "result_b"


def test_apply_tool_results_with_error():
    """Test merging tool results when tool returned an error."""
    stored_requirements = [
        RunRequirement(
            tool_execution=ToolExecution(
                tool_call_id="call_1",
                tool_name="failing_tool",
                tool_args={},
                external_execution_required=True,
            )
        )
    ]
    tool_messages = [ToolMessage(id="t1", tool_call_id="call_1", content="", error="Something went wrong")]

    result = apply_tool_results_to_requirements(stored_requirements, tool_messages)

    assert result[0].tool_execution.tool_call_error is True
    assert result[0].tool_execution.result == "Something went wrong"


def test_apply_tool_results_no_match():
    """Test that unmatched requirements are unchanged."""
    stored_requirements = [
        RunRequirement(
            tool_execution=ToolExecution(
                tool_call_id="call_1",
                tool_name="some_tool",
                tool_args={},
                external_execution_required=True,
            )
        )
    ]
    tool_messages = [ToolMessage(id="t1", tool_call_id="call_other", content="result")]

    result = apply_tool_results_to_requirements(stored_requirements, tool_messages)

    assert result[0].tool_execution.result is None


def test_apply_tool_results_empty_inputs():
    """Test with empty inputs."""
    assert apply_tool_results_to_requirements([], []) == []

    stored = [
        RunRequirement(
            tool_execution=ToolExecution(
                tool_call_id="call_1",
                tool_name="tool",
                external_execution_required=True,
            )
        )
    ]
    result = apply_tool_results_to_requirements(stored, [])
    assert result[0].tool_execution.result is None
