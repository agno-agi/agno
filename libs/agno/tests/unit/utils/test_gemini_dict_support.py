"""Tests for Gemini Dict field support in convert_schema"""

from agno.utils.gemini import convert_schema


def test_convert_schema_dict_field_integer():
    """Test converting Dict[str, int] field creates placeholder properties"""
    dict_schema = {"type": "object", "additionalProperties": {"type": "integer"}, "description": "Rating dictionary"}

    result = convert_schema(dict_schema)

    assert result is not None
    assert result.type == "OBJECT"
    assert result.properties is not None

    # Should have placeholder property
    assert "example_key" in result.properties
    placeholder = result.properties["example_key"]
    assert placeholder.type == "INTEGER"
    assert "integer values" in placeholder.description.lower()


def test_convert_schema_dict_field_string():
    """Test converting Dict[str, str] field creates string placeholder"""
    dict_schema = {"type": "object", "additionalProperties": {"type": "string"}, "description": "Metadata dictionary"}

    result = convert_schema(dict_schema)

    assert result is not None
    assert result.type == "OBJECT"

    # Should have string placeholder
    placeholder = result.properties["example_key"]
    assert placeholder.type == "STRING"
    assert "string values" in placeholder.description.lower()


def test_convert_schema_dict_field_number():
    """Test converting Dict[str, float] field creates number placeholder"""
    dict_schema = {"type": "object", "additionalProperties": {"type": "number"}, "description": "Score dictionary"}

    result = convert_schema(dict_schema)

    assert result is not None
    assert result.type == "OBJECT"

    # Should have number placeholder
    placeholder = result.properties["example_key"]
    assert placeholder.type == "NUMBER"
    assert "number values" in placeholder.description.lower()


def test_convert_schema_dict_field_with_description():
    """Test Dict field preserves original description"""
    dict_schema = {
        "type": "object",
        "additionalProperties": {"type": "integer"},
        "description": "User ratings for movies",
    }

    result = convert_schema(dict_schema)

    assert result is not None
    # Should preserve original description (enhancement happens in schema_utils normalization)
    assert "User ratings for movies" in result.description
    # The placeholder property should have descriptive text about the type
    placeholder = result.properties["example_key"]
    assert "integer values" in placeholder.description.lower()


def test_convert_schema_dict_field_without_description():
    """Test Dict field gets default description when none provided"""
    dict_schema = {"type": "object", "additionalProperties": {"type": "string"}}

    result = convert_schema(dict_schema)

    assert result is not None
    # Should have default description
    assert "Dictionary with string values" in result.description
    assert "key-value pairs" in result.description


def test_convert_schema_regular_object_still_works():
    """Test that regular objects with properties still work normally"""
    object_schema = {
        "type": "object",
        "description": "A regular object",
        "properties": {
            "name": {"type": "string", "description": "Name field"},
            "age": {"type": "integer", "description": "Age field"},
        },
        "required": ["name"],
    }

    result = convert_schema(object_schema)

    assert result is not None
    assert result.type == "OBJECT"
    assert result.description == "A regular object"

    # Should have actual properties, not placeholders
    assert "name" in result.properties
    assert "age" in result.properties
    assert "example_key" not in result.properties

    assert result.properties["name"].type == "STRING"
    assert result.properties["age"].type == "INTEGER"
    assert "name" in result.required


def test_convert_schema_object_with_additional_properties_false():
    """Test object with additionalProperties: false works normally"""
    object_schema = {"type": "object", "properties": {"name": {"type": "string"}}, "additionalProperties": False}

    result = convert_schema(object_schema)

    assert result is not None
    assert result.type == "OBJECT"

    # Should process as regular object, not Dict
    assert "name" in result.properties
    assert "example_key" not in result.properties


def test_convert_schema_object_with_additional_properties_true():
    """Test object with additionalProperties: true (not a typed Dict)"""
    object_schema = {"type": "object", "properties": {"name": {"type": "string"}}, "additionalProperties": True}

    result = convert_schema(object_schema)

    assert result is not None
    assert result.type == "OBJECT"

    # Should process as regular object since additionalProperties is not a schema
    assert "name" in result.properties
    assert "example_key" not in result.properties


def test_convert_schema_empty_object():
    """Test empty object without properties or additionalProperties"""
    object_schema = {"type": "object", "description": "Empty object"}

    result = convert_schema(object_schema)

    assert result is not None
    assert result.type == "OBJECT"
    assert result.description == "Empty object"


def test_convert_schema_nested_dict_in_properties():
    """Test object with both regular properties and Dict fields"""
    complex_schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Name field"},
            "metadata": {
                "type": "object",
                "additionalProperties": {"type": "string"},
                "description": "Dynamic metadata",
            },
        },
        "required": ["name"],
    }

    result = convert_schema(complex_schema)

    assert result is not None
    assert result.type == "OBJECT"

    # Should have regular property
    assert "name" in result.properties
    assert result.properties["name"].type == "STRING"

    # Should have converted Dict property
    assert "metadata" in result.properties
    metadata_result = result.properties["metadata"]
    assert metadata_result.type == "OBJECT"

    # The metadata object should have placeholder properties
    assert metadata_result.properties is not None
    assert "example_key" in metadata_result.properties
    assert metadata_result.properties["example_key"].type == "STRING"


def test_convert_schema_dict_field_case_insensitive_type():
    """Test that type conversion handles different cases properly"""
    dict_schema = {"type": "object", "additionalProperties": {"type": "integer"}, "description": "Test dict"}

    result = convert_schema(dict_schema)

    assert result is not None
    placeholder = result.properties["example_key"]
    # Should convert to uppercase for Gemini
    assert placeholder.type == "INTEGER"
