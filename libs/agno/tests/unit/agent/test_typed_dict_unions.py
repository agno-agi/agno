import sys
from typing import TypedDict, Union

import pytest

from agno.utils.agent import validate_input


@pytest.fixture(params=["typing", "pep604"])
def union_style(request):
    if request.param == "pep604" and sys.version_info < (3, 10):
        pytest.skip("PEP 604 unions require Python 3.10+")
    return request.param


@pytest.fixture(params=[False, True], ids=["list-first", "list-last"])
def reverse_members(request):
    return request.param


@pytest.fixture(params=[False, True], ids=["integer", "nullable"])
def nullable(request):
    return request.param


@pytest.fixture
def union_input_schema(union_style, reverse_members, nullable):
    members = (list[str], type(None) if nullable else int)
    if reverse_members:
        members = members[::-1]
    annotation = Union[members] if union_style == "typing" else members[0] | members[1]
    return TypedDict("UnionInput", {"values": annotation})


@pytest.mark.parametrize("value", [[], ["first", "second"]])
def test_typed_dict_union_accepts_valid_lists(union_input_schema, value):
    data = {"values": value}
    assert validate_input(data, union_input_schema) == data


def test_typed_dict_union_accepts_other_member(union_input_schema, nullable):
    data = {"values": None if nullable else 7}
    assert validate_input(data, union_input_schema) == data


@pytest.mark.parametrize("value", [["valid", 7], {"value": "valid"}, 3.14, "not a list"])
def test_typed_dict_union_rejects_invalid_values(union_input_schema, value):
    """Parameterized members must be checked recursively for both union spellings."""
    with pytest.raises(ValueError, match="Field 'values' expected type"):
        validate_input({"values": value}, union_input_schema)


def test_typed_dict_union_rejects_absent_member(union_input_schema, nullable):
    with pytest.raises(ValueError, match="Field 'values' expected type"):
        validate_input({"values": 7 if nullable else None}, union_input_schema)
