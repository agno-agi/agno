"""json_schema_to_model builds a Pydantic model that keeps what the JSON Schema says, or refuses."""

import json
import re
import warnings
from typing import Any, Optional

import pytest
from pydantic import BaseModel, ValidationError

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.models.openai import OpenAIChat, OpenAIResponses
from agno.run.agent import RunOutput
from agno.team import Team
from agno.utils.models.json_schema_model import (
    UnsupportedJsonSchemaError,
    json_schema_to_model,
    rehydrate_inline_output_schema,
    serialize_output_schema,
    source_json_schema,
)
from agno.utils.models.schema_utils import json_schema_response_format

TICKET = {
    "title": "Ticket",
    "type": "object",
    "description": "A support ticket",
    "properties": {
        "summary": {"type": "string", "description": "One-line summary", "maxLength": 80},
        "priority": {"type": "string", "enum": ["low", "medium", "high"]},
        "assignee": {"type": ["string", "null"], "description": "Email, or null if unassigned"},
        "labels": {"type": "object", "additionalProperties": {"type": "string"}},
        "due": {"anyOf": [{"type": "string", "format": "date"}, {"type": "null"}]},
        "owner": {"$ref": "#/$defs/Person"},
        "score": {"type": "integer", "minimum": 1, "maximum": 5},
        "tags": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
    },
    "required": ["summary", "priority", "assignee", "labels", "due", "owner", "score", "tags"],
    "$defs": {
        "Person": {
            "type": "object",
            "properties": {"name": {"type": "string"}, "manager": {"$ref": "#/$defs/Person"}},
            "required": ["name"],
        }
    },
}
VALID = {
    "summary": "Login fails",
    "priority": "high",
    "assignee": None,
    "labels": {"area": "auth"},
    "due": "2026-11-01",
    "owner": {"name": "Ana", "manager": {"name": "Bo"}},
    "score": 4,
    "tags": ["login"],
}


@pytest.fixture(scope="module")
def ticket():
    return json_schema_to_model(TICKET)


def test_the_model_schema_keeps_every_constraint(ticket):
    out = ticket.model_json_schema()
    props = out["properties"]
    assert out["title"] == "Ticket"
    assert out["description"] == "A support ticket"
    assert props["summary"]["description"] == "One-line summary"
    assert props["summary"]["maxLength"] == 80
    assert props["priority"]["enum"] == ["low", "medium", "high"]
    assert props["assignee"]["description"] == "Email, or null if unassigned"
    assert {"type": "null"} in props["assignee"]["anyOf"]
    assert props["labels"]["additionalProperties"] == {"type": "string"}
    assert {"type": "string", "format": "date"} in props["due"]["anyOf"]
    assert props["score"]["minimum"] == 1 and props["score"]["maximum"] == 5
    assert props["tags"]["maxItems"] == 3
    assert sorted(out["required"]) == sorted(TICKET["required"])
    assert "Person" in out["$defs"]


def test_valid_output_validates_including_a_recursive_ref(ticket):
    parsed = ticket.model_validate(VALID)
    assert parsed.owner.manager.name == "Bo"
    assert parsed.assignee is None


@pytest.mark.parametrize(
    "change",
    [
        {"priority": "urgent"},
        {"summary": "x" * 81},
        {"score": 9},
        {"labels": {"area": 3}},
        {"tags": ["a", "b", "c", "d"]},
    ],
    ids=["enum", "maxLength", "maximum", "map-value-type", "maxItems"],
)
def test_output_breaking_the_schema_is_rejected(ticket, change):
    with pytest.raises(ValidationError):
        ticket.model_validate({**VALID, **change})


def test_an_optional_property_may_be_absent_or_null():
    model = json_schema_to_model({"type": "object", "properties": {"name": {"type": "string", "minLength": 2}}})
    assert "default" not in model.model_json_schema()["properties"]["name"]
    assert model.model_validate({}).name is None
    assert model.model_validate({"name": None}).name is None
    with pytest.raises(ValidationError):
        model.model_validate({"name": "x"})


def test_a_required_property_stays_non_nullable():
    model = json_schema_to_model({"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]})
    with pytest.raises(ValidationError):
        model.model_validate({"name": None})


def test_null_for_an_optional_property_with_a_default_becomes_the_default():
    model = json_schema_to_model(
        {
            "type": "object",
            "properties": {"unit": {"enum": ["c", "f"], "default": "c"}, "n": {"type": "integer", "default": 3}},
        }
    )
    assert model.model_validate({}).unit == "c"
    parsed = model.model_validate({"unit": None, "n": None})
    assert (parsed.unit, parsed.n) == ("c", 3)
    assert model.model_validate({"unit": "f"}).unit == "f"


@pytest.mark.parametrize(
    "field",
    [
        {"type": ["string", "null"], "default": "x"},
        {"type": "string", "nullable": True, "default": "x"},
        {"enum": ["x", None], "default": "x"},
        {"anyOf": [{"type": "string"}, {"type": "null"}], "default": "x"},
        {"$ref": "#/$defs/N", "default": "x"},
    ],
    ids=["type-list", "nullable", "enum", "any-of", "ref"],
)
def test_null_stays_null_when_the_schema_allows_it(field):
    model = json_schema_to_model(
        {"type": "object", "properties": {"a": field}, "$defs": {"N": {"type": ["string", "null"]}}}
    )
    assert model.model_validate({"a": None}).a is None
    assert model.model_validate({}).a == "x"


@pytest.mark.parametrize(
    "field",
    [
        {"type": "integer", "default": "5"},
        {"type": "boolean", "default": "true"},
        {"type": "string", "default": 5},
        {"type": "integer", "default": 3.5},
        {"type": "array", "items": {"type": "integer"}, "default": ["1"]},
    ],
    ids=["str-for-int", "str-for-bool", "int-for-str", "fraction-for-int", "str-in-int-array"],
)
def test_a_default_that_only_passes_by_coercion_is_refused(field):
    with pytest.raises(UnsupportedJsonSchemaError, match="does not match"):
        json_schema_to_model({"type": "object", "properties": {"a": field}})


def test_an_integral_float_default_becomes_an_integer():
    value = (
        json_schema_to_model({"type": "object", "properties": {"a": {"type": "integer", "default": 3.0}}})
        .model_validate({})
        .a
    )
    assert value == 3 and isinstance(value, int)


@pytest.mark.parametrize(
    "field, defs, expected",
    [
        ({"$ref": "#/$defs/I", "default": 3.0}, {"I": {"type": "integer"}}, 3),
        ({"anyOf": [{"type": "integer"}, {"type": "string"}], "default": 3.0}, {}, 3),
        ({"type": "array", "items": {"type": "integer"}, "default": [1.0, 2.0]}, {}, [1, 2]),
    ],
    ids=["ref", "any-of", "array-items"],
)
def test_integral_float_defaults_work_at_any_depth(field, defs, expected):
    model = json_schema_to_model({"type": "object", "properties": {"a": field}, "$defs": defs})
    value = model.model_validate({}).a
    assert value == expected
    assert all(isinstance(item, int) for item in (value if isinstance(value, list) else [value]))


def test_an_integral_float_default_in_a_nested_object_works():
    model = json_schema_to_model(
        {
            "type": "object",
            "properties": {
                "a": {"type": "object", "properties": {"count": {"type": "integer"}}, "default": {"count": 3.0}}
            },
        }
    )
    count = model.model_validate({}).a.count
    assert count == 3 and isinstance(count, int)


def test_a_fractional_default_is_still_refused_at_depth():
    with pytest.raises(UnsupportedJsonSchemaError, match="does not match"):
        json_schema_to_model(
            {
                "type": "object",
                "properties": {
                    "a": {"type": "object", "properties": {"count": {"type": "integer"}}, "default": {"count": 3.5}}
                },
            }
        )


def test_an_integer_default_is_valid_for_a_number():
    model = json_schema_to_model({"type": "object", "properties": {"a": {"type": "number", "default": 3}}})
    assert model.model_validate({}).a == 3


def test_an_object_default_is_applied_as_its_model():
    model = json_schema_to_model(
        {
            "type": "object",
            "properties": {"n": {"type": "object", "properties": {"x": {"type": "string"}}, "default": {"x": "a"}}},
        }
    )
    assert model.model_validate({}).n.x == "a"


def _nullable_model():
    return json_schema_to_model(
        {
            "type": "object",
            "properties": {
                "city": {"type": "string"},
                "alert": {"type": ["string", "null"]},
                "note": {"type": "string"},
                "n": {
                    "type": "object",
                    "properties": {"x": {"type": ["string", "null"]}},
                    "required": ["x"],
                },
            },
            "required": ["city", "alert", "n"],
        }
    )


def test_run_output_keeps_a_required_null_and_drops_an_optional_one():
    model = _nullable_model()
    content = RunOutput(content=model(city="Paris", alert=None, n={"x": None})).to_dict()["content"]
    assert content == {"city": "Paris", "alert": None, "n": {"x": None}}


def test_a_required_null_survives_json_serialization():
    model = _nullable_model()
    dumped = model(city="Paris", alert=None, n={"x": None}).model_dump_json(exclude_none=True)
    assert json.loads(dumped) == {"city": "Paris", "alert": None, "n": {"x": None}}


@pytest.mark.parametrize(
    "kwargs, expected",
    [
        ({}, {"city": "Paris", "alert": None, "note": None, "n": {"x": None}}),
        ({"include": {"city"}}, {"city": "Paris"}),
        ({"exclude": {"alert", "note", "n"}}, {"city": "Paris"}),
        ({"exclude_none": True, "include": {"city"}}, {"city": "Paris"}),
        ({"exclude_none": True, "exclude": {"alert"}}, {"city": "Paris", "n": {"x": None}}),
        ({"exclude_none": True, "exclude": {"n": {"x"}}}, {"city": "Paris", "alert": None, "n": {}}),
        ({"exclude_none": True, "include": {"n": {"x"}}}, {"n": {"x": None}}),
    ],
    ids=["no-filter", "include", "exclude", "none-and-include", "none-and-exclude", "nested-exclude", "nested-include"],
)
def test_serialization_filters_win_over_required_nulls(kwargs, expected):
    instance = _nullable_model()(city="Paris", alert=None, n={"x": None})
    assert instance.model_dump(**kwargs) == expected
    assert json.loads(instance.model_dump_json(**kwargs)) == expected


def test_a_filter_on_a_list_item_applies_to_that_item_only():
    model = json_schema_to_model(
        {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"x": {"type": ["string", "null"]}},
                        "required": ["x"],
                    },
                }
            },
            "required": ["items"],
        }
    )
    instance = model(items=[{"x": None}, {"x": None}])
    assert instance.model_dump(exclude_none=True, exclude={"items": {0: {"x"}}}) == {"items": [{}, {"x": None}]}


def test_serializing_keeps_undeclared_keys():
    model = json_schema_to_model({"type": "object", "properties": {"a": {"type": "string"}}})
    assert model.model_validate({"other": 1}).model_dump(exclude_none=True) == {"other": 1}


def test_format_survives_on_optional_and_required_properties_without_warnings():
    field = {"type": "string", "format": "date-time"}
    schema = {"type": "object", "properties": {"a": field, "b": field}, "required": ["b"]}
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        props = json_schema_to_model(schema).model_json_schema()["properties"]
    assert props["a"]["anyOf"][0]["format"] == "date-time"
    assert props["b"]["format"] == "date-time"


def test_a_property_title_is_kept():
    model = json_schema_to_model({"type": "object", "properties": {"a": {"type": "string", "title": "Pretty A"}}})
    assert model.model_json_schema()["properties"]["a"]["title"] == "Pretty A"


@pytest.mark.parametrize(
    "schema, reason",
    [
        ({"type": "integer", "default": "x"}, "does not match"),
        ({"type": "integer", "minimum": 5, "default": 1}, "does not match"),
        ({"enum": ["a"], "default": "b"}, "does not match"),
    ],
)
def test_a_default_its_property_rejects_is_refused(schema, reason):
    with pytest.raises(UnsupportedJsonSchemaError, match=reason):
        json_schema_to_model({"type": "object", "properties": {"a": schema}})


def test_a_default_is_checked_beside_a_required_property():
    model = json_schema_to_model(
        {
            "type": "object",
            "properties": {"a": {"type": "integer", "default": 1}, "b": {"type": "string"}},
            "required": ["b"],
        }
    )
    assert model.model_validate({"b": "x"}).a == 1


def test_model_prefixed_names_that_are_not_pydantic_attributes_work_without_warnings():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        model = json_schema_to_model(
            {"type": "object", "properties": {"model_name": {"type": "string"}, "model_dump_id": {"type": "string"}}}
        )
    assert model.model_validate({"model_name": "m"}).model_name == "m"


def test_undeclared_additional_properties_stay_out_of_the_model_schema():
    model = json_schema_to_model(
        {
            "type": "object",
            "properties": {"n": {"type": "object", "properties": {"x": {"type": "string"}}}},
        }
    )
    schema = model.model_json_schema()
    assert "additionalProperties" not in schema
    assert "additionalProperties" not in schema["$defs"]["N"]
    assert model.model_validate({"other": 1}).model_dump()["other"] == 1


def test_declared_additional_properties_stay_in_the_model_schema():
    model = json_schema_to_model(
        {"type": "object", "properties": {"a": {"type": "string"}}, "additionalProperties": True}
    )
    assert model.model_json_schema()["additionalProperties"] is True


def test_additional_properties_false_stays_in_the_model_schema_at_every_level():
    model = json_schema_to_model(
        {
            "type": "object",
            "properties": {
                "n": {"type": "object", "properties": {"x": {"type": "string"}}, "additionalProperties": False}
            },
            "additionalProperties": False,
        }
    )
    schema = model.model_json_schema()
    assert schema["additionalProperties"] is False
    assert schema["$defs"]["N"]["additionalProperties"] is False


def test_one_of_with_null_in_two_members_is_refused():
    schema = {
        "type": "object",
        "properties": {"a": {"oneOf": [{"type": "string", "nullable": True}, {"type": "integer", "nullable": True}]}},
    }
    with pytest.raises(UnsupportedJsonSchemaError, match="null in more than one"):
        json_schema_to_model(schema)


def test_one_of_with_null_in_one_member_works():
    model = json_schema_to_model(
        {
            "type": "object",
            "properties": {"a": {"oneOf": [{"type": "string"}, {"type": "null"}]}},
            "required": ["a"],
        }
    )
    assert model.model_validate({"a": None}).a is None


@pytest.mark.parametrize("name", ["class", "None", "True", "import"])
def test_a_recursive_definition_named_like_a_keyword_works(name):
    model = json_schema_to_model(
        {
            "type": "object",
            "properties": {"c": {"$ref": f"#/$defs/{name}"}},
            "$defs": {
                name: {
                    "type": "object",
                    "properties": {"next": {"$ref": f"#/$defs/{name}"}, "v": {"type": "string"}},
                }
            },
        }
    )
    assert model.model_validate({"c": {"next": {"v": "x"}}}).c.next.v == "x"
    with pytest.raises(ValidationError):
        model.model_validate({"c": {"next": {"v": 1}}})


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "object", "properties": {"Config": {"type": "string"}}},
        {"type": "object", "properties": {"a": {"type": {"x": 1}}}},
        {"type": "object", "properties": {"a": {"type": "string"}}, "required": [["a"]]},
    ],
    ids=["pydantic-reserved-name", "unhashable-type", "unhashable-required"],
)
def test_any_build_failure_is_a_refusal(schema):
    with pytest.raises(UnsupportedJsonSchemaError):
        json_schema_to_model(schema)
    config = {"output_schema": json_schema_response_format(schema)}
    rehydrate_inline_output_schema(config, component_label="Agent 'a'")
    assert isinstance(config["output_schema"], dict)


@pytest.mark.parametrize(
    "ref, name",
    [("#/$defs/a~1b", "a/b"), ("#/$defs/a~0b", "a~b"), ("#/$defs/a~01b", "a~1b"), ("#/$defs/a%20b", "a b")],
)
def test_ref_tokens_are_decoded(ref, name):
    model = json_schema_to_model(
        {"type": "object", "properties": {"a": {"$ref": ref}}, "$defs": {name: {"type": "string"}}, "required": ["a"]}
    )
    assert model.model_validate({"a": "x"}).a == "x"
    with pytest.raises(ValidationError):
        model.model_validate({"a": 1})


def test_a_percent_encoded_slash_separates_tokens_and_is_refused_as_a_nested_pointer():
    schema = {
        "type": "object",
        "properties": {"a": {"$ref": "#/$defs/a%2Fb"}},
        "$defs": {"a/b": {"type": "string"}, "a": {"b": {"type": "integer"}}},
    }
    with pytest.raises(UnsupportedJsonSchemaError, match="only local refs"):
        json_schema_to_model(schema)


def test_a_percent_encoded_defs_keyword_resolves():
    model = json_schema_to_model(
        {
            "type": "object",
            "properties": {"a": {"$ref": "#/%24defs/s"}},
            "$defs": {"s": {"type": "string"}},
            "required": ["a"],
        }
    )
    assert model.model_validate({"a": "x"}).a == "x"


@pytest.mark.parametrize("ref", ["%23/$defs/s", "#/$defs/", "#/$defs", "#", "/$defs/s"])
def test_refs_that_are_not_fragments_into_defs_are_refused(ref):
    schema = {"type": "object", "properties": {"a": {"$ref": ref}}, "$defs": {"s": {"type": "string"}}}
    with pytest.raises(UnsupportedJsonSchemaError, match="only local refs"):
        json_schema_to_model(schema)


def test_an_escaped_ref_never_selects_the_literally_named_definition():
    model = json_schema_to_model(
        {
            "type": "object",
            "properties": {"a": {"$ref": "#/$defs/a~1b"}},
            "$defs": {"a/b": {"type": "string"}, "a~1b": {"type": "integer"}},
            "required": ["a"],
        }
    )
    assert model.model_validate({"a": "x"}).a == "x"
    with pytest.raises(ValidationError):
        model.model_validate({"a": 1})


@pytest.mark.parametrize("field", [{"type": "integer", "enum": [1.0]}, {"type": "integer", "const": 1.0}])
def test_an_integral_float_literal_matches_an_integer(field):
    model = json_schema_to_model({"type": "object", "properties": {"a": field}, "required": ["a"]})
    assert model.model_validate({"a": 1}).a == 1
    with pytest.raises(ValidationError):
        model.model_validate({"a": 2})


def test_a_fractional_literal_still_fails_an_integer_type():
    with pytest.raises(UnsupportedJsonSchemaError, match="do not match type"):
        json_schema_to_model({"type": "object", "properties": {"a": {"type": "integer", "enum": [1.5]}}})


def test_enum_with_a_matching_type_is_allowed():
    model = json_schema_to_model(
        {"type": "object", "properties": {"p": {"type": "string", "enum": ["a", "b"]}}, "required": ["p"]}
    )
    with pytest.raises(ValidationError):
        model.model_validate({"p": "c"})


def test_enum_over_a_type_list_accepts_each_listed_type():
    model = json_schema_to_model(
        {"type": "object", "properties": {"p": {"type": ["integer", "null"], "enum": [1, 2, None]}}, "required": ["p"]}
    )
    assert model.model_validate({"p": None}).p is None


def test_a_unicode_class_pattern_still_works():
    model = json_schema_to_model(
        {"type": "object", "properties": {"s": {"type": "string", "pattern": "^\\p{L}+$"}}, "required": ["s"]}
    )
    assert model.model_validate({"s": "Zoë"}).s == "Zoë"
    with pytest.raises(ValidationError):
        model.model_validate({"s": "a1"})


@pytest.mark.parametrize(
    "definition, value",
    [
        ({"type": ["object", "null"], "properties": {"a": {"type": "string"}}}, None),
        ({"type": ["object", "string"], "properties": {"a": {"type": "string"}}}, "x"),
        ({"type": "object", "nullable": True, "properties": {"a": {"type": "string"}}}, None),
    ],
    ids=["type-list-null", "type-list-string", "nullable"],
)
def test_a_ref_keeps_the_definitions_other_types(definition, value):
    model = json_schema_to_model(
        {
            "type": "object",
            "properties": {"v": {"$ref": "#/$defs/T"}},
            "required": ["v"],
            "$defs": {"T": definition},
        }
    )
    assert model.model_validate({"v": value}).v == value
    assert model.model_validate({"v": {"a": "x"}}).v.a == "x"


def test_a_recursive_nullable_ref_keeps_null():
    model = json_schema_to_model(
        {
            "type": "object",
            "properties": {"node": {"$ref": "#/$defs/Node"}},
            "required": ["node"],
            "$defs": {
                "Node": {
                    "type": ["object", "null"],
                    "properties": {"next": {"$ref": "#/$defs/Node"}},
                    "required": ["next"],
                }
            },
        }
    )
    parsed = model.model_validate({"node": {"next": {"next": None}}})
    assert parsed.node.next.next is None


def test_a_root_ref_with_defs_still_works():
    model = json_schema_to_model(
        {
            "$ref": "#/$defs/T",
            "description": "the output",
            "$defs": {"T": {"type": "object", "properties": {"v": {"type": "string"}}, "required": ["v"]}},
        }
    )
    assert model.model_validate({"v": "x"}).v == "x"


def test_optional_property_gets_its_default():
    model = json_schema_to_model(
        {"type": "object", "properties": {"a": {"type": "string", "default": "x", "description": "doc"}}}
    )
    assert model.model_validate({}).a == "x"
    assert model.model_json_schema()["properties"]["a"]["description"] == "doc"


def test_property_names_that_are_not_identifiers_work_without_warnings():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        model = json_schema_to_model(
            {"type": "object", "properties": {"due-date": {"type": "string"}, "schema": {"type": "string"}}}
        )
    assert model.model_validate({"due-date": "a", "schema": "b"}).model_dump() == {"due-date": "a", "schema": "b"}


def test_oneof_over_distinct_types_is_a_union():
    model = json_schema_to_model(
        {"type": "object", "properties": {"v": {"oneOf": [{"type": "string"}, {"type": "integer"}]}}, "required": ["v"]}
    )
    assert model.model_validate({"v": 3}).v == 3


def test_an_object_without_declared_properties_is_a_map():
    model = json_schema_to_model(
        {
            "type": "object",
            "properties": {"bag": {"type": "object", "properties": {}, "additionalProperties": True}},
            "required": ["bag"],
        }
    )
    assert model.model_validate({"bag": {"k": "v"}}).model_dump() == {"bag": {"k": "v"}}


def test_undeclared_keys_are_kept_unless_forbidden():
    model = json_schema_to_model({"type": "object", "properties": {"a": {"type": "string"}}})
    assert model.model_validate({"a": "x", "extra": 1}).model_dump() == {"a": "x", "extra": 1}


def test_ref_with_a_description_or_nullable_keeps_both():
    model = json_schema_to_model(
        {
            "type": "object",
            "properties": {"s": {"$ref": "#/$defs/T", "description": "d", "nullable": True}},
            "required": ["s"],
            "$defs": {"T": {"type": "string"}},
        }
    )
    assert model.model_json_schema()["properties"]["s"]["description"] == "d"
    assert model.model_validate({"s": None}).s is None


def test_additional_properties_false_forbids_extra_keys():
    model = json_schema_to_model(
        {"type": "object", "properties": {"a": {"type": "string"}}, "additionalProperties": False}
    )
    with pytest.raises(ValidationError):
        model.model_validate({"a": "x", "b": "y"})


@pytest.mark.parametrize(
    "schema, reason",
    [
        ({"type": "array", "items": {}}, "root must be an object"),
        ({"type": "object", "properties": {"a": {"allOf": [{"type": "string"}, {"maxLength": 2}]}}}, "allOf"),
        ({"type": "object", "properties": {"a": {"not": {"type": "string"}}}}, "unsupported keyword(s): not"),
        ({"type": "object", "properties": {"a": {"type": "object", "patternProperties": {}}}}, "patternProperties"),
        (
            {
                "type": "object",
                "properties": {"a": {"oneOf": [{"type": "string"}, {"type": "string", "maxLength": 2}]}},
            },
            "cannot overlap",
        ),
        ({"type": "object", "properties": {"a": {"type": "string"}}, "required": ["b"]}, "required lists"),
        (
            {
                "type": "object",
                "properties": {"a": {"type": "string"}},
                "additionalProperties": {"type": "string"},
            },
            "schema-valued additionalProperties",
        ),
        ({"type": "object", "properties": {"a": {"$ref": "https://x/schema.json"}}}, "only local refs"),
        ({"type": "object", "properties": {"a": {"$ref": "#/$defs/Missing"}}}, "does not resolve"),
        ({"type": "object", "properties": {"a": {"type": "array", "items": [{"type": "string"}]}}}, "tuple-style"),
        ({"type": "object", "properties": {"_a": {"type": "string"}}}, "property names"),
        ({"type": "object", "properties": {"model_dump": {"type": "string"}}}, "property names"),
        ({"type": "object", "properties": {"a": {"enum": [{"x": 1}]}}}, "enum and const values"),
        ({"type": "object", "properties": {"a": {"type": "integer", "maxLength": 3}}}, "needs type string"),
        ({"type": "object", "properties": {"a": {"type": "strin"}}}, "unknown type 'strin'"),
        (
            {
                "type": "object",
                "properties": {"s": {"$ref": "#/$defs/T", "enum": ["ok"]}},
                "$defs": {"T": {"type": "string"}},
            },
            "$ref cannot be combined with enum",
        ),
        (
            {"type": "object", "properties": {"n": {"oneOf": [{"type": "number"}, {"type": "integer"}]}}},
            "cannot overlap",
        ),
        ({"type": "object", "properties": {}}, "root must be an object"),
        (
            {
                "type": "object",
                "properties": {"v": {"type": "integer"}},
                "required": ["v"],
                "anyOf": [{"properties": {"v": {"minimum": 5}}}],
            },
            "anyOf cannot be combined with properties",
        ),
        (
            {"type": "object", "properties": {"s": {"allOf": [{"type": "string"}], "enum": ["ok"]}}},
            "allOf cannot be combined with enum",
        ),
        (
            {"type": "object", "properties": {"s": {"type": "string", "properties": {"a": {}}}}},
            "need type object",
        ),
        ({"type": "object", "properties": {"s": {"type": "string", "items": {}}}}, "items needs type array"),
        ({"type": "object", "properties": {"p": {"type": "integer", "enum": [1, "bad"]}}}, "do not match type"),
        ({"type": "object", "properties": {"p": {"type": "integer", "enum": [True]}}}, "do not match type"),
        ({"type": "object", "properties": {"p": {"type": "string", "const": 3}}}, "do not match type"),
        (
            {
                "type": "object",
                "properties": {"m": {"type": "object", "required": ["key"], "additionalProperties": True}},
            },
            "required needs the keys declared",
        ),
        (
            {
                "type": "object",
                "properties": {"m": {"type": "object", "required": ["k"], "additionalProperties": {"type": "string"}}},
            },
            "required needs the keys declared",
        ),
        (
            {"type": "object", "properties": {"s": {"type": "string", "pattern": "(?=a)a"}}},
            "at properties/s: pattern '(?=a)a' is not supported",
        ),
        ({"type": "object", "properties": {"s": {"type": "string", "pattern": "["}}}, "is not supported by the regex"),
        ({"type": ["object", "null"], "properties": {"a": {"type": "string"}}}, "not null or another type"),
        (
            {
                "type": "object",
                "properties": {"v": {"$ref": "#/$defs/T"}},
                "$defs": {"T": {"type": ["object", "array"], "properties": {"a": {}}, "items": {}}},
            },
            "only also allow primitive types",
        ),
        (
            {
                "type": "object",
                "$ref": "#/$defs/T",
                "required": ["v"],
                "$defs": {"T": {"type": "object", "properties": {"v": {"type": "string"}}}},
            },
            "$ref cannot be combined with required, type",
        ),
    ],
    ids=[
        "array-root",
        "allOf",
        "not",
        "patternProperties",
        "oneOf-overlapping",
        "required-missing",
        "properties-and-map",
        "remote-ref",
        "missing-ref",
        "tuple-items",
        "underscore-name",
        "model-prefix-name",
        "object-enum",
        "constraint-wrong-type",
        "unknown-type",
        "ref-with-enum",
        "oneOf-number-integer",
        "root-without-properties",
        "root-composition",
        "allOf-with-enum",
        "object-keywords-on-string",
        "items-on-string",
        "enum-outside-type",
        "enum-bool-as-integer",
        "const-outside-type",
        "map-with-required",
        "typed-map-with-required",
        "lookahead-pattern",
        "invalid-pattern",
        "nullable-root",
        "ref-object-or-array",
        "root-ref-with-required",
    ],
)
def test_unrepresentable_schemas_are_refused(schema, reason):
    with pytest.raises(UnsupportedJsonSchemaError, match=re.escape(reason)):
        json_schema_to_model(schema)


def test_refusals_name_where_they_happened():
    with pytest.raises(UnsupportedJsonSchemaError, match="at properties/outer/properties/inner"):
        json_schema_to_model(
            {
                "type": "object",
                "properties": {"outer": {"type": "object", "properties": {"inner": {"not": {}}}}},
            }
        )


def test_serialize_writes_back_the_source_dict(ticket):
    class Plain(BaseModel):
        a: str

    wrapped = json_schema_response_format(TICKET, name="Ticket")
    assert serialize_output_schema(ticket) == wrapped
    assert source_json_schema(ticket) == wrapped
    assert serialize_output_schema(Plain) == "Plain"
    assert source_json_schema(Plain) is None
    assert serialize_output_schema({"type": "json_object"}) == {"type": "json_object"}


@pytest.mark.parametrize("owner", ["agent", "team"])
def test_a_built_model_survives_a_save_and_load(ticket, owner):
    from agno.agent import Agent
    from agno.models.openai import OpenAIResponses
    from agno.registry import Registry
    from agno.team import Team

    model = OpenAIResponses(id="gpt-5.6-luna")
    if owner == "agent":
        original = Agent(id="a", model=model, output_schema=ticket)
        loaded = Agent.from_dict(original.to_dict(), registry=Registry())
    else:
        member = Agent(id="m", model=model)
        original = Team(id="t", model=model, members=[member], output_schema=ticket)
        loaded = Team.from_dict(original.to_dict(), registry=Registry())

    assert issubclass(loaded.output_schema, BaseModel)
    assert loaded.output_schema.model_validate(VALID).owner.manager.name == "Bo"
    assert serialize_output_schema(loaded.output_schema) == serialize_output_schema(ticket)


def test_rehydrate_replaces_a_stored_response_format_and_keeps_it_for_saving():
    stored = json_schema_response_format(TICKET, name="Ticket", strict=True)
    config = {"output_schema": stored}
    rehydrate_inline_output_schema(config, component_label="Agent 'a'")

    model = config["output_schema"]
    assert issubclass(model, BaseModel)
    assert serialize_output_schema(model) == stored


def test_rehydrate_leaves_provider_specific_dicts_alone():
    config = {"output_schema": {"type": "json_object"}}
    rehydrate_inline_output_schema(config, component_label="Agent 'a'")
    assert config["output_schema"] == {"type": "json_object"}


def test_rehydrate_keeps_the_dict_of_an_unsupported_schema():
    bad = json_schema_response_format({"type": "object", "properties": {"a": {"not": {}}}})
    config = {"output_schema": bad}
    rehydrate_inline_output_schema(config, component_label="Agent 'a'")
    assert config["output_schema"] == bad


def test_a_saved_agent_keeps_a_schema_the_converter_refuses():
    stored = json_schema_response_format(
        {"type": "object", "properties": {"t": {"type": "array", "items": {"type": "string"}, "uniqueItems": True}}}
    )
    loaded = Agent.from_dict(Agent(id="a", output_schema=stored).to_dict())
    assert loaded.output_schema == stored
    assert Agent.from_dict(loaded.to_dict()).output_schema == stored


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "object", "properties": {"a": {"type": "string"}}, "minProperties": 1},
        {"type": "object", "properties": {"a": {"type": "integer", "default": "x"}}},
        {
            "type": "object",
            "properties": {
                "a": {"oneOf": [{"type": "string", "nullable": True}, {"type": "integer", "nullable": True}]}
            },
        },
    ],
    ids=["unsupported-keyword", "bad-default", "one-of-nulls"],
)
def test_a_strict_load_keeps_a_schema_the_converter_refuses(schema):
    stored = json_schema_response_format(schema)
    assert Agent.from_dict(Agent(id="a", output_schema=stored).to_dict(), strict=True).output_schema == stored
    team = Team(id="t", members=[], output_schema=stored)
    assert Team.from_dict(team.to_dict(), strict=True).output_schema == stored


STRICTLESS = {"type": "object", "properties": {"a": {"type": "string"}, "b": {"type": "string"}}, "required": ["a"]}


def _loaded_schema(strict):
    stored = json_schema_response_format(STRICTLESS, name="S", strict=strict)
    return Agent.from_dict({"id": "x", "output_schema": stored}).output_schema


def test_a_stored_strict_false_reaches_openai_responses_as_written():
    params = OpenAIResponses(id="gpt-5.6-luna").get_request_params(response_format=_loaded_schema(False))
    sent = params["text"]["format"]
    assert (sent["name"], sent["strict"], sent["schema"]) == ("S", False, STRICTLESS)


def test_a_stored_strict_false_reaches_openai_chat_as_written():
    params = OpenAIChat(id="gpt-5.6-luna").get_request_params(response_format=_loaded_schema(False))
    sent = params["response_format"]["json_schema"]
    assert (sent["name"], sent["strict"], sent["schema"]) == ("S", False, STRICTLESS)


@pytest.mark.parametrize("strict", [True, None])
def test_only_a_stored_strict_false_leaves_the_pydantic_path(strict):
    sent = OpenAIResponses(id="gpt-5.6-luna").get_request_params(response_format=_loaded_schema(strict))["text"][
        "format"
    ]
    assert sent["strict"] is True
    assert set(sent["schema"]["required"]) == {"a", "b"}


def test_a_stored_strict_false_still_parses_as_a_model():
    assert _loaded_schema(False).model_validate({"a": "x"}).a == "x"


def test_claude_falls_back_on_a_mixed_enum():
    model = json_schema_to_model(
        {
            "type": "object",
            "properties": {
                "a": {"enum": [1, "x"]},
                "n": {"type": "object", "properties": {"x": {"type": "string"}}},
            },
            "required": ["a"],
        }
    )
    schema = Claude()._build_output_format(model)["schema"]
    assert schema["additionalProperties"] is False
    assert schema["$defs"]["N"]["additionalProperties"] is False
    assert schema["properties"]["a"]["enum"] == [1, "x"]


@pytest.mark.parametrize(
    "properties, path",
    [
        ({"a": {}}, "properties/a"),
        ({"a": {"type": "array", "items": {}}}, "properties/a/items"),
        ({"a": {"type": "object", "properties": {"b": {}}}}, "$defs/A/properties/b"),
    ],
    ids=["property", "array-items", "nested-object"],
)
def test_claude_refuses_an_untyped_node_and_names_it(properties, path):
    model = json_schema_to_model({"type": "object", "properties": properties, "required": ["a"]})
    with pytest.raises(ValueError, match=re.escape(path)):
        Claude()._build_output_format(model)


def test_claude_refuses_an_optional_any_field():
    class Loose(BaseModel):
        a: Optional[Any] = None

    with pytest.raises(ValueError, match="properties/a"):
        Claude()._build_output_format(Loose)


def test_claude_keeps_a_fully_typed_schema_on_the_sdk_path():
    model = json_schema_to_model({"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]})
    assert Claude()._build_output_format(model)["schema"]["properties"]["a"]["type"] == "string"
