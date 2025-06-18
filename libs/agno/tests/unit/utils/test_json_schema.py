from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel

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
    assert get_json_type_for_py_type("int") == "number"
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
    assert get_json_schema_for_arg(int) == {"type": "number"}
    assert get_json_schema_for_arg(str) == {"type": "string"}
    assert get_json_schema_for_arg(bool) == {"type": "boolean"}
    assert get_json_schema_for_arg(type(None)) == {"type": "null"}


def test_get_json_schema_for_arg_collections():
    # Test list type
    list_schema = get_json_schema_for_arg(List[str])
    assert list_schema == {"type": "array", "items": {"type": "string"}}

    # Test dict type
    dict_schema = get_json_schema_for_arg(Dict[str, int])
    assert dict_schema == {
        "type": "object",
        "propertyNames": {"type": "string"},
        "additionalProperties": {"type": "number"},
    }


def test_get_json_schema_for_arg_union():
    # Test Optional type (Union with None)
    optional_schema = get_json_schema_for_arg(Optional[str])
    assert optional_schema == {"anyOf": [{"type": "string"}, {"type": "null"}]}

    # Test Union type
    union_schema = get_json_schema_for_arg(Union[str, int])
    assert "anyOf" in union_schema
    assert len(union_schema["anyOf"]) == 2


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
    assert schema["properties"]["age"]["type"] == "number"
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
    assert user_schema["properties"]["age"]["type"] == "number"
    assert user_schema["properties"]["is_active"]["type"] == "boolean"
    assert user_schema["properties"]["tags"]["type"] == "array"


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
    assert schema["properties"]["optional_field"]["type"] == "number"


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
