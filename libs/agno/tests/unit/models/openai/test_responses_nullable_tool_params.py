"""A tool parameter the schema lets be null must still allow null when sent to the Responses API.

OpenAI documents an optional parameter of a strict tool as a type union with "null" that stays in
`required`. `_format_tool_params` reduced every type list to its first entry, so `["string", "null"]`
reached the model as a required `"string"` and the model had to invent a value — against the live
API it sent `""` in 5 of 5 samples where the unchanged schema got `null` in 5 of 5.
"""

from copy import deepcopy

from agno.models.openai.responses import OpenAIResponses
from agno.tools.function import Function

PARAMETERS = {
    "type": "object",
    "additionalProperties": False,
    "required": ["status", "keyword"],
    "properties": {
        "status": {"type": "string", "enum": ["open", "closed"]},
        "keyword": {"type": ["string", "null"], "description": "Free text to match, or null when unused"},
    },
}


def _formatted(tool):
    return OpenAIResponses(id="gpt-5", api_key="test")._format_tool_params([], [tool])[0]["parameters"]


def test_nullable_parameter_stays_nullable_for_a_function():
    tool = Function(name="search_tickets", description="Search tickets", parameters=deepcopy(PARAMETERS))

    assert _formatted(tool)["properties"]["keyword"]["type"] == ["string", "null"]


def test_nullable_parameter_stays_nullable_for_a_dict_tool():
    tool = {"type": "function", "function": {"name": "search_tickets", "parameters": deepcopy(PARAMETERS)}}

    assert _formatted(tool)["properties"]["keyword"]["type"] == ["string", "null"]


def test_a_required_nullable_parameter_is_still_required():
    tool = Function(name="search_tickets", description="Search tickets", parameters=deepcopy(PARAMETERS))

    assert _formatted(tool)["required"] == ["status", "keyword"]


def test_other_type_unions_are_reduced_as_before():
    parameters = {"type": "object", "properties": {"value": {"type": ["string", "integer"]}}}
    tool = Function(name="set_value", description="Set a value", parameters=parameters)

    assert _formatted(tool)["properties"]["value"]["type"] == "string"
