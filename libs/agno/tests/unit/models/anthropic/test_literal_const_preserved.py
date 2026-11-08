"""
Regression test for Claude native structured output dropping single-value
Literal constraints (#11521).

Anthropic's structured output dialect has no ``const`` keyword and the SDK's
``transform_schema()`` demotes fixed values to descriptions, which silently
widens ``Literal[...]`` fields. The schema sent for native enforcement must
preserve the declared fixed values as single-value enums.
"""

from typing import Literal

from pydantic import BaseModel

from agno.models.anthropic.claude import Claude


class Invoice(BaseModel):
    kind: Literal["invoice"]
    count: Literal[3]


class Line(BaseModel):
    kind: Literal["text"]


class Doc(BaseModel):
    doc_type: Literal[7]
    lines: list[Line]


def test_build_output_format_converts_const_to_enum():
    model = Claude(id="claude-sonnet-4-5")
    schema = model._build_output_format(Invoice)

    assert schema is not None
    properties = schema["schema"]["properties"]
    assert properties["kind"] == {"type": "string", "title": "Kind", "enum": ["invoice"]}
    assert properties["count"] == {"type": "integer", "title": "Count", "enum": [3]}


def test_build_output_format_converts_nested_const():
    model = Claude(id="claude-sonnet-4-5")
    schema = model._build_output_format(Doc)

    assert schema is not None
    assert schema["schema"]["properties"]["doc_type"]["enum"] == [7]
    assert schema["schema"]["$defs"]["Line"]["properties"]["kind"]["enum"] == ["text"]


def test_build_output_format_fallback_path_converts_const():
    """The no-transform_schema fallback path must preserve fixed values too."""
    model = Claude(id="claude-sonnet-4-5")
    schema = model._build_output_format(Invoice)

    assert schema is not None
    assert "const" not in schema["schema"]["properties"]["kind"]
    assert schema["schema"]["properties"]["kind"]["enum"] == ["invoice"]
