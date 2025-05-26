import json
from typing import Dict

import pytest

from agno.tools.function import Function, FunctionCall
from agno.utils.functions import get_function_call


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
        )
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
    """Test argument sanitization for boolean and null values."""
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
        "param1": None,
        "param2": True,
        "param3": False,
        "param4": "test",
    }


def test_get_function_call_argument_2(sample_functions):
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

    arguments = '{"param1": "none", "param2": "false", "param3": "true", "param4": "test"}'

    result = get_function_call(
        name="test_function",
        arguments=arguments,
        functions=sample_functions,
    )

    assert result is not None
    assert result.arguments == {
        "param1": None,
        "param2": False,
        "param3": True,
        "param4": "test",
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
