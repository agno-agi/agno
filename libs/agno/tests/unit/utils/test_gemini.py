from agno.utils.gemini import (
    convert_schema,
    format_function_definitions,
    needs_conversion,
    prepare_response_schema,
)


def test_convert_schema_simple_string():
    """Test converting a simple string schema"""
    schema_dict = {"type": "string", "description": "A string field"}
    result = convert_schema(schema_dict)

    assert result is not None
    assert result.type == "STRING"
    assert result.description == "A string field"


def test_convert_schema_string_with_format():
    """Test converting a string schema with a specific format"""
    schema_dict = {
        "type": "string",
        "description": "A date field",
        "format": "date",
    }

    result = convert_schema(schema_dict)

    assert result is not None
    assert result.type == "STRING"
    assert result.format == "date"


def test_convert_schema_simple_integer():
    """Test converting a simple integer schema"""
    schema_dict = {"type": "integer", "description": "An integer field", "default": 42}
    result = convert_schema(schema_dict)

    assert result is not None
    assert result.type == "INTEGER"
    assert result.description == "An integer field"
    assert result.default == 42


def test_convert_schema_integer_with_range():
    """Test converting an integer schema with minimum and maximum"""
    schema_dict = {
        "type": "integer",
        "description": "Bounded integer",
        "minimum": 0,
        "maximum": 10,
    }

    result = convert_schema(schema_dict)

    assert result is not None
    assert result.type == "INTEGER"
    assert result.minimum == 0
    assert result.maximum == 10


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


def test_convert_schema_array_with_min_max_items():
    """Test converting an array schema with minItems and maxItems"""
    schema_dict = {
        "type": "array",
        "description": "An array with limits",
        "items": {"type": "integer"},
        "minItems": 1,
        "maxItems": 5,
    }

    result = convert_schema(schema_dict)

    assert result is not None
    assert result.type == "ARRAY"
    assert result.min_items == 1
    assert result.max_items == 5
    assert result.items.type == "INTEGER"


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


def test_convert_schema_with_ref():
    """Test converting a schema with $ref to $defs"""
    schema_dict = {
        "type": "object",
        "properties": {"person": {"$ref": "#/$defs/Person"}},
        "$defs": {
            "Person": {
                "type": "object",
                "properties": {"name": {"type": "string"}, "age": {"type": "integer"}},
                "required": ["name"],
            }
        },
    }

    result = convert_schema(schema_dict)

    assert result is not None
    assert result.type == "OBJECT"
    assert "person" in result.properties

    person_schema = result.properties["person"]
    assert person_schema.type == "OBJECT"
    assert "name" in person_schema.properties
    assert "age" in person_schema.properties
    assert person_schema.properties["name"].type == "STRING"
    assert person_schema.properties["age"].type == "INTEGER"
    assert "name" in person_schema.required


def test_convert_schema_with_circular_ref():
    """Test converting a schema with circular references"""
    schema_dict = {
        "type": "object",
        "properties": {"node": {"$ref": "#/$defs/Node"}},
        "$defs": {
            "Node": {
                "type": "object",
                "properties": {
                    "value": {"type": "string"},
                    "next": {"$ref": "#/$defs/Node"},  # Circular reference
                },
            }
        },
    }

    result = convert_schema(schema_dict)

    assert result is not None
    assert result.type == "OBJECT"
    assert "node" in result.properties

    node_schema = result.properties["node"]
    assert node_schema.type == "OBJECT"
    assert "value" in node_schema.properties
    assert "next" in node_schema.properties

    # The circular reference should be handled gracefully
    next_schema = node_schema.properties["next"]
    assert next_schema.type == "OBJECT"
    assert "Circular reference" in next_schema.description


def test_convert_schema_with_multiple_refs_to_same_def():
    """Test converting a schema with multiple references to the same definition"""
    schema_dict = {
        "type": "object",
        "properties": {"sender": {"$ref": "#/$defs/Person"}, "receiver": {"$ref": "#/$defs/Person"}},
        "$defs": {
            "Person": {"type": "object", "properties": {"name": {"type": "string"}, "email": {"type": "string"}}}
        },
    }

    result = convert_schema(schema_dict)

    assert result is not None
    assert result.type == "OBJECT"
    assert "sender" in result.properties
    assert "receiver" in result.properties

    # Both should resolve to the same Person schema structure
    for prop in ["sender", "receiver"]:
        person_schema = result.properties[prop]
        assert person_schema.type == "OBJECT"
        assert "name" in person_schema.properties
        assert "email" in person_schema.properties
        assert person_schema.properties["name"].type == "STRING"
        assert person_schema.properties["email"].type == "STRING"


def test_prepare_response_schema_with_simple_model():
    """Test that simple Pydantic models are returned directly"""
    from pydantic import BaseModel

    class SimpleModel(BaseModel):
        name: str
        age: int

    result = prepare_response_schema(SimpleModel)

    # Simple models should be returned directly
    assert result == SimpleModel


def test_prepare_response_schema_with_circular_ref():
    """Test that models with circular refs get converted"""
    from typing import Optional

    from pydantic import BaseModel

    class TreeNode(BaseModel):
        value: str
        left: Optional["TreeNode"] = None
        right: Optional["TreeNode"] = None

    result = prepare_response_schema(TreeNode)

    # Should be converted to Schema, not the raw model
    assert result != TreeNode
    assert hasattr(result, "type")  # Should be a Schema object


def test_needs_conversion_simple_schema():
    """Test that simple schemas don't need conversion"""
    schema = {"type": "object", "properties": {"name": {"type": "string"}, "age": {"type": "integer"}}}

    assert needs_conversion(schema) is False


def test_needs_conversion_with_circular_ref():
    """Test that schemas with circular refs need conversion"""
    schema = {
        "type": "object",
        "properties": {"node": {"$ref": "#/$defs/Node"}},
        "$defs": {
            "Node": {
                "type": "object",
                "properties": {
                    "value": {"type": "string"},
                    "next": {"$ref": "#/$defs/Node"},  # Circular
                },
            }
        },
    }

    assert needs_conversion(schema) is True


def test_needs_conversion_with_self_ref():
    """Test that schemas with self-references need conversion"""
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}, "parent": {"$ref": "#/$defs/SameModel"}},
        "$defs": {
            "SameModel": {
                "type": "object",
                "properties": {"name": {"type": "string"}, "parent": {"$ref": "#/$defs/SameModel"}},
            }
        },
    }

    assert needs_conversion(schema) is True


def test_needs_conversion_nested_no_refs():
    """Test that nested schemas without refs don't need conversion"""
    schema = {
        "type": "object",
        "properties": {
            "address": {"type": "object", "properties": {"street": {"type": "string"}, "city": {"type": "string"}}}
        },
    }

    assert needs_conversion(schema) is False


def test_prepare_response_schema_with_dict_field():
    """Test that models with dict fields get converted"""
    from typing import Dict

    from pydantic import BaseModel

    class ModelWithDict(BaseModel):
        metadata: Dict[str, str]
        scores: Dict[str, int]

    result = prepare_response_schema(ModelWithDict)

    # Should be converted due to additionalProperties
    assert result != ModelWithDict
    assert hasattr(result, "type")  # Should be a Schema object


def test_convert_schema_string_with_title():
    """Test converting a string schema with title"""
    schema_dict = {"type": "string", "title": "Name", "description": "A string field"}
    result = convert_schema(schema_dict)

    assert result is not None
    assert result.type == "STRING"
    assert result.title == "Name"
    assert result.description == "A string field"


def test_convert_schema_object_with_title():
    """Test converting an object schema with title"""
    schema_dict = {
        "type": "object",
        "title": "Person",
        "description": "A person object",
        "properties": {
            "name": {"type": "string", "description": "Name field"},
            "age": {"type": "integer", "description": "Age field"},
        },
    }

    result = convert_schema(schema_dict)

    assert result is not None
    assert result.type == "OBJECT"
    assert result.title == "Person"
    assert result.description == "A person object"


def test_convert_schema_object_properties_with_titles():
    """Test converting an object schema where properties have titles"""
    schema_dict = {
        "type": "object",
        "properties": {
            "key": {"type": "string", "title": "Key", "description": "The key field"},
            "value": {
                "anyOf": [{"type": "string"}, {"type": "integer"}],
                "title": "Value",
                "description": "The value field",
            },
        },
        "required": ["key", "value"],
    }

    result = convert_schema(schema_dict)

    assert result is not None
    assert result.type == "OBJECT"
    assert "key" in result.properties
    assert "value" in result.properties
    assert result.properties["key"].title == "Key"
    assert result.properties["value"].title == "Value"


def test_convert_schema_enum_with_title():
    """Test converting an enum schema with title"""
    schema_dict = {
        "type": "string",
        "title": "Status",
        "enum": ["active", "inactive", "pending"],
        "description": "Status enum",
    }

    result = convert_schema(schema_dict)

    assert result is not None
    assert result.type == "STRING"
    assert result.title == "Status"
    assert result.enum == ["active", "inactive", "pending"]


def test_convert_schema_array_with_title():
    """Test converting an array schema with title"""
    schema_dict = {
        "type": "array",
        "title": "Items",
        "description": "An array of strings",
        "items": {"type": "string", "title": "Item"},
    }

    result = convert_schema(schema_dict)

    assert result is not None
    assert result.type == "ARRAY"
    assert result.title == "Items"
    assert result.items is not None
    assert result.items.type == "STRING"
    assert result.items.title == "Item"


def test_convert_schema_integer_with_title():
    """Test converting an integer schema with title"""
    schema_dict = {"type": "integer", "title": "Age", "description": "An integer field", "default": 42}
    result = convert_schema(schema_dict)

    assert result is not None
    assert result.type == "INTEGER"
    assert result.title == "Age"
    assert result.description == "An integer field"
    assert result.default == 42


def test_convert_schema_number_with_title():
    """Test converting a number schema with title"""
    schema_dict = {
        "type": "number",
        "title": "Score",
        "description": "A number field",
        "minimum": 0,
        "maximum": 100,
    }

    result = convert_schema(schema_dict)

    assert result is not None
    assert result.type == "NUMBER"
    assert result.title == "Score"
    assert result.minimum == 0
    assert result.maximum == 100


def test_convert_schema_anyof_with_title():
    """Test converting a schema with anyOf and title"""
    schema_dict = {
        "anyOf": [{"type": "string"}, {"type": "integer"}],
        "title": "StringOrInteger",
        "description": "String or integer",
    }

    result = convert_schema(schema_dict)

    assert result is not None
    assert result.title == "StringOrInteger"
    assert result.description == "String or integer"
    assert result.any_of is not None
    assert len(result.any_of) == 2


def test_convert_schema_empty_object_with_title():
    """Test converting an empty object schema with title"""
    schema_dict = {"type": "object", "title": "EmptyObject", "description": "Empty object"}
    result = convert_schema(schema_dict)

    assert result is not None
    assert result.type == "OBJECT"
    assert result.title == "EmptyObject"
    assert result.description == "Empty object"


def test_convert_schema_property_without_type_has_title():
    """Test that properties without type but with title still get title preserved"""
    schema_dict = {
        "type": "object",
        "properties": {
            "key": {"type": "string", "title": "Key"},
            "value": {"title": "Value", "description": "Value without type"},
        },
        "required": ["key", "value"],
    }

    result = convert_schema(schema_dict)

    assert result is not None
    assert result.type == "OBJECT"
    assert "key" in result.properties
    assert "value" in result.properties
    # Value property should have title even though it doesn't have a type
    assert result.properties["value"].title == "Value"
