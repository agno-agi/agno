from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field

from agno.tools.function import Function
from agno.utils.models.claude import format_tools_for_model


def test_none_input():
    """Test that None input returns None."""
    result = format_tools_for_model(None)
    assert result is None


def test_empty_list_input():
    """Test that empty list input returns None."""
    result = format_tools_for_model([])
    assert result is None


def test_non_function_tool_passthrough():
    """Test that non-function tools are passed through unchanged."""
    tools = [
        {
            "type": "computer_20241022",
            "name": "computer",
            "display_width_px": 1024,
            "display_height_px": 768,
        }
    ]
    result = format_tools_for_model(tools)
    assert result == tools


def test_simple_function_tool():
    """Test formatting a simple function tool with required parameters."""

    def get_weather(location: str, units: str):
        """Get weather information for a location

        Args:
            location: The location to get weather for
            units: Temperature units (celsius or fahrenheit)
        """
        return f"The weather in {location} is {units}"

    function = Function.from_callable(get_weather)

    tools = [
        {
            "type": "function",
            "function": function.to_dict(),
        }
    ]

    expected = [
        {
            "name": "get_weather",
            "description": "Get weather information for a location",
            "input_schema": {
                "type": "object",
                "properties": {
                    "location": {"type": "string", "description": "The location to get weather for"},
                    "units": {"type": "string", "description": "Temperature units (celsius or fahrenheit)"},
                },
                "required": ["location", "units"],
                "additionalProperties": False,
            },
        }
    ]

    result = format_tools_for_model(tools)
    assert result == expected


def test_optional_parameters_with_null_type():
    """Test that parameters with 'null' in type are not marked as required."""

    def search_database(query: str, limit: Optional[int] = None):
        """Search database with optional filters

        Args:
            query: Search query
            limit (Optional): Maximum results to return
        """
        return f"Searching database for {query} with limit {limit}"

    function = Function.from_callable(search_database)

    tools = [
        {
            "type": "function",
            "function": function.to_dict(),
        }
    ]

    result = format_tools_for_model(tools)
    assert result[0]["input_schema"]["required"] == ["query"]
    assert "limit" not in result[0]["input_schema"]["required"]


def test_optional_parameters_with_null_union():
    """Test that parameters with 'null' in type are not marked as required."""

    def search_database(query: str, limit: int | None = None):
        """Search database with optional filters

        Args:
            query: Search query
            limit (Optional): Maximum results to return
        """
        return f"Searching database for {query} with limit {limit}"

    function = Function.from_callable(search_database)

    tools = [
        {
            "type": "function",
            "function": function.to_dict(),
        }
    ]

    result = format_tools_for_model(tools)
    assert result[0]["input_schema"]["required"] == ["query"]
    assert "limit" not in result[0]["input_schema"]["required"]


def test_parameters_with_anyof_schema():
    """Test handling of parameters with anyOf schemas."""

    def process_data(data: Union[str, Dict[str, Any]]):
        """Process data with flexible input

        Args:
            data: Data to process
        """
        return f"Processing data: {data}"

    function = Function.from_callable(process_data)

    tools = [
        {
            "type": "function",
            "function": function.to_dict(),
        }
    ]

    print(tools)

    result = format_tools_for_model(tools)
    data_property = result[0]["input_schema"]["properties"]["data"]
    assert "anyOf" in data_property
    assert "type" not in data_property
    assert data_property["anyOf"] == [
        {"type": "string"},
        {
            "type": "object",
            "propertyNames": {"type": "string"},
            "additionalProperties": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    ]


def test_parameter_with_list_type_containing_null():
    """Test parameter with list type that contains null."""

    def flexible_func(required_param: str, optional_param: Union[str, None] = None):
        """Function with flexible parameters

        Args:
            required_param: Required parameter
            optional_param: Optional parameter
        """
        return f"Required parameter: {required_param}, Optional parameter: {optional_param}"

    function = Function.from_callable(flexible_func)

    tools = [
        {
            "type": "function",
            "function": function.to_dict(),
        }
    ]

    result = format_tools_for_model(tools)
    required_params = result[0]["input_schema"]["required"]
    assert "required_param" in required_params
    assert "optional_param" not in required_params


def test_parameter_missing_description():
    """Test parameter without description."""

    def test_func(param1: str):
        """Test function"""
        return f"Test function: {param1}"

    function = Function.from_callable(test_func)

    tools = [
        {
            "type": "function",
            "function": function.to_dict(),
        }
    ]

    result = format_tools_for_model(tools)
    param1 = result[0]["input_schema"]["properties"]["param1"]
    assert param1["description"] == ""
    assert param1["type"] == "string"


def test_complex_nested_schema():
    """Test complex nested parameter schema."""

    class NestedParam(BaseModel):
        nested_field: bool

    class ComplexParam(BaseModel):
        simple_param: str = Field(description="A simple string parameter")
        array_param: List[int] = Field(description="An array of integers")
        object_param: Dict[str, Any] = Field(description="An object parameter")
        nested_param: NestedParam = Field(description="A nested parameter")

    def complex_func(param: ComplexParam):
        """Function with complex parameters"""
        return f"Complex parameter: {param}"

    function = Function.from_callable(complex_func)

    tools = [
        {
            "type": "function",
            "function": function.to_dict(),
        }
    ]

    result = format_tools_for_model(tools)
    properties = result[0]["input_schema"]["properties"]

    assert "param" in properties

    inner_properties = properties["param"]["properties"]

    assert inner_properties["simple_param"] == {
        "title": "Simple Param",
        "type": "string",
        "description": "A simple string parameter",
    }
    assert inner_properties["array_param"] == {
        "title": "Array Param",
        "type": "array",
        "items": {"type": "integer"},
        "description": "An array of integers",
    }
    assert inner_properties["object_param"] == {
        "title": "Object Param",
        "type": "object",
        "description": "An object parameter",
        "additionalProperties": True,
    }
    assert inner_properties["nested_param"] == {
        "title": "NestedParam",
        "type": "object",
        "properties": {"nested_field": {"title": "Nested Field", "type": "boolean"}},
        "required": ["nested_field"],
    }
    nested_properties = inner_properties["nested_param"]["properties"]
    assert nested_properties["nested_field"] == {"title": "Nested Field", "type": "boolean"}
