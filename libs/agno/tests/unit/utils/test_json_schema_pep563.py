from __future__ import annotations

from dataclasses import dataclass

from agno.utils.json_schema import get_json_schema, get_json_schema_for_arg


@dataclass
class Pep563User:
    name: str
    age: int
    active: bool = True


def test_pep563_dataclass_field_types_are_strings():
    assert isinstance(Pep563User.__dataclass_fields__["name"].type, str)
    assert Pep563User.__dataclass_fields__["name"].type == "str"


def test_get_json_schema_for_arg_accepts_pep563_dataclass():
    schema = get_json_schema_for_arg(Pep563User)
    assert schema["type"] == "object"
    assert schema["properties"]["name"]["type"] == "string"
    assert schema["properties"]["age"]["type"] == "integer"
    assert schema["properties"]["active"]["type"] == "boolean"


def test_get_json_schema_accepts_pep563_dataclass_parameter():
    schema = get_json_schema({"user": Pep563User})
    assert "user" in schema["properties"]
    assert schema["properties"]["user"]["properties"]["name"]["type"] == "string"
