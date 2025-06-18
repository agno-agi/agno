from agno.utils.gemini import convert_schema, format_function_definitions


def test_convert_schema_simple_string():
    """Test converting a simple string schema"""
    schema_dict = {"type": "string", "description": "A string field"}
    result = convert_schema(schema_dict)

    assert result is not None
    assert result.type == "STRING"
    assert result.description == "A string field"


def test_convert_schema_simple_integer():
    """Test converting a simple integer schema"""
    schema_dict = {"type": "integer", "description": "An integer field", "default": 42}
    result = convert_schema(schema_dict)

    assert result is not None
    assert result.type == "INTEGER"
    assert result.description == "An integer field"
    assert result.default == 42


def test_convert_schema_object_with_properties():
    """Test converting an object schema with properties"""
    schema_dict = {
        "type": "object",
        "description": "A test object",
        "properties": {
            "name": {"type": "string", "description": "Name field"},
            "age": {"type": "integer", "description": "Age field"},
        },
        "required": ["name"],
    }

    result = convert_schema(schema_dict)

    assert result is not None
    assert result.type == "OBJECT"
    assert result.description == "A test object"
    assert "name" in result.properties
    assert "age" in result.properties
    assert result.properties["name"].type == "STRING"
    assert result.properties["age"].type == "INTEGER"
    assert "name" in result.required
    assert "age" not in result.required


def test_convert_schema_array():
    """Test converting an array schema"""
    schema_dict = {"type": "array", "description": "An array of strings", "items": {"type": "string"}}

    result = convert_schema(schema_dict)

    assert result is not None
    assert result.type == "ARRAY"
    assert result.description == "An array of strings"
    assert result.items is not None
    assert result.items.type == "STRING"


def test_convert_schema_nullable_property():
    """Test converting a schema with nullable property"""
    schema_dict = {
        "type": "object",
        "properties": {"name": {"type": "string"}, "optional_field": {"type": ["string", "null"]}},
    }

    result = convert_schema(schema_dict)

    assert result is not None
    assert result.properties["optional_field"].nullable is True


def test_convert_schema_anyof():
    """Test converting a schema with anyOf"""
    schema_dict = {"anyOf": [{"type": "string"}, {"type": "integer"}], "description": "String or integer"}

    result = convert_schema(schema_dict)

    assert result is not None
    assert result.description == "String or integer"
    assert result.any_of is not None
    assert len(result.any_of) == 2
    assert result.any_of[0].type == "STRING"
    assert result.any_of[1].type == "INTEGER"


def test_convert_schema_anyof_with_null():
    """Test converting a schema with anyOf including null (nullable)"""
    schema_dict = {"anyOf": [{"type": "string"}, {"type": "null"}], "description": "Nullable string"}

    result = convert_schema(schema_dict)

    assert result is not None
    assert result.type == "STRING"
    assert result.nullable is True


def test_convert_schema_null_type():
    """Test converting a schema with null type"""
    schema_dict = {"type": "null"}
    result = convert_schema(schema_dict)

    assert result is None


def test_convert_schema_empty_object():
    """Test converting an empty object schema"""
    schema_dict = {"type": "object"}
    result = convert_schema(schema_dict)

    assert result is not None
    assert result.type == "OBJECT"
    assert not hasattr(result, "properties") or not result.properties


def test_format_function_definitions_single_function():
    """Test formatting a single function definition"""
    tools_list = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get weather for a location",
                "parameters": {
                    "type": "object",
                    "properties": {"location": {"type": "string", "description": "The city and state"}},
                    "required": ["location"],
                },
            },
        }
    ]

    result = format_function_definitions(tools_list)

    assert result is not None
    assert len(result.function_declarations) == 1
    func = result.function_declarations[0]
    assert func.name == "get_weather"
    assert func.description == "Get weather for a location"
    assert func.parameters.properties["location"].type == "STRING"
    assert "location" in func.parameters.required


def test_format_function_definitions_multiple_functions():
    """Test formatting multiple function definitions"""
    tools_list = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get weather for a location",
                "parameters": {
                    "type": "object",
                    "properties": {"location": {"type": "string"}},
                    "required": ["location"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_time",
                "description": "Get current time for a timezone",
                "parameters": {
                    "type": "object",
                    "properties": {"timezone": {"type": "string"}},
                    "required": ["timezone"],
                },
            },
        },
    ]

    result = format_function_definitions(tools_list)

    assert result is not None
    assert len(result.function_declarations) == 2
    assert result.function_declarations[0].name == "get_weather"
    assert result.function_declarations[1].name == "get_time"


def test_format_function_definitions_no_functions():
    """Test formatting with no valid functions"""
    tools_list = [{"type": "not_a_function", "something": "else"}]

    result = format_function_definitions(tools_list)

    assert result is None


def test_format_function_definitions_empty_list():
    """Test formatting with an empty tools list"""
    tools_list = []

    result = format_function_definitions(tools_list)

    assert result is None


def test_format_function_definitions_complex_parameters():
    """Test formatting a function with complex nested parameters"""
    tools_list = [
        {
            "type": "function",
            "function": {
                "name": "complex_function",
                "description": "A function with complex parameters",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "simple_param": {"type": "string"},
                        "object_param": {"type": "object", "properties": {"nested_field": {"type": "integer"}}},
                        "array_param": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["simple_param"],
                },
            },
        }
    ]

    result = format_function_definitions(tools_list)

    assert result is not None
    func = result.function_declarations[0]
    assert func.name == "complex_function"

    # Check nested parameters
    params = func.parameters
    assert "simple_param" in params.properties
    assert "object_param" in params.properties
    assert "array_param" in params.properties

    # Check object param
    object_param = params.properties["object_param"]
    assert object_param.type == "OBJECT"
    assert "nested_field" in object_param.properties

    # Check array param
    array_param = params.properties["array_param"]
    assert array_param.type == "ARRAY"
    assert array_param.items.type == "STRING"


def test_convert_schema_union():
    """Test converting a schema with union types using anyOf"""
    schema_dict = {
        "anyOf": [
            {"type": "string", "description": "A string value"},
            {"type": "integer", "description": "An integer value"},
            {"type": "boolean", "description": "A boolean value"},
        ],
        "description": "A union of string, integer, and boolean",
    }

    result = convert_schema(schema_dict)

    assert result is not None
    assert result.description == "A union of string, integer, and boolean"
    assert result.any_of is not None
    assert len(result.any_of) == 3
    assert result.any_of[0].type == "STRING"
    assert result.any_of[0].description == "A string value"
    assert result.any_of[1].type == "INTEGER"
    assert result.any_of[1].description == "An integer value"
    assert result.any_of[2].type == "BOOLEAN"
    assert result.any_of[2].description == "A boolean value"
