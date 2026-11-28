"""Tests for openai_responses module"""

import base64
import copy
from pathlib import Path
from typing import Dict, List, Optional

import pytest
from pydantic import BaseModel, ConfigDict, Field, RootModel

from agno.media import Image
from agno.utils.media import resolve_image_mime_type
from agno.utils.models.openai_responses import (
    _process_bytes_image,
    _process_image,
    _process_image_path,
    _process_image_url,
    images_to_message,
    sanitize_response_schema,
)


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


PNG_HEADER = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
JPEG_HEADER = b"\xff\xd8\xff\xe0" + b"\x00" * 20
GIF_HEADER = b"GIF89a" + b"\x00" * 20
WEBP_HEADER = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 8


def _make_tmp_image(tmp_path: Path, name: str, data: bytes) -> Path:
    p = tmp_path / name
    p.write_bytes(data)
    return p


def test_resolve_explicit_mime_type_wins():
    result = resolve_image_mime_type(mime_type="image/webp", image_format="png", image_bytes=JPEG_HEADER)
    assert result == "image/webp"


def test_resolve_format_over_detection():
    result = resolve_image_mime_type(image_format="png", image_bytes=JPEG_HEADER)
    assert result == "image/png"


def test_resolve_file_extension(tmp_path):
    p = _make_tmp_image(tmp_path, "photo.webp", JPEG_HEADER)
    result = resolve_image_mime_type(file_path=p, image_bytes=JPEG_HEADER)
    assert result == "image/webp"


def test_resolve_magic_bytes_fallback():
    result = resolve_image_mime_type(image_bytes=PNG_HEADER)
    assert result == "image/png"


def test_resolve_ultimate_fallback():
    result = resolve_image_mime_type(image_bytes=b"\x00\x00\x00")
    assert result == "image/jpeg"


def test_bytes_image_detects_png():
    result = _process_bytes_image(PNG_HEADER)
    assert result["type"] == "input_image"
    assert result["image_url"].startswith("data:image/png;base64,")


def test_bytes_image_explicit_mime_overrides():
    result = _process_bytes_image(PNG_HEADER, mime_type="image/webp")
    assert result["image_url"].startswith("data:image/webp;base64,")


def test_bytes_image_format_overrides_detection():
    result = _process_bytes_image(JPEG_HEADER, image_format="tiff")
    assert result["image_url"].startswith("data:image/tiff;base64,")


def test_bytes_image_roundtrip():
    result = _process_bytes_image(PNG_HEADER)
    encoded = result["image_url"].split(",", 1)[1]
    assert base64.b64decode(encoded) == PNG_HEADER


def test_path_uses_extension(tmp_path):
    p = _make_tmp_image(tmp_path, "img.png", PNG_HEADER)
    result = _process_image_path(p)
    assert result["image_url"].startswith("data:image/png;base64,")


def test_path_explicit_mime_overrides_extension(tmp_path):
    p = _make_tmp_image(tmp_path, "img.png", PNG_HEADER)
    result = _process_image_path(p, mime_type="image/webp")
    assert result["image_url"].startswith("data:image/webp;base64,")


def test_path_format_overrides_extension(tmp_path):
    p = _make_tmp_image(tmp_path, "img.png", PNG_HEADER)
    result = _process_image_path(p, image_format="gif")
    assert result["image_url"].startswith("data:image/gif;base64,")


def test_path_magic_bytes_fallback_no_extension(tmp_path):
    p = _make_tmp_image(tmp_path, "noext", PNG_HEADER)
    result = _process_image_path(p)
    assert result["image_url"].startswith("data:image/png;base64,")


def test_path_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        _process_image_path(tmp_path / "missing.png")


def test_url_http():
    result = _process_image_url("https://example.com/photo.png")
    assert result == {"type": "input_image", "image_url": "https://example.com/photo.png"}


def test_url_data_uri():
    uri = "data:image/png;base64,abc123"
    result = _process_image_url(uri)
    assert result == {"type": "input_image", "image_url": uri}


def test_url_invalid():
    with pytest.raises(ValueError):
        _process_image_url("ftp://bad.com/img.png")


def test_process_image_bytes_uses_mime_type():
    img = Image(content=PNG_HEADER, mime_type="image/tiff")
    result = _process_image(img)
    assert result["image_url"].startswith("data:image/tiff;base64,")


def test_process_image_path_uses_mime_type(tmp_path):
    p = _make_tmp_image(tmp_path, "img.jpg", PNG_HEADER)
    img = Image(filepath=p, mime_type="image/png")
    result = _process_image(img)
    assert result["image_url"].startswith("data:image/png;base64,")


def test_process_image_detail_is_top_level():
    img = Image(content=PNG_HEADER, detail="high")
    result = _process_image(img)
    assert result["detail"] == "high"
    # Responses API: image_url is a flat string, not a nested dict
    assert isinstance(result["image_url"], str)


def test_images_to_message_mixed(tmp_path):
    p = _make_tmp_image(tmp_path, "test.webp", WEBP_HEADER)
    images = [
        Image(content=PNG_HEADER),
        Image(filepath=p),
        Image(url="https://example.com/photo.jpg"),
    ]
    result = images_to_message(images)
    assert len(result) == 3
    assert result[0]["image_url"].startswith("data:image/png;base64,")
    assert result[1]["image_url"].startswith("data:image/webp;base64,")
    assert result[2]["image_url"] == "https://example.com/photo.jpg"


def _refs_with_siblings(node):
    if isinstance(node, dict):
        found = [node] if isinstance(node.get("$ref"), str) and len(node) > 1 else []
        return found + [n for value in node.values() for n in _refs_with_siblings(value)]
    if isinstance(node, list):
        return [n for item in node for n in _refs_with_siblings(item)]
    return []


def test_sanitize_response_schema_wraps_ref_with_sibling_keywords():
    """OpenAI strict mode rejects any keyword beside $ref but accepts them beside anyOf."""
    ref = {"$ref": "#/$defs/Actor"}
    schema = {
        "type": "object",
        "$defs": {"Actor": {"type": "object", "title": "Actor", "properties": {"name": {"type": "string"}}}},
        "properties": {
            "actors": {"type": "array", "title": "Actors", "items": {**ref, "title": "Actor"}},
            "lead": {**ref, "title": "Lead", "description": "The lead actor."},
            "star": {**ref, "examples": [{"name": "Kate"}]},
            "understudy": {**ref, "default": {"name": "Billy"}},
        },
    }

    sanitize_response_schema(schema)

    properties = schema["properties"]
    assert properties["actors"]["items"] == {"anyOf": [ref], "title": "Actor"}
    assert properties["lead"] == {"anyOf": [ref], "title": "Lead", "description": "The lead actor."}
    assert properties["star"] == {"anyOf": [ref], "examples": [{"name": "Kate"}]}
    assert properties["understudy"] == {"anyOf": [ref], "default": {"name": "Billy"}}
    assert schema["$defs"]["Actor"]["title"] == "Actor"
    assert _refs_with_siblings(schema) == []


def test_sanitize_response_schema_wraps_pydantic_field_description():
    class Actor(BaseModel):
        name: str

    class Cast(BaseModel):
        lead: Actor = Field(description="The lead actor.")

    schema = Cast.model_json_schema()
    sanitize_response_schema(schema)

    assert schema["properties"]["lead"] == {"anyOf": [{"$ref": "#/$defs/Actor"}], "description": "The lead actor."}
    assert _refs_with_siblings(schema) == []


def test_sanitize_response_schema_keeps_a_recursive_root_ref():
    """A self-referencing model's root is $defs plus $ref, which OpenAI accepts; wrapping it breaks the root."""

    class Node(BaseModel):
        name: str
        child: Optional["Node"] = None

    schema = Node.model_json_schema()
    assert set(schema) == {"$defs", "$ref"}

    sanitize_response_schema(schema)

    assert schema["$ref"] == "#/$defs/Node"
    assert "anyOf" not in schema


def test_sanitize_response_schema_keeps_defs_beside_a_wrapped_ref():
    node = {"$defs": {"Actor": {"type": "object"}}, "$ref": "#/$defs/Actor", "description": "The lead actor."}
    schema = {"type": "object", "properties": {"lead": node}}

    sanitize_response_schema(schema)

    assert node["anyOf"] == [{"$ref": "#/$defs/Actor"}]
    assert node["description"] == "The lead actor."
    assert "Actor" in node["$defs"]
    assert "$ref" not in node


class _Actor(BaseModel):
    name: str


class _Cast(RootModel[_Actor]):
    pass


class _DocumentedCast(RootModel[_Actor]):
    """The cast."""


class _ConstrainedCast(RootModel[_Actor]):
    model_config = ConfigDict(json_schema_extra={"minProperties": 1})


class _Node(BaseModel):
    name: str
    child: Optional["_Node"] = None


class _Tree(RootModel[_Node]):
    """A tree."""


@pytest.mark.parametrize(
    "model, kept",
    [
        (_Cast, {"title": "_Cast"}),
        (_DocumentedCast, {"title": "_DocumentedCast", "description": "The cast."}),
        (_ConstrainedCast, {"title": "_ConstrainedCast", "minProperties": 1}),
    ],
)
def test_sanitize_response_schema_inlines_a_root_ref_with_siblings(model, kept):
    """OpenAI needs an object at the root, so a root $ref with siblings becomes its definition plus those siblings."""
    schema = model.model_json_schema()
    assert schema["$ref"] == "#/$defs/_Actor"

    sanitize_response_schema(schema)

    assert "$ref" not in schema and "anyOf" not in schema
    assert schema["type"] == "object"
    assert schema["properties"] == {"name": {"title": "Name", "type": "string"}}
    assert schema["required"] == ["name"]
    assert schema["additionalProperties"] is False
    assert {key: schema[key] for key in kept} == kept


class _Role(BaseModel):
    name: str
    role: str


class _PatternedCast(RootModel[_Role]):
    model_config = ConfigDict(json_schema_extra={"properties": {"name": {"pattern": "^[A-Z]"}}, "required": ["name"]})


def test_sanitize_response_schema_merges_root_properties_with_the_definition():
    """Keywords beside a $ref apply on top of the definition, so overlapping properties merge instead of replacing it."""
    schema = _PatternedCast.model_json_schema()
    assert schema["properties"] == {"name": {"pattern": "^[A-Z]"}}

    sanitize_response_schema(schema)

    assert schema["properties"] == {
        "name": {"title": "Name", "type": "string", "pattern": "^[A-Z]"},
        "role": {"title": "Role", "type": "string"},
    }
    assert schema["required"] == ["name", "role"]


def test_sanitize_response_schema_unions_required_when_merging_a_root_definition():
    schema = {
        "$defs": {"A": {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}},
        "$ref": "#/$defs/A",
        "required": ["y"],
        "properties": {"y": {"type": "integer"}},
    }

    sanitize_response_schema(schema)

    assert schema["properties"] == {"x": {"type": "string"}, "y": {"type": "integer"}}
    assert schema["required"] == ["x", "y"]


class _Movie(RootModel[_Cast]):
    pass


def test_sanitize_response_schema_follows_a_root_ref_chain_to_its_object():
    schema = _Movie.model_json_schema()
    assert schema["$ref"] == "#/$defs/_Cast"
    assert schema["$defs"]["_Cast"]["$ref"] == "#/$defs/_Actor"

    sanitize_response_schema(schema)

    assert "$ref" not in schema and "anyOf" not in schema
    assert schema["title"] == "_Movie"
    assert schema["type"] == "object"
    assert schema["properties"] == {"name": {"title": "Name", "type": "string"}}


def test_sanitize_response_schema_stops_on_a_root_ref_cycle():
    schema = {
        "$defs": {"A": {"$ref": "#/$defs/B", "title": "A"}, "B": {"$ref": "#/$defs/A", "title": "B"}},
        "$ref": "#/$defs/A",
        "title": "Root",
    }

    sanitize_response_schema(schema)

    assert schema["title"] == "Root"
    assert isinstance(schema["$ref"], str)


def test_sanitize_response_schema_inlines_a_recursive_root_ref():
    schema = _Tree.model_json_schema()

    sanitize_response_schema(schema)

    assert "$ref" not in schema
    assert schema["description"] == "A tree."
    assert schema["properties"]["child"]["anyOf"][0] == {"$ref": "#/$defs/_Node"}
    assert schema["$defs"]["_Node"]["additionalProperties"] is False


def test_sanitize_response_schema_leaves_an_unresolvable_root_ref():
    schema = {"$ref": "https://example.com/actor.json", "title": "Cast"}

    sanitize_response_schema(schema)

    assert schema == {"$ref": "https://example.com/actor.json", "title": "Cast"}


def test_sanitize_response_schema_leaves_literal_data_alone():
    """Values under examples, default, const and enum are data, not schemas."""

    class Doc(BaseModel):
        ref: Dict[str, str] = Field(examples=[{"$ref": "document-id", "title": "Read me"}])
        meta: Dict[str, str] = Field(default={"type": "object"})

    schema = Doc.model_json_schema()
    schema["properties"]["kind"] = {"const": {"type": "object"}}
    schema["properties"]["shape"] = {"enum": [{"$ref": "x", "title": "y"}]}

    sanitize_response_schema(schema)

    properties = schema["properties"]
    assert properties["ref"]["examples"] == [{"$ref": "document-id", "title": "Read me"}]
    assert properties["meta"]["default"] == {"type": "object"}
    assert properties["kind"]["const"] == {"type": "object"}
    assert properties["shape"]["enum"] == [{"$ref": "x", "title": "y"}]


def test_sanitize_response_schema_still_sanitizes_properties_named_like_data_keywords():
    schema = {
        "type": "object",
        "properties": {
            "examples": {"type": "object", "properties": {"a": {"type": "string"}}},
            "default": {"$ref": "#/$defs/A", "description": "A default."},
        },
    }

    sanitize_response_schema(schema)

    assert schema["properties"]["examples"]["additionalProperties"] is False
    assert schema["properties"]["default"] == {"anyOf": [{"$ref": "#/$defs/A"}], "description": "A default."}


def test_sanitize_response_schema_leaves_a_bare_ref_alone():
    schema = {"$ref": "#/$defs/Actor", "default": None}

    sanitize_response_schema(schema)

    assert schema == {"$ref": "#/$defs/Actor"}


def test_sanitize_response_schema_is_idempotent():
    schema = {"type": "object", "properties": {"lead": {"$ref": "#/$defs/Actor", "description": "The lead actor."}}}
    sanitize_response_schema(schema)
    once = copy.deepcopy(schema)

    sanitize_response_schema(schema)

    assert schema == once


def test_sanitize_response_schema_keeps_ref_beside_an_existing_any_of():
    node = {"$ref": "#/$defs/Actor", "anyOf": [{"type": "null"}]}
    schema = {"type": "object", "properties": {"lead": copy.deepcopy(node)}}

    sanitize_response_schema(schema)

    assert schema["properties"]["lead"] == node


def test_sanitize_response_schema_keeps_properties_named_title_and_ref():
    schema = {"type": "object", "properties": {"title": {"type": "string"}, "$ref": {"type": "string"}}}

    sanitize_response_schema(schema)

    assert schema["properties"] == {"title": {"type": "string"}, "$ref": {"type": "string"}}
    assert schema["required"] == ["title", "$ref"]
