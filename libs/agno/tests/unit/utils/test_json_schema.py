from copy import deepcopy
from dataclasses import dataclass, field
from typing import Annotated, Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field

from agno.utils.json_schema import (
    get_json_schema,
    get_json_schema_for_arg,
    get_json_type_for_py_type,
    inline_pydantic_schema,
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


class CatModel(BaseModel):
    kind: Literal["cat"]
    lives: int


class DogModel(BaseModel):
    kind: Literal["dog"]
    breed: str


DiscriminatedPet = Annotated[Union[CatModel, DogModel], Field(discriminator="kind")]


class PetOwnerModel(BaseModel):
    name: str
    pets: List[DiscriminatedPet]


class OpaqueSchemaMetadataModel(BaseModel):
    config: Dict[str, Any] = Field(
        default={
            "$defs": {"payload-key": "must survive"},
            "discriminator": {"mapping": {"payload-tag": "#/$defs/PayloadValue"}},
        }
    )


def _contains_key(value: Any, key: str) -> bool:
    if isinstance(value, dict):
        return key in value or any(_contains_key(item, key) for item in value.values())
    if isinstance(value, list):
        return any(_contains_key(item, key) for item in value)
    return False


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


def test_inline_pydantic_schema_inlines_discriminated_one_of_without_dangling_refs():
    raw_schema = PetOwnerModel.model_json_schema()
    original_schema = deepcopy(raw_schema)
    raw_pet_items = raw_schema["properties"]["pets"]["items"]

    assert "mapping" in raw_pet_items["discriminator"]

    schema = inline_pydantic_schema(raw_schema)

    # Inlining is side-effect free and removes every local definition/ref.
    assert raw_schema == original_schema
    assert not _contains_key(schema, "$defs")
    assert not _contains_key(schema, "$ref")

    pet_items = schema["properties"]["pets"]["items"]
    assert pet_items["discriminator"] == {"propertyName": "kind"}
    assert len(pet_items["oneOf"]) == 2
    assert {branch["properties"]["kind"]["const"] for branch in pet_items["oneOf"]} == {"cat", "dog"}


def test_get_json_schema_for_arg_inlines_discriminated_union_model():
    schema = get_json_schema_for_arg(PetOwnerModel)

    assert schema is not None
    assert not _contains_key(schema, "$defs")
    assert not _contains_key(schema, "$ref")
    pet_items = schema["properties"]["pets"]["items"]
    assert pet_items["discriminator"] == {"propertyName": "kind"}
    assert {branch["properties"]["kind"]["const"] for branch in pet_items["oneOf"]} == {"cat", "dog"}


def test_inline_pydantic_schema_preserves_opaque_model_defaults():
    raw_schema = OpaqueSchemaMetadataModel.model_json_schema()
    original_schema = deepcopy(raw_schema)

    schema = inline_pydantic_schema(raw_schema)

    assert schema["properties"]["config"]["default"] == original_schema["properties"]["config"]["default"]
    schema["properties"]["config"]["default"]["$defs"]["payload-key"] = "changed"
    assert raw_schema == original_schema


def test_inline_pydantic_schema_preserves_all_opaque_annotation_payloads():
    opaque = {
        "$defs": {"payload-key": "must survive"},
        "discriminator": {"mapping": {"payload-tag": "#/$defs/PayloadValue"}},
    }
    raw_schema = {
        "$defs": {
            "Payload": {
                "type": "object",
                "properties": {"value": {"type": "string"}},
            }
        },
        "type": "object",
        "properties": {
            "payload": {
                "$ref": "#/$defs/Payload",
                "default": deepcopy(opaque),
                "examples": [deepcopy(opaque)],
                "const": deepcopy(opaque),
                "enum": [deepcopy(opaque)],
            }
        },
    }

    schema = inline_pydantic_schema(raw_schema)
    payload_schema = schema["properties"]["payload"]

    assert payload_schema["properties"] == {"value": {"type": "string"}}
    assert payload_schema["default"] == opaque
    assert payload_schema["examples"] == [opaque]
    assert payload_schema["const"] == opaque
    assert payload_schema["enum"] == [opaque]


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
