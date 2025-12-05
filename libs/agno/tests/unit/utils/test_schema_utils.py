"""Tests for schema_utils module"""

from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from agno.utils.models.schema_utils import (
    _normalize_for_gemini,
    _normalize_for_openai,
    get_dict_value_type,
    get_response_schema_for_provider,
    is_dict_field,
)


class SimpleModel(BaseModel):
    name: str = Field(..., description="Name field")
    age: int = Field(..., description="Age field")


class DictModel(BaseModel):
    name: str = Field(..., description="Name field")
    rating: Dict[str, int] = Field(..., description="Rating dictionary")
    scores: Dict[str, float] = Field(..., description="Score dictionary")
    metadata: Dict[str, str] = Field(..., description="Metadata dictionary")


class ComplexModel(BaseModel):
    name: str = Field(..., description="Name field")
    rating: Dict[str, int] = Field(..., description="Rating dictionary")
    tags: List[str] = Field(..., description="List of tags")
    optional_field: Optional[str] = Field(None, description="Optional field")


def test_is_dict_field_positive():
    """Test is_dict_field correctly identifies Dict fields"""
    dict_schema = {"type": "object", "additionalProperties": {"type": "integer"}, "description": "Rating dictionary"}

    assert is_dict_field(dict_schema) is True


def test_is_dict_field_negative_regular_object():
    """Test is_dict_field correctly rejects regular objects"""
    object_schema = {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}

    assert is_dict_field(object_schema) is False


def test_is_dict_field_negative_additional_properties_false():
    """Test is_dict_field correctly rejects objects with additionalProperties: false"""
    object_schema = {"type": "object", "additionalProperties": False, "properties": {"name": {"type": "string"}}}

    assert is_dict_field(object_schema) is False


def test_is_dict_field_negative_no_additional_properties():
    """Test is_dict_field correctly rejects objects without additionalProperties"""
    object_schema = {"type": "object", "description": "Regular object"}

    assert is_dict_field(object_schema) is False


def test_get_dict_value_type():
    """Test get_dict_value_type extracts correct value types"""
    int_dict_schema = {"type": "object", "additionalProperties": {"type": "integer"}}

    float_dict_schema = {"type": "object", "additionalProperties": {"type": "number"}}

    string_dict_schema = {"type": "object", "additionalProperties": {"type": "string"}}

    assert get_dict_value_type(int_dict_schema) == "integer"
    assert get_dict_value_type(float_dict_schema) == "number"
    assert get_dict_value_type(string_dict_schema) == "string"


def test_get_dict_value_type_non_dict():
    """Test get_dict_value_type returns default for non-Dict fields"""
    regular_schema = {"type": "object", "properties": {"name": {"type": "string"}}}

    assert get_dict_value_type(regular_schema) == "string"


def test_normalize_for_openai():
    """Test OpenAI normalization excludes Dict fields from required array"""
    original_schema = DictModel.model_json_schema()
    normalized = _normalize_for_openai(original_schema.copy())

    # Should exclude Dict fields from required
    required_fields = normalized.get("required", [])
    assert "name" in required_fields  # Regular field should be required
    assert "rating" not in required_fields  # Dict field should not be required
    assert "scores" not in required_fields  # Dict field should not be required

    # Should preserve additionalProperties for Dict fields
    rating_field = normalized["properties"]["rating"]
    assert "additionalProperties" in rating_field
    assert rating_field["additionalProperties"]["type"] == "integer"

    # Should set additionalProperties: false at root level
    assert normalized.get("additionalProperties") is False


def test_normalize_for_gemini():
    """Test Gemini normalization preserves Dict field info for conversion"""
    original_schema = DictModel.model_json_schema()
    normalized = _normalize_for_gemini(original_schema.copy())

    # Should preserve additionalProperties for Dict fields
    rating_field = normalized["properties"]["rating"]
    assert "additionalProperties" in rating_field
    assert rating_field["additionalProperties"]["type"] == "integer"

    # Should enhance description for Dict fields
    assert "Dictionary with integer values" in rating_field["description"]


def test_get_response_schema_for_provider_openai():
    """Test getting OpenAI-specific schema"""
    schema = get_response_schema_for_provider(DictModel, "openai")

    # Should exclude Dict fields from required
    required_fields = schema.get("required", [])
    assert "name" in required_fields
    assert "rating" not in required_fields
    assert "scores" not in required_fields

    # Should preserve Dict field structure
    rating_field = schema["properties"]["rating"]
    assert "additionalProperties" in rating_field
    assert rating_field["additionalProperties"]["type"] == "integer"


def test_get_response_schema_for_provider_gemini():
    """Test getting Gemini-specific schema"""
    schema = get_response_schema_for_provider(DictModel, "gemini")

    # Should preserve additionalProperties for convert_schema
    rating_field = schema["properties"]["rating"]
    assert "additionalProperties" in rating_field
    assert rating_field["additionalProperties"]["type"] == "integer"

    # Should have enhanced description
    assert "Dictionary with integer values" in rating_field["description"]


def test_get_response_schema_for_provider_unknown():
    """Test getting schema for unknown provider uses generic normalization"""
    schema = get_response_schema_for_provider(ComplexModel, "unknown_provider")

    # Should have basic structure
    assert "properties" in schema
    assert "required" in schema

    # Should remove null defaults
    optional_field = schema["properties"]["optional_field"]
    assert "default" not in optional_field or optional_field.get("default") is not None


def test_complex_model_schema_handling():
    """Test schema handling with mixed field types"""
    schema = get_response_schema_for_provider(ComplexModel, "openai")

    required_fields = schema.get("required", [])

    # Regular fields should be required
    assert "name" in required_fields
    assert "tags" in required_fields

    # Dict field should not be required
    assert "rating" not in required_fields

    # Optional field handling depends on implementation
    # (could be required or not based on OpenAI's strict mode requirements)

    # Dict field should preserve structure
    rating_field = schema["properties"]["rating"]
    assert is_dict_field(rating_field)
    assert get_dict_value_type(rating_field) == "integer"


def test_simple_model_schema_handling():
    """Test schema handling with no Dict fields"""
    schema = get_response_schema_for_provider(SimpleModel, "openai")

    required_fields = schema.get("required", [])

    # All regular fields should be required
    assert "name" in required_fields
    assert "age" in required_fields

    # Should have additionalProperties: false
    assert schema.get("additionalProperties") is False


def test_multiple_dict_types():
    """Test handling of multiple Dict field types"""
    schema = get_response_schema_for_provider(DictModel, "openai")

    # Check all Dict fields are properly handled
    rating_field = schema["properties"]["rating"]
    scores_field = schema["properties"]["scores"]
    metadata_field = schema["properties"]["metadata"]

    assert is_dict_field(rating_field)
    assert is_dict_field(scores_field)
    assert is_dict_field(metadata_field)

    assert get_dict_value_type(rating_field) == "integer"
    assert get_dict_value_type(scores_field) == "number"
    assert get_dict_value_type(metadata_field) == "string"

    # None should be in required array
    required_fields = schema.get("required", [])
    assert "rating" not in required_fields
    assert "scores" not in required_fields
    assert "metadata" not in required_fields
