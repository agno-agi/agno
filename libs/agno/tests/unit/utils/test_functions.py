import json
from typing import Any, Dict

import pytest

from agno.tools.function import Function, FunctionCall
from agno.utils.functions import coerce_literal_argument_values, get_function_call


def _same_argument_value(left: Any, right: Any) -> bool:
    """Whether two decoded argument values match with no type coercion at all.

    Plain equality would let True stand in for 1 and 1 for 1.0, and what a
    comparison of decoded arguments pins is the type a tool is called with as
    much as the value.
    """
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return len(left) == len(right) and all(
            key in right and _same_argument_value(value, right[key]) for key, value in left.items()
        )
    if isinstance(left, list):
        return len(left) == len(right) and all(_same_argument_value(a, b) for a, b in zip(left, right))
    return bool(left == right)


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
    """Test boolean and null coercion and whitespace preservation for other strings."""
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
    """Test boolean and null coercion with surrounding whitespace."""
    arguments = json.dumps({"param1": "  None  ", "param2": " true ", "param3": "  FALSE  "})
    result = get_function_call(
        name="test_function",
        arguments=arguments,
        functions=sample_functions,
    )
    assert result is not None
    assert result.error is None
    assert result.arguments == {"param1": None, "param2": True, "param3": False}


def test_get_function_call_decodes_arguments_through_the_shared_coercion(sample_functions):
    """The values a tool is called with come from the shared coercion.

    Anything holding a copy of a call's arguments against the run's own has to
    read them the way the run did, so the coercion has one definition and this
    pins the decoding to it: the values below are the ones decoding has always
    produced, and they are also exactly what that definition returns.
    """
    sent = {
        "param1": "true",
        "param2": " FALSE ",
        "param3": "null",
        "param4": "hello",
        "param5": {"nested": "true"},
        "param6": ["true"],
        "param7": 1,
    }

    result = get_function_call(
        name="test_function",
        arguments=json.dumps(sent),
        functions=sample_functions,
    )

    expected = {
        "param1": True,
        "param2": False,
        "param3": None,
        "param4": "hello",
        "param5": {"nested": "true"},
        "param6": ["true"],
        "param7": 1,
    }

    assert result is not None
    assert result.error is None
    assert _same_argument_value(result.arguments, expected), result.arguments
    assert _same_argument_value(result.arguments, coerce_literal_argument_values(sent)), result.arguments


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
