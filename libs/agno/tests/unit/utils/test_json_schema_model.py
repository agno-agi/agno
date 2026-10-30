"""json_schema_to_model builds a Pydantic model that keeps what the JSON Schema says, or refuses."""

import re
import warnings

import pytest
from pydantic import BaseModel, ValidationError

from agno.exceptions import ComponentRehydrationError
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


def test_an_optional_property_may_be_absent_but_not_null():
    model = json_schema_to_model({"type": "object", "properties": {"name": {"type": "string"}}})
    assert model.model_json_schema()["properties"]["name"] == {"title": "Name", "type": "string"}
    assert model.model_validate({}).name is None
    with pytest.raises(ValidationError):
        model.model_validate({"name": None})


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
        ({"type": "object", "properties": {"model_name": {"type": "string"}}}, "property names"),
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
    rehydrate_inline_output_schema(config, strict=True, component_label="Agent 'a'")

    model = config["output_schema"]
    assert issubclass(model, BaseModel)
    assert serialize_output_schema(model) == stored


def test_rehydrate_leaves_provider_specific_dicts_alone():
    config = {"output_schema": {"type": "json_object"}}
    rehydrate_inline_output_schema(config, strict=True, component_label="Agent 'a'")
    assert config["output_schema"] == {"type": "json_object"}


def test_rehydrate_unsupported_schema_raises_when_strict_and_drops_it_otherwise():
    bad = json_schema_response_format({"type": "object", "properties": {"a": {"not": {}}}})
    with pytest.raises(ComponentRehydrationError, match="cannot be loaded"):
        rehydrate_inline_output_schema({"output_schema": bad}, strict=True, component_label="Agent 'a'")

    config = {"output_schema": bad}
    rehydrate_inline_output_schema(config, strict=False, component_label="Agent 'a'")
    assert "output_schema" not in config
