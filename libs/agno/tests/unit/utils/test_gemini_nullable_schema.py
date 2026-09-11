from copy import deepcopy

import pytest

pytest.importorskip("google.genai")

from agno.utils.gemini import convert_schema


@pytest.mark.parametrize("types", [["string", "null"], ["null", "string"]])
def test_nullable_property_conversion_preserves_source(types):
    schema = {"type": "object", "properties": {"value": {"type": types, "format": "date"}}}
    original = deepcopy(schema)

    first = convert_schema(schema)
    second = convert_schema(schema)

    assert schema == original
    assert first == second
    assert first.properties["value"].type == "STRING"
    assert first.properties["value"].nullable is True
    assert first.properties["value"].format == "date"


def test_nullable_array_retains_item_constraints():
    schema = {"type": ["null", "array"], "items": {"type": "integer", "minimum": 0}, "minItems": 1}

    converted = convert_schema(schema)

    assert converted.type == "ARRAY"
    assert converted.nullable is True
    assert converted.items.type == "INTEGER"
    assert converted.items.minimum == 0
    assert converted.min_items == 1


def test_nullable_union_keeps_null_alongside_multiple_types():
    converted = convert_schema({"anyOf": [{"type": "string"}, {"type": "integer"}, {"type": "null"}]})

    assert converted.nullable is True
    assert [item.type for item in converted.any_of] == ["STRING", "INTEGER"]
