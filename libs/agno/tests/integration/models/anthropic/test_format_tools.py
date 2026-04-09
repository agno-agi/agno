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
        "additionalProperties": False,
    }
    nested_properties = inner_properties["nested_param"]["properties"]
    assert nested_properties["nested_field"] == {"title": "Nested Field", "type": "boolean"}


def test_pydantic_model_without_extra_forbid():
    """Test that pydantic models without extra='forbid' still get additionalProperties: false.

    This is a regression test for the bug where Anthropic API rejected tool schemas
    from pydantic models that didn't have ConfigDict(extra='forbid') set, because
    the nested object schemas were missing additionalProperties: false.
    """

    class SearchFilters(BaseModel):
        category: str = Field(description="Category to filter by")
        max_results: int = Field(default=10, description="Maximum results")

    class SearchRequest(BaseModel):
        query: str = Field(description="Search query")
        filters: SearchFilters = Field(description="Search filters")

    def search(request: SearchRequest):
        """Search with structured input

        Args:
            request: The search request
        """
        return f"Searching for {request.query}"

    function = Function.from_callable(search)

    tools = [
        {
            "type": "function",
            "function": function.to_dict(),
        }
    ]

    result = format_tools_for_model(tools)
    input_schema = result[0]["input_schema"]

    # Root level
    assert input_schema["additionalProperties"] is False

    # Nested pydantic model (SearchRequest)
    request_schema = input_schema["properties"]["request"]
    assert request_schema["additionalProperties"] is False

    # Doubly nested pydantic model (SearchFilters)
    filters_schema = request_schema["properties"]["filters"]
    assert filters_schema["additionalProperties"] is False


def test_pydantic_model_with_list_of_objects():
    """Test that list items containing pydantic objects get additionalProperties: false."""

    class Tag(BaseModel):
        name: str
        value: str

    def tag_items(tags: List[Tag]):
        """Tag items

        Args:
            tags: List of tags to apply
        """
        return f"Tagging with {tags}"

    function = Function.from_callable(tag_items)

    tools = [
        {
            "type": "function",
            "function": function.to_dict(),
        }
    ]

    result = format_tools_for_model(tools)
    tags_schema = result[0]["input_schema"]["properties"]["tags"]
    assert tags_schema["type"] == "array"
    assert tags_schema["items"]["additionalProperties"] is False


def test_mcp_schema_with_defs_preserved():
    """Test that $defs from MCP tool schemas are preserved alongside $ref pointers."""
    # MCP tools pass raw JSON schemas from external servers (skip_entrypoint_processing=True)
    mcp_tool_schema = {
        "type": "function",
        "function": {
            "name": "get_data",
            "description": "Get data for a device",
            "parameters": {
                "type": "object",
                "properties": {
                    "request": {
                        "anyOf": [{"$ref": "#/$defs/DynamicData"}, {"type": "string"}],
                        "description": "The request data",
                    }
                },
                "required": ["request"],
                "$defs": {
                    "DynamicData": {
                        "type": "object",
                        "properties": {
                            "dev": {"type": "string", "minLength": 1},
                            "startTime": {"type": "string"},
                            "endTime": {"type": "string"},
                        },
                        "required": ["dev", "startTime", "endTime"],
                    }
                },
            },
        },
    }

    result = format_tools_for_model([mcp_tool_schema])
    input_schema = result[0]["input_schema"]

    # $defs container preserved with full content
    assert input_schema["$defs"]["DynamicData"]["properties"]["dev"] == {"type": "string", "minLength": 1}
    # $ref pointer inside properties survived so it can resolve against $defs
    assert input_schema["properties"]["request"]["anyOf"][0] == {"$ref": "#/$defs/DynamicData"}
    # Standard fields still correct
    assert input_schema["type"] == "object"
    assert input_schema["required"] == ["request"]


def test_mcp_schema_with_definitions_preserved():
    """Test that definitions (legacy JSON Schema draft-04 style) are preserved."""
    # MCP tools pass raw JSON schemas from external servers (skip_entrypoint_processing=True)
    mcp_tool_schema = {
        "type": "function",
        "function": {
            "name": "legacy_tool",
            "description": "A tool using older JSON Schema style",
            "parameters": {
                "type": "object",
                "properties": {"data": {"$ref": "#/definitions/MyModel"}},
                "required": ["data"],
                "definitions": {"MyModel": {"type": "object", "properties": {"field": {"type": "string"}}}},
            },
        },
    }

    result = format_tools_for_model([mcp_tool_schema])
    input_schema = result[0]["input_schema"]

    # definitions container preserved with full content
    assert input_schema["definitions"]["MyModel"] == {"type": "object", "properties": {"field": {"type": "string"}}}
    # $ref pointer survived
    assert input_schema["properties"]["data"] == {"$ref": "#/definitions/MyModel", "description": ""}
