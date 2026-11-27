"""The Ollama client keeps only `type`, `items`, `description` and `enum` on a tool property."""

from agno.utils.models.ollama import flatten_nullable_any_of, format_tools_for_ollama


def test_a_nullable_any_of_becomes_a_type_list():
    schema = {"anyOf": [{"type": "integer"}, {"type": "null"}], "description": "Stored version."}

    assert flatten_nullable_any_of(schema) == {"type": ["integer", "null"], "description": "Stored version."}


def test_the_branch_keeps_its_enum_and_items():
    enum = {"anyOf": [{"type": "string", "enum": ["a", "b"]}, {"type": "null"}]}
    array = {"anyOf": [{"type": "array", "items": {"type": "string"}}, {"type": "null"}]}

    assert flatten_nullable_any_of(enum) == {"type": ["string", "null"], "enum": ["a", "b"]}
    assert flatten_nullable_any_of(array) == {"type": ["array", "null"], "items": {"type": "string"}}


def test_a_real_union_is_left_alone():
    union = {"anyOf": [{"type": "integer"}, {"type": "string"}]}
    with_null = {"anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}]}

    assert flatten_nullable_any_of(union) == union
    assert flatten_nullable_any_of(with_null) == with_null


def test_function_parameters_are_rewritten_and_the_input_is_not_mutated():
    version = {"anyOf": [{"type": "integer"}, {"type": "null"}]}
    tool = {
        "type": "function",
        "function": {
            "name": "get_component",
            "parameters": {
                "type": "object",
                "properties": {"component_id": {"type": "string"}, "version": version},
                "required": ["component_id", "version"],
            },
        },
    }
    builtin = {"type": "web_search"}

    formatted, untouched = format_tools_for_ollama([tool, builtin])

    assert formatted["function"]["parameters"]["properties"]["version"] == {"type": ["integer", "null"]}
    assert formatted["function"]["parameters"]["properties"]["component_id"] == {"type": "string"}
    assert untouched is builtin
    assert tool["function"]["parameters"]["properties"]["version"] is version
