"""The Ollama client keeps only `type`, `items`, `description` and `enum` on a tool property.

Before 0.4.8 its `type` also had to be a single string, so a nullable property is sent as its one
non-null type.
"""

import pytest

from agno.utils.models.ollama import collapse_nullable_any_of, format_tools_for_ollama


def _tool(version_schema):
    return {
        "type": "function",
        "function": {
            "name": "get_component",
            "description": "Read one component.",
            "parameters": {
                "type": "object",
                "properties": {"component_id": {"type": "string"}, "version": version_schema},
                "required": ["component_id", "version"],
            },
        },
    }


def test_a_nullable_any_of_becomes_its_non_null_type():
    schema = {"anyOf": [{"type": "integer"}, {"type": "null"}], "description": "Stored version."}

    assert collapse_nullable_any_of(schema) == {"type": "integer", "description": "Stored version."}


def test_the_branch_keeps_its_enum_and_items():
    enum = {"anyOf": [{"type": "string", "enum": ["a", "b"]}, {"type": "null"}]}
    array = {"anyOf": [{"type": "array", "items": {"type": "string"}}, {"type": "null"}]}

    assert collapse_nullable_any_of(enum) == {"type": "string", "enum": ["a", "b"]}
    assert collapse_nullable_any_of(array) == {"type": "array", "items": {"type": "string"}}


def test_a_real_union_is_left_alone():
    union = {"anyOf": [{"type": "integer"}, {"type": "string"}]}
    with_null = {"anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}]}

    assert collapse_nullable_any_of(union) == union
    assert collapse_nullable_any_of(with_null) == with_null


def test_function_parameters_are_rewritten_and_the_input_is_not_mutated():
    version = {"anyOf": [{"type": "integer"}, {"type": "null"}]}
    tool = _tool(version)
    builtin = {"type": "web_search"}

    formatted, untouched = format_tools_for_ollama([tool, builtin])

    assert formatted["function"]["parameters"]["properties"]["version"] == {"type": "integer"}
    assert formatted["function"]["parameters"]["properties"]["component_id"] == {"type": "string"}
    assert untouched is builtin
    assert tool["function"]["parameters"]["properties"]["version"] is version


def test_the_installed_ollama_client_keeps_the_parameter_type():
    """The client validates every tool before sending it; a rejected tool fails the whole run."""
    ollama_types = pytest.importorskip("ollama._types")

    (formatted,) = format_tools_for_ollama(
        [_tool({"anyOf": [{"type": "string", "enum": ["a", "b"]}, {"type": "null"}], "description": "Version."})]
    )
    validated = ollama_types.Tool.model_validate(formatted)

    # `type` and `description` are the fields every client version keeps.
    version = validated.function.parameters.properties["version"]
    assert version.type == "string"
    assert version.description == "Version."
