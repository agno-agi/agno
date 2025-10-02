"""Tests for openai_responses module"""

import copy
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from agno.utils.models.openai_responses import sanitize_response_schema


class SimpleModel(BaseModel):
    name: str = Field(..., description="Name field")
    age: int = Field(..., description="Age field")


class DictModel(BaseModel):
    name: str = Field(..., description="Name field")
    rating: Dict[str, int] = Field(..., description="Rating dictionary")
    scores: Dict[str, float] = Field(..., description="Score dictionary")


class OptionalModel(BaseModel):
    name: str = Field(..., description="Name field")
    optional_field: Optional[str] = Field(None, description="Optional field")


def test_sanitize_response_schema_dict_fields_excluded_from_required():
    """Test that Dict fields are excluded from the required array"""
    original_schema = DictModel.model_json_schema()
    schema = copy.deepcopy(original_schema)

    sanitize_response_schema(schema)

    required_fields = schema.get("required", [])

    # Regular field should be required
    assert "name" in required_fields

    # Dict fields should NOT be required
    assert "rating" not in required_fields
    assert "scores" not in required_fields


def test_sanitize_response_schema_preserves_dict_additional_properties():
    """Test that Dict fields preserve their additionalProperties schema"""
    original_schema = DictModel.model_json_schema()
    schema = copy.deepcopy(original_schema)

    sanitize_response_schema(schema)

    # Dict fields should preserve additionalProperties
    rating_field = schema["properties"]["rating"]
    assert "additionalProperties" in rating_field
    assert rating_field["additionalProperties"]["type"] == "integer"

    scores_field = schema["properties"]["scores"]
    assert "additionalProperties" in scores_field
    assert scores_field["additionalProperties"]["type"] == "number"


def test_sanitize_response_schema_sets_root_additional_properties_false():
    """Test that root level additionalProperties is set to false"""
    original_schema = SimpleModel.model_json_schema()
    schema = copy.deepcopy(original_schema)

    sanitize_response_schema(schema)

    assert schema.get("additionalProperties") is False


def test_sanitize_response_schema_regular_fields_required():
    """Test that regular fields are included in required array"""
    original_schema = SimpleModel.model_json_schema()
    schema = copy.deepcopy(original_schema)

    sanitize_response_schema(schema)

    required_fields = schema.get("required", [])
    assert "name" in required_fields
    assert "age" in required_fields


def test_sanitize_response_schema_removes_null_defaults():
    """Test that null defaults are removed"""
    original_schema = OptionalModel.model_json_schema()
    schema = copy.deepcopy(original_schema)

    sanitize_response_schema(schema)

    optional_field = schema["properties"]["optional_field"]

    # Should not have default: null
    assert "default" not in optional_field or optional_field.get("default") is not None


def test_sanitize_response_schema_nested_objects():
    """Test sanitization works with nested objects"""

    class NestedModel(BaseModel):
        name: str = Field(..., description="Name")
        nested: Dict[str, Dict[str, int]] = Field(..., description="Nested dict")

    original_schema = NestedModel.model_json_schema()
    schema = copy.deepcopy(original_schema)

    sanitize_response_schema(schema)

    # Top level Dict should not be required
    required_fields = schema.get("required", [])
    assert "name" in required_fields
    assert "nested" not in required_fields

    # Nested additionalProperties should be preserved
    nested_field = schema["properties"]["nested"]
    assert "additionalProperties" in nested_field


def test_sanitize_response_schema_array_items():
    """Test sanitization works with array items"""

    class ArrayModel(BaseModel):
        name: str = Field(..., description="Name")
        items: List[Dict[str, int]] = Field(..., description="Array of dicts")

    original_schema = ArrayModel.model_json_schema()
    schema = copy.deepcopy(original_schema)

    sanitize_response_schema(schema)

    # Regular field should be required
    required_fields = schema.get("required", [])
    assert "name" in required_fields
    assert "items" in required_fields  # List itself should be required

    # Array items should preserve Dict structure
    items_field = schema["properties"]["items"]
    assert items_field["type"] == "array"

    # The items within the array should preserve additionalProperties
    array_items = items_field.get("items", {})
    if "additionalProperties" in array_items:
        assert array_items["additionalProperties"]["type"] == "integer"


def test_sanitize_response_schema_mixed_object_with_properties_and_additional():
    """Test object that has both properties and additionalProperties"""

    # Create a schema that has both properties and additionalProperties
    mixed_schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Fixed property"},
            "metadata": {
                "type": "object",
                "additionalProperties": {"type": "string"},
                "description": "Dynamic metadata",
            },
        },
        "required": ["name", "metadata"],
    }

    schema = copy.deepcopy(mixed_schema)
    sanitize_response_schema(schema)

    # Regular field should be required
    required_fields = schema.get("required", [])
    assert "name" in required_fields

    # Dict field should NOT be required
    assert "metadata" not in required_fields

    # Dict field should preserve additionalProperties
    metadata_field = schema["properties"]["metadata"]
    assert "additionalProperties" in metadata_field
    assert metadata_field["additionalProperties"]["type"] == "string"


def test_sanitize_response_schema_object_without_additional_properties():
    """Test regular object without additionalProperties gets additionalProperties: false"""

    regular_schema = {"type": "object", "properties": {"name": {"type": "string"}, "age": {"type": "integer"}}}

    schema = copy.deepcopy(regular_schema)
    sanitize_response_schema(schema)

    # Should add additionalProperties: false
    assert schema.get("additionalProperties") is False

    # Should make all properties required
    required_fields = schema.get("required", [])
    assert "name" in required_fields
    assert "age" in required_fields


def test_sanitize_response_schema_object_with_additional_properties_true():
    """Test object with additionalProperties: true gets converted to false"""

    loose_schema = {"type": "object", "properties": {"name": {"type": "string"}}, "additionalProperties": True}

    schema = copy.deepcopy(loose_schema)
    sanitize_response_schema(schema)

    # Should convert True to False
    assert schema.get("additionalProperties") is False


def test_sanitize_response_schema_preserves_non_object_types():
    """Test that non-object types are preserved unchanged"""

    string_schema = {"type": "string", "description": "A string"}
    array_schema = {"type": "array", "items": {"type": "integer"}}

    schema1 = copy.deepcopy(string_schema)
    schema2 = copy.deepcopy(array_schema)

    sanitize_response_schema(schema1)
    sanitize_response_schema(schema2)

    # Should be unchanged except for removed null defaults
    assert schema1["type"] == "string"
    assert schema2["type"] == "array"
    assert schema2["items"]["type"] == "integer"
