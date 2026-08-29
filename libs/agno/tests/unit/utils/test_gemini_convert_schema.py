"""Unit tests for ``agno.utils.gemini.convert_schema`` enum handling."""

from enum import IntEnum

import pytest

from agno.utils.gemini import convert_schema


class Color(IntEnum):
    RED = 1
    GREEN = 2
    BLUE = 3


def test_integer_enum_coerced_to_strings():
    """An integer ``enum`` (IntEnum / Literal[1, 2, 3] shape) must be coerced
    to strings, matching the ``GeminiType.STRING`` the converter already uses."""
    schema = convert_schema({"type": "integer", "enum": [1, 2, 3]})
    assert schema is not None
    assert schema.type == "STRING"
    assert schema.enum == ["1", "2", "3"]


def test_intenum_values_coerced_to_strings():
    schema = convert_schema({"type": "integer", "enum": [c.value for c in Color]})
    assert schema is not None
    assert schema.enum == ["1", "2", "3"]


def test_string_enum_unchanged():
    schema = convert_schema({"type": "string", "enum": ["a", "b"]})
    assert schema is not None
    assert schema.enum == ["a", "b"]


def test_mixed_enum_values_all_coerced():
    schema = convert_schema({"type": "integer", "enum": [1, 2.5, True, "x"]})
    assert schema is not None
    assert schema.enum == ["1", "2.5", "True", "x"]


@pytest.mark.parametrize("value", [1, 2, 3])
def test_each_integer_enum_member_is_string(value):
    schema = convert_schema({"type": "integer", "enum": [value]})
    assert schema is not None
    assert all(isinstance(v, str) for v in schema.enum)
