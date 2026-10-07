import collections.abc
import datetime
import pathlib
import uuid
from dataclasses import dataclass, field
from typing import (
    AbstractSet,
    Any,
    Collection,
    Dict,
    Iterable,
    List,
    Literal,
    Mapping,
    MutableMapping,
    MutableSequence,
    MutableSet,
    Optional,
    Sequence,
    Union,
)

import pytest
from pydantic import BaseModel

from agno.tools.function import Function, FunctionCall
from agno.utils.json_schema import (
    get_json_schema,
    get_json_schema_for_arg,
    get_json_type_for_py_type,
    is_origin_union_type,
)


# Test models and dataclasses
class MockPydanticModel(BaseModel):
    name: str
    age: int
    is_active: bool = True


@dataclass
class MockDataclass:
    name: str
    age: int
    is_active: bool = True
    tags: List[str] = field(default_factory=list)


# Nested Pydantic models
class AddressModel(BaseModel):
    street: str
    city: str
    country: str
    postal_code: str


class ContactInfoModel(BaseModel):
    email: str
    phone: Optional[str] = None
    address: AddressModel


class UserProfileModel(BaseModel):
    name: str
    age: int
    contact_info: ContactInfoModel
    preferences: Dict[str, Any] = field(default_factory=dict)


# Nested dataclasses
@dataclass
class AddressDataclass:
    street: str
    city: str
    country: str
    postal_code: str


@dataclass
class ContactInfoDataclass:
    email: str
    address: AddressDataclass
    phone: Optional[str] = None


@dataclass
class UserProfileDataclass:
    name: str
    age: int
    contact_info: ContactInfoDataclass
    preferences: Dict[str, Any] = field(default_factory=dict)


# Test cases for get_json_type_for_py_type
def test_get_json_type_for_py_type():
    assert get_json_type_for_py_type("int") == "integer"
    assert get_json_type_for_py_type("float") == "number"
    assert get_json_type_for_py_type("str") == "string"
    assert get_json_type_for_py_type("bool") == "boolean"
    assert get_json_type_for_py_type("NoneType") == "null"
    assert get_json_type_for_py_type("list") == "array"
    assert get_json_type_for_py_type("dict") == "object"
    assert get_json_type_for_py_type("unknown") == "object"


# Test cases for is_origin_union_type
def test_is_origin_union_type():
    assert is_origin_union_type(Union)
    assert not is_origin_union_type(list)
    assert not is_origin_union_type(dict)


# Test cases for get_json_schema_for_arg
def test_get_json_schema_for_arg_basic_types():
    assert get_json_schema_for_arg(int) == {"type": "integer"}
    assert get_json_schema_for_arg(str) == {"type": "string"}
    assert get_json_schema_for_arg(bool) == {"type": "boolean"}
    assert get_json_schema_for_arg(type(None)) == {"type": "null"}


def test_get_json_schema_for_arg_collections():
    # Test list type
    list_schema = get_json_schema_for_arg(List[str])
    assert list_schema == {"type": "array", "items": {"type": "string"}}

    # Test Dict[str, int] - typed dict
    dict_schema = get_json_schema_for_arg(Dict[str, int])
    assert dict_schema == {
        "type": "object",
        "propertyNames": {"type": "string"},
        "additionalProperties": {"type": "integer"},
    }


def test_get_json_schema_for_arg_bare_dict():
    """Test that bare dict allows arbitrary key-value pairs (issue #7175)."""
    # Bare dict should allow any properties
    bare_dict_schema = get_json_schema_for_arg(dict)
    assert bare_dict_schema == {"type": "object", "additionalProperties": True}

    # List of bare dicts
    list_dict_schema = get_json_schema_for_arg(List[dict])
    assert list_dict_schema == {
        "type": "array",
        "items": {"type": "object", "additionalProperties": True},
    }

    # Optional[dict] should have anyOf with the correct dict schema
    optional_dict_schema = get_json_schema_for_arg(Optional[dict])
    assert "anyOf" in optional_dict_schema
    dict_variant = next(s for s in optional_dict_schema["anyOf"] if s.get("type") == "object")
    assert dict_variant.get("additionalProperties") is True

    # Union[dict, str] should have dict with correct schema
    union_dict_schema = get_json_schema_for_arg(Union[dict, str])
    assert "anyOf" in union_dict_schema
    dict_variant = next(s for s in union_dict_schema["anyOf"] if s.get("type") == "object")
    assert dict_variant.get("additionalProperties") is True

    # Lowercase generic (Python 3.9+): list[dict]
    list_dict_lower = get_json_schema_for_arg(list[dict])
    assert list_dict_lower["type"] == "array"
    assert list_dict_lower["items"].get("additionalProperties") is True


def test_get_json_schema_bare_dict_in_function():
    """Test bare dict as a function parameter generates correct schema."""
    type_hints = {"data": dict}
    param_descriptions = {"data": "Arbitrary key-value pairs"}

    schema = get_json_schema(type_hints, param_descriptions)

    assert schema["type"] == "object"
    assert "properties" in schema
    assert "data" in schema["properties"]

    data_schema = schema["properties"]["data"]
    assert data_schema["type"] == "object"
    assert data_schema["additionalProperties"] is True
    assert data_schema["description"] == "Arbitrary key-value pairs"


def test_get_json_schema_typed_dict_unchanged():
    """Ensure typed Dict[K, V] still works correctly (regression test)."""
    # Dict[str, int] should use typed additionalProperties
    typed_dict = get_json_schema_for_arg(Dict[str, int])
    assert typed_dict["type"] == "object"
    assert typed_dict["additionalProperties"] == {"type": "integer"}

    # Lowercase dict[str, int] should work the same
    typed_dict_lower = get_json_schema_for_arg(dict[str, int])
    assert typed_dict_lower["type"] == "object"
    assert typed_dict_lower["additionalProperties"] == {"type": "integer"}


def test_get_json_schema_for_arg_union():
    # Test Optional type (Union with None)
    optional_schema = get_json_schema_for_arg(Optional[str])
    assert optional_schema == {"anyOf": [{"type": "string"}, {"type": "null"}]}

    # Test Union type
    union_schema = get_json_schema_for_arg(Union[str, int])
    assert "anyOf" in union_schema
    assert len(union_schema["anyOf"]) == 2


def test_get_json_schema_for_arg_literal():
    # Test string Literal type
    string_literal_schema = get_json_schema_for_arg(Literal["create", "update", "delete"])
    assert string_literal_schema == {"type": "string", "enum": ["create", "update", "delete"]}

    # Test integer Literal type
    int_literal_schema = get_json_schema_for_arg(Literal[1, 2, 3])
    assert int_literal_schema == {"type": "integer", "enum": [1, 2, 3]}

    # Test boolean Literal type
    bool_literal_schema = get_json_schema_for_arg(Literal[True, False])
    assert bool_literal_schema == {"type": "boolean", "enum": [True, False]}

    # Test float Literal type
    float_literal_schema = get_json_schema_for_arg(Literal[1.5, 2.5, 3.5])
    assert float_literal_schema == {"type": "number", "enum": [1.5, 2.5, 3.5]}

    # Test mixed int/float Literal type - should use "number" to cover both
    mixed_numeric_schema = get_json_schema_for_arg(Literal[1, 2.5, 3])
    assert mixed_numeric_schema == {"type": "number", "enum": [1, 2.5, 3]}

    # Test single value Literal
    single_literal_schema = get_json_schema_for_arg(Literal["only_option"])
    assert single_literal_schema == {"type": "string", "enum": ["only_option"]}


# Test cases for get_json_schema
def test_get_json_schema_basic():
    type_hints = {
        "name": str,
        "age": int,
        "is_active": bool,
    }
    param_descriptions = {
        "name": "User's full name",
        "age": "User's age in years",
        "is_active": "Whether the user is active",
    }

    schema = get_json_schema(type_hints, param_descriptions)
    assert schema["type"] == "object"
    assert "properties" in schema
    assert schema["properties"]["name"]["type"] == "string"
    assert schema["properties"]["name"]["description"] == "User's full name"
    assert schema["properties"]["age"]["type"] == "integer"
    assert schema["properties"]["is_active"]["type"] == "boolean"


def test_get_json_schema_with_pydantic_model():
    type_hints = {"user": MockPydanticModel}
    schema = get_json_schema(type_hints)
    assert schema["type"] == "object"
    assert "properties" in schema
    assert "user" in schema["properties"]
    user_schema = schema["properties"]["user"]
    assert user_schema["type"] == "object"
    assert "properties" in user_schema
    print(schema)
    assert user_schema["properties"]["name"]["type"] == "string"
    assert user_schema["properties"]["age"]["type"] == "integer"
    assert user_schema["properties"]["is_active"]["type"] == "boolean"


def test_get_json_schema_with_dataclass():
    type_hints = {"user": MockDataclass}
    schema = get_json_schema(type_hints)
    assert schema["type"] == "object"
    assert "properties" in schema
    assert "user" in schema["properties"]
    user_schema = schema["properties"]["user"]
    assert user_schema["type"] == "object"
    assert "properties" in user_schema
    assert user_schema["properties"]["name"]["type"] == "string"
    assert user_schema["properties"]["age"]["type"] == "integer"
    assert user_schema["properties"]["is_active"]["type"] == "boolean"
    assert user_schema["properties"]["tags"]["type"] == "array"


def test_get_json_schema_dataclass_optional_field_without_type():
    """A dataclass field whose Optional members lack a "type" key (e.g. a mixed-type
    Literal yields {"enum": [...]}) must not crash schema generation with KeyError."""

    @dataclass
    class MixedLiteralDataclass:
        mode: Optional[Literal[1, "a"]] = None

    # Direct call previously raised KeyError: 'type'
    arg_schema = get_json_schema_for_arg(MixedLiteralDataclass)
    assert arg_schema["type"] == "object"
    assert "mode" in arg_schema["properties"]

    # And the parameter must survive instead of being silently dropped
    schema = get_json_schema({"cfg": MixedLiteralDataclass})
    assert "cfg" in schema["properties"]


def test_get_json_schema_strict():
    type_hints = {"name": str, "age": int}
    schema = get_json_schema(type_hints, strict=True)
    assert schema["additionalProperties"] is False


def test_get_json_schema_with_complex_types():
    type_hints = {
        "names": List[str],
        "scores": Dict[str, float],
        "optional_field": Optional[int],
    }
    schema = get_json_schema(type_hints)
    assert schema["properties"]["names"]["type"] == "array"
    assert schema["properties"]["names"]["items"]["type"] == "string"
    assert schema["properties"]["scores"]["type"] == "object"
    assert schema["properties"]["optional_field"]["type"] == "integer"


def test_get_json_schema_with_literal_types():
    """Test that Literal types are correctly converted to JSON schema with enum."""
    type_hints = {
        "operation": Literal["create", "update", "delete"],
        "priority": Literal[1, 2, 3],
        "enabled": Literal[True, False],
    }
    param_descriptions = {
        "operation": "The operation to perform",
        "priority": "Priority level",
        "enabled": "Whether feature is enabled",
    }

    schema = get_json_schema(type_hints, param_descriptions)

    # Check operation (string literal)
    assert schema["properties"]["operation"]["type"] == "string"
    assert schema["properties"]["operation"]["enum"] == ["create", "update", "delete"]
    assert schema["properties"]["operation"]["description"] == "The operation to perform"

    # Check priority (integer literal)
    assert schema["properties"]["priority"]["type"] == "integer"
    assert schema["properties"]["priority"]["enum"] == [1, 2, 3]

    # Check enabled (boolean literal)
    assert schema["properties"]["enabled"]["type"] == "boolean"
    assert schema["properties"]["enabled"]["enum"] == [True, False]


def test_get_json_schema_optional_literal():
    """Test that Optional[Literal[...]] is correctly unwrapped and converted."""
    schema = get_json_schema({"op": Optional[Literal["a", "b"]]})
    # get_json_schema unwraps Optional before calling get_json_schema_for_arg
    assert schema["properties"]["op"] == {"type": "string", "enum": ["a", "b"]}


# Test cases for nested structures
def test_get_json_schema_with_nested_pydantic_models():
    type_hints = {"user_profile": UserProfileModel}
    schema = get_json_schema(type_hints)

    # Verify top-level structure
    assert schema["type"] == "object"
    assert "properties" in schema
    assert "user_profile" in schema["properties"]

    user_profile = schema["properties"]["user_profile"]
    assert user_profile["type"] == "object"
    assert "properties" in user_profile

    # Verify nested structure
    assert "contact_info" in user_profile["properties"]
    contact_info = user_profile["properties"]["contact_info"]
    assert contact_info["type"] == "object"
    assert "properties" in contact_info

    # Verify address within contact_info
    assert "address" in contact_info["properties"]
    address = contact_info["properties"]["address"]
    assert address["type"] == "object"
    assert "properties" in address
    assert address["properties"]["street"]["type"] == "string"
    assert address["properties"]["city"]["type"] == "string"
    assert address["properties"]["country"]["type"] == "string"
    assert address["properties"]["postal_code"]["type"] == "string"

    # Verify optional phone field
    assert "phone" in contact_info["properties"]
    assert contact_info["required"] == ["email", "address"]

    # Verify preferences dictionary
    assert "preferences" in user_profile["properties"]
    preferences = user_profile["properties"]["preferences"]
    assert preferences["type"] == "object"
    assert "additionalProperties" in preferences


def test_get_json_schema_with_nested_dataclasses():
    type_hints = {"user_profile": UserProfileDataclass}
    schema = get_json_schema(type_hints)

    # Verify top-level structure
    assert schema["type"] == "object"
    assert "properties" in schema
    assert "user_profile" in schema["properties"]

    user_profile = schema["properties"]["user_profile"]
    assert user_profile["type"] == "object"
    assert "properties" in user_profile

    # Verify nested structure
    assert "contact_info" in user_profile["properties"]
    contact_info = user_profile["properties"]["contact_info"]
    assert contact_info["type"] == "object"
    assert "properties" in contact_info

    # Verify address within contact_info
    assert "address" in contact_info["properties"]
    address = contact_info["properties"]["address"]
    assert address["type"] == "object"
    assert "properties" in address
    assert address["properties"]["street"]["type"] == "string"
    assert address["properties"]["city"]["type"] == "string"
    assert address["properties"]["country"]["type"] == "string"
    assert address["properties"]["postal_code"]["type"] == "string"

    # Verify optional phone field
    assert "phone" in contact_info["properties"]
    assert contact_info["required"] == ["email", "address"]

    # Verify preferences dictionary
    assert "preferences" in user_profile["properties"]
    preferences = user_profile["properties"]["preferences"]
    assert preferences["type"] == "object"
    assert "additionalProperties" in preferences


def test_get_json_schema_with_mixed_nested_structures():
    @dataclass
    class MixedStructure:
        pydantic_model: UserProfileModel
        dataclass_model: UserProfileDataclass

    type_hints = {"mixed": MixedStructure}
    schema = get_json_schema(type_hints)

    # Verify top-level structure
    assert schema["type"] == "object"
    assert "properties" in schema
    assert "mixed" in schema["properties"]

    mixed = schema["properties"]["mixed"]
    assert mixed["type"] == "object"
    assert "properties" in mixed

    # Verify both nested structures are present
    assert "pydantic_model" in mixed["properties"]
    assert "dataclass_model" in mixed["properties"]

    # Verify both structures have the same schema structure
    pydantic_schema = mixed["properties"]["pydantic_model"]
    dataclass_schema = mixed["properties"]["dataclass_model"]

    assert pydantic_schema["type"] == "object"
    assert dataclass_schema["type"] == "object"
    assert "properties" in pydantic_schema
    assert "properties" in dataclass_schema

    # Verify both have contact_info and address structures
    assert "contact_info" in pydantic_schema["properties"]
    assert "contact_info" in dataclass_schema["properties"]
    assert "address" in pydantic_schema["properties"]["contact_info"]["properties"]
    assert "address" in dataclass_schema["properties"]["contact_info"]["properties"]


def test_get_json_schema_for_arg_any_is_unconstrained():
    """Any/object must not fall through to an object schema that only `{}` satisfies."""
    assert get_json_schema_for_arg(Any) == {}
    assert get_json_schema_for_arg(object) == {}

    assert get_json_schema_for_arg(Dict[str, Any]) == {
        "type": "object",
        "propertyNames": {"type": "string"},
        "additionalProperties": {},
    }
    assert get_json_schema_for_arg(List[Any]) == {"type": "array", "items": {}}

    # `{}` is a real (unconstrained) member of a union, not an absent one
    assert get_json_schema_for_arg(Union[Any, int]) == {"anyOf": [{}, {"type": "integer"}]}


def test_get_json_schema_any_parameter_is_kept():
    schema = get_json_schema({"payload": Any, "maybe": Optional[Any]}, {"payload": "Anything"})

    assert schema["properties"]["payload"] == {"description": "Anything"}
    assert schema["properties"]["maybe"] == {}


def test_get_json_schema_dataclass_any_field_stays_in_properties():
    """An Any field must not be listed in `required` while missing from `properties`."""

    @dataclass
    class Envelope:
        payload: Any
        name: str

    schema = get_json_schema_for_arg(Envelope)

    assert schema["properties"] == {"payload": {}, "name": {"type": "string"}}
    assert schema["required"] == ["payload", "name"]


@pytest.mark.parametrize(
    "hint, item_type",
    [
        (Sequence[str], "string"),
        (MutableSequence[int], "integer"),
        (Collection[float], "number"),
        (Iterable[bool], "boolean"),
        (AbstractSet[str], "string"),
        (MutableSet[int], "integer"),
        (collections.abc.Sequence[str], "string"),
    ],
)
def test_get_json_schema_for_arg_abstract_collections(hint, item_type):
    assert get_json_schema_for_arg(hint) == {"type": "array", "items": {"type": item_type}}


@pytest.mark.parametrize("hint", [Mapping[str, int], MutableMapping[str, int], collections.abc.Mapping[str, int]])
def test_get_json_schema_for_arg_abstract_mappings(hint):
    assert get_json_schema_for_arg(hint) == {
        "type": "object",
        "propertyNames": {"type": "string"},
        "additionalProperties": {"type": "integer"},
    }


def test_get_json_schema_for_arg_bare_abstract_types():
    # Same shape as their concrete counterparts (bare list / bare dict)
    assert get_json_schema_for_arg(collections.abc.Sequence) == {"type": "array"}
    assert get_json_schema_for_arg(collections.abc.Iterable) == {"type": "array"}
    assert get_json_schema_for_arg(collections.abc.Mapping) == {"type": "object", "additionalProperties": True}
    assert get_json_schema_for_arg(collections.abc.MutableMapping) == {"type": "object", "additionalProperties": True}


def test_get_json_schema_for_arg_string_serialized_types():
    # Only date-time carries a `format`; the rest stay plain strings
    assert get_json_schema_for_arg(datetime.datetime) == {"type": "string", "format": "date-time"}
    assert get_json_schema_for_arg(datetime.date) == {"type": "string"}
    assert get_json_schema_for_arg(datetime.time) == {"type": "string"}
    assert get_json_schema_for_arg(uuid.UUID) == {"type": "string"}
    assert get_json_schema_for_arg(pathlib.Path) == {"type": "string"}
    assert get_json_schema_for_arg(pathlib.PurePosixPath) == {"type": "string"}

    assert get_json_schema_for_arg(List[datetime.datetime]) == {
        "type": "array",
        "items": {"type": "string", "format": "date-time"},
    }
    assert get_json_schema({"day": Optional[datetime.date]})["properties"]["day"] == {"type": "string"}


def test_function_from_callable_round_trips_abstract_and_string_types():
    """The generated schema and the call path agree: model-side JSON in, typed Python values out."""

    def book(
        day: datetime.date,
        at: datetime.datetime,
        ref: uuid.UUID,
        tags: Sequence[str],
        meta: Mapping[str, Any],
    ) -> str:
        """Book a slot.

        Args:
            day: The day.
            at: The start.
            ref: Reference id.
            tags: Tags.
            meta: Free-form metadata.
        """
        assert isinstance(day, datetime.date) and not isinstance(day, datetime.datetime)
        assert isinstance(at, datetime.datetime)
        assert isinstance(ref, uuid.UUID)
        return f"{list(tags)} {dict(meta)}"

    function = Function.from_callable(book)
    properties = function.parameters["properties"]

    assert properties["tags"]["type"] == "array"
    assert properties["meta"]["type"] == "object"
    assert properties["meta"]["additionalProperties"] == {}
    assert properties["day"]["type"] == "string"
    assert properties["at"]["format"] == "date-time"

    call = FunctionCall(
        function=function,
        arguments={
            "day": "2026-01-02",
            "at": "2026-01-02T03:04:05Z",
            "ref": str(uuid.uuid4()),
            "tags": ["a", "b"],
            "meta": {"k": [1, {"z": 2}]},
        },
    )
    result = call.execute()

    assert result.status == "success", result.error
    assert result.result == "['a', 'b'] {'k': [1, {'z': 2}]}"
