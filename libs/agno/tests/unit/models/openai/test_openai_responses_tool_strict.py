"""How ``OpenAIResponses`` states whether a function tool is strict.

The Responses API reads a function tool sent without ``strict`` as strict. It then makes every
parameter required, optional ones included, so the model must write a value for an argument the
tool lets it leave out. A request must therefore say ``strict: False`` for every tool that did not
ask to be strict.
"""

from typing import Optional
from unittest.mock import MagicMock

from pydantic import BaseModel

from agno.agent import Agent
from agno.models.azure.openai_responses import AzureOpenAIResponses
from agno.models.openai.responses import OpenAIResponses
from agno.tools.function import Function


def get_component(component_id: str, version: Optional[int] = None) -> str:
    """Read one component.

    Args:
        component_id: The component id.
        version: Stored version. Leave out for the latest.
    """
    return component_id


def _function(strict: bool = False) -> Function:
    function = Function.from_callable(get_component, strict=strict)
    if strict:
        function.strict = True
    return function


def test_a_tool_that_did_not_ask_to_be_strict_is_sent_as_not_strict():
    model = OpenAIResponses(id="gpt-5-mini")

    (tool,) = model._format_tool_params(messages=[], tools=[_function()])

    assert tool["strict"] is False
    assert tool["parameters"]["required"] == ["component_id"], "the optional parameter stays optional"


def test_a_tool_passed_as_a_dict_is_sent_as_not_strict():
    model = OpenAIResponses(id="gpt-5-mini")

    (tool,) = model._format_tool_params(messages=[], tools=[{"type": "function", "function": _function().to_dict()}])

    assert tool["type"] == "function"
    assert tool["strict"] is False


def test_a_strict_tool_stays_strict():
    model = OpenAIResponses(id="gpt-5-mini")

    as_function, as_dict = model._format_tool_params(
        messages=[],
        tools=[_function(strict=True), {"type": "function", "function": _function(strict=True).to_dict()}],
    )

    assert as_function["strict"] is True
    assert as_dict["strict"] is True


def test_the_request_carries_the_flag_for_every_function_tool():
    model = OpenAIResponses(id="gpt-5-mini")

    params = model.get_request_params(
        messages=[], tools=[{"type": "function", "function": _function().to_dict()}, {"type": "web_search"}]
    )

    function_tool, builtin_tool = params["tools"]
    assert function_tool["strict"] is False
    assert "strict" not in builtin_tool, "only function tools take the flag"


def test_azure_sends_the_same_flag():
    model = AzureOpenAIResponses(id="gpt-5-mini", api_key="test", azure_endpoint="https://example.openai.azure.com")

    (tool,) = model._format_tool_params(messages=[], tools=[_function()])

    assert tool["strict"] is False


class _Answer(BaseModel):
    answer: str


def test_a_structured_output_run_sends_optional_parameters_as_nullable():
    """A run with an output schema makes every tool strict; an optional parameter must stay nullable.

    Strict mode requires every parameter. Sent as a plain integer, ``version`` forces the model to
    invent a value it was told to leave out.
    """
    sent = []

    def create(**kwargs):
        sent.append(kwargs)
        raise RuntimeError("stop after the request is built")

    client = MagicMock()
    client.responses.create.side_effect = create
    model = OpenAIResponses(id="gpt-5-mini", api_key="test")
    model.get_client = lambda: client  # type: ignore[method-assign]
    agent = Agent(model=model, tools=[get_component], output_schema=_Answer, telemetry=False)

    agent.run("read component c1")

    (tool,) = sent[0]["tools"]
    assert tool["strict"] is True
    assert tool["parameters"]["required"] == ["component_id", "version"]
    assert tool["parameters"]["properties"]["version"]["anyOf"] == [{"type": "integer"}, {"type": "null"}]
