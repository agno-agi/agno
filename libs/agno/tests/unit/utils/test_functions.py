import json
from typing import Dict

import pytest

from agno.tools.function import Function, FunctionCall
from agno.utils.functions import get_function_call
from agno.utils.tools import get_function_call_for_tool_call


@pytest.fixture
def sample_functions() -> Dict[str, Function]:
    return {
        "test_function": Function(
            name="test_function",
            description="A test function",
            parameters={
                "type": "object",
                "properties": {
                    "param1": {"type": "string"},
                    "param2": {"type": "integer"},
                    "param3": {"type": "boolean"},
                },
            },
        ),
        "test_function_2": Function(
            name="test_function_2",
            description="A test function 2",
            parameters={
                "type": "object",
                "properties": {
                    "code": {"type": "string"},
                },
            },
        ),
    }


def test_get_function_call_basic(sample_functions):
    """Test basic function call creation with valid arguments."""
    arguments = json.dumps({"param1": "test", "param2": 42, "param3": True})
    call_id = "test-call-123"
    result = get_function_call(
        name="test_function",
        arguments=arguments,
        call_id=call_id,
        functions=sample_functions,
    )
    assert result is not None
    assert isinstance(result, FunctionCall)
    assert result.function == sample_functions["test_function"]
    assert result.call_id == call_id
    assert result.arguments == {"param1": "test", "param2": 42, "param3": True}
    assert result.error is None


def test_provider_tool_dispatch_preserves_string_literals(sample_functions):
    """Provider JSON strings must reach the executable function unchanged."""
    received: dict[str, object] = {}

    def bash(command: str, user_facing_message: str) -> str:
        received.update(
            command=command,
            user_facing_message=user_facing_message,
        )
        return "ok"

    bash_function = Function(
        name="bash",
        description="Run a command",
        entrypoint=bash,
        parameters={
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "user_facing_message": {"type": "string"},
            },
            "required": ["command", "user_facing_message"],
        },
    )
    tool_call = {
        "id": "call-bash-1",
        "type": "function",
        "function": {
            "name": "bash",
            "arguments": json.dumps(
                {
                    "command": "true",
                    "user_facing_message": "Read the bounded evidence file",
                }
            ),
        },
    }

    result = get_function_call_for_tool_call(tool_call, {"bash": bash_function})

    assert result is not None
    assert result.error is None
    assert result.call_id == "call-bash-1"
    assert result.arguments == {
        "command": "true",
        "user_facing_message": "Read the bounded evidence file",
    }
    execution = result.execute()
    assert execution.status == "success"
    assert received == {
        "command": "true",
        "user_facing_message": "Read the bounded evidence file",
    }


def test_get_function_call_invalid_name(sample_functions):
    """Test function call with non-existent function name."""
    result = get_function_call(
        name="non_existent_function",
        arguments='{"param1": "test"}',
        functions=sample_functions,
    )
    assert result is None


def test_get_function_call_no_functions():
    """Test function call with no functions dictionary."""
    result = get_function_call(
        name="test_function",
        arguments='{"param1": "test"}',
        functions=None,
    )
    assert result is None


def test_get_function_call_invalid_json(sample_functions):
    """Test function call with invalid JSON arguments."""
    result = get_function_call(
        name="test_function",
        arguments="invalid json",
        functions=sample_functions,
    )
    assert result is not None
    assert result.error is not None
    assert "Error while decoding function arguments" in result.error


def test_get_function_call_non_dict_arguments(sample_functions):
    """Test function call with non-dictionary arguments."""
    result = get_function_call(
        name="test_function",
        arguments='["not", "a", "dict"]',
        functions=sample_functions,
    )
    assert result is not None
    assert result.error is not None
    assert "Function arguments are not a valid JSON object" in result.error


def test_get_function_call_argument(sample_functions):
    """Test preservation of JSON string values and their whitespace."""
    arguments = json.dumps(
        {
            "param1": "None",
            "param2": "True",
            "param3": "False",
            "param4": "  test  ",
        }
    )

    result = get_function_call(
        name="test_function",
        arguments=arguments,
        functions=sample_functions,
    )
    assert result is not None
    assert result.arguments == {
        "param1": "None",
        "param2": "True",
        "param3": "False",
        "param4": "  test  ",
    }


def test_get_function_call_preserves_string_argument_whitespace(sample_functions):
    """Test preservation of leading and trailing whitespace in string arguments."""
    arguments = json.dumps({"code": "\n  return value\n", "space": " "})

    result = get_function_call(
        name="test_function_2",
        arguments=arguments,
        functions=sample_functions,
    )

    assert result is not None
    assert result.arguments == {"code": "\n  return value\n", "space": " "}


def test_get_function_call_preserves_newline_only_string_arguments(sample_functions):
    """Test preservation of whitespace-only string arguments."""
    arguments = json.dumps({"param1": "\n\n", "param2": "  \t  ", "param3": "\n \n"})
    result = get_function_call(
        name="test_function",
        arguments=arguments,
        functions=sample_functions,
    )
    assert result is not None
    assert result.error is None
    assert result.arguments["param1"] == "\n\n"
    assert result.arguments["param2"] == "  \t  "
    assert result.arguments["param3"] == "\n \n"


def test_get_function_call_coercion_with_surrounding_whitespace(sample_functions):
    """Test preservation of string values with surrounding whitespace."""
    arguments = json.dumps({"param1": "  None  ", "param2": " true ", "param3": "  FALSE  "})
    result = get_function_call(
        name="test_function",
        arguments=arguments,
        functions=sample_functions,
    )
    assert result is not None
    assert result.error is None
    assert result.arguments == {
        "param1": "  None  ",
        "param2": " true ",
        "param3": "  FALSE  ",
    }


def test_get_function_call_argument_advanced(sample_functions):
    """Test function call without argument sanitization."""
    arguments = '{"param1": None, "param2": True, "param3": False, "param4": "test"}'

    result = get_function_call(
        name="test_function",
        arguments=arguments,
        functions=sample_functions,
    )

    assert result is not None
    assert result.arguments == {
        "param1": None,
        "param2": True,
        "param3": False,
        "param4": "test",
    }

    arguments = '{"code": "x = True; y = False; z = None;"}'

    result = get_function_call(
        name="test_function_2",
        arguments=arguments,
        functions=sample_functions,
    )

    assert result is not None
    assert result.arguments == {
        "code": "x = True; y = False; z = None;",
    }


def test_get_function_call_empty_arguments(sample_functions):
    """Test function call with empty arguments."""
    result = get_function_call(
        name="test_function",
        arguments="",
        functions=sample_functions,
    )
    assert result is not None
    assert result.arguments is None
    assert result.error is None


def test_get_function_call_no_arguments(sample_functions):
    """Test function call with no arguments provided."""
    result = get_function_call(
        name="test_function",
        arguments=None,
        functions=sample_functions,
    )

    assert result is not None
    assert result.arguments is None
    assert result.error is None


def test_get_function_call_empty_array_arguments(sample_functions):
    """Test function call with an empty JSON array as arguments."""
    result = get_function_call(
        name="test_function",
        arguments="[]",
        functions=sample_functions,
    )
    assert result is not None
    assert result.arguments is None
    assert result.error is None
