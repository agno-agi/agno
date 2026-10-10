"""Tool configuration must survive saving an agent before its model is selected."""

import json

import pytest

from agno.agent import Agent
from agno.agent._tools import parse_tools
from agno.models.openai import OpenAIChat
from agno.registry import Registry
from agno.run import RunContext
from agno.tools import Function, Toolkit, tool
from agno.tools.function import FunctionCall


def echo(text: str) -> str:
    """Return the supplied text."""
    return text


async def async_echo(text: str) -> str:
    """Return the supplied text asynchronously."""
    return text


@pytest.mark.parametrize("with_model", [False, True], ids=["no-model", "explicit-model"])
@pytest.mark.parametrize("kind", ["callable", "async-callable", "function", "decorated", "toolkit", "builtin"])
def test_to_dict_preserves_tools(with_model, kind):
    model = OpenAIChat() if with_model else None
    if kind == "callable":
        configured_tool = echo
    elif kind == "async-callable":
        configured_tool = async_echo
    elif kind == "function":
        configured_tool = Function.from_callable(echo)
    elif kind == "decorated":
        configured_tool = tool(requires_confirmation=True, strict=True)(echo)
    elif kind == "toolkit":
        configured_tool = Toolkit(name="echo_tools", tools=[echo])
    else:
        configured_tool = {"type": "web_search_preview", "search_context_size": "low"}

    agent = Agent(tools=[configured_tool], model=model)
    config = agent.to_dict()

    assert agent.model is model
    assert ("model" in config) is with_model
    assert len(config["tools"]) == 1
    serialized = config["tools"][0]
    if kind == "builtin":
        assert serialized == configured_tool
    else:
        assert serialized["name"] == ("async_echo" if kind == "async-callable" else "echo")
        assert serialized["parameters"]["properties"]["text"]["type"] == "string"
        assert serialized["description"]
        if kind == "toolkit":
            assert serialized["toolkit"] == "echo_tools"
        if kind == "decorated":
            assert serialized["requires_confirmation"] is True
            assert serialized["strict"] is True
    assert json.loads(json.dumps(config))["tools"] == config["tools"]


@pytest.mark.parametrize("toolkit_first", [False, True])
def test_to_dict_without_model_keeps_first_duplicate_and_its_owner(toolkit_first):
    toolkit = Toolkit(name="echo_tools", tools=[echo])
    tools = [toolkit, echo] if toolkit_first else [echo, toolkit]
    agent = Agent(tools=tools)

    serialized_tools = agent.to_dict()["tools"]

    assert len(serialized_tools) == 1
    assert serialized_tools[0]["name"] == "echo"
    assert serialized_tools[0].get("toolkit") == ("echo_tools" if toolkit_first else None)


@pytest.mark.parametrize("async_tool", [False, True])
async def test_round_trip_without_model_preserves_executable_tool(async_tool):
    entrypoint = async_echo if async_tool else echo
    configured_tool = entrypoint if async_tool else Toolkit(name="echo_tools", tools=[entrypoint])
    agent = Agent(id="unconfigured-model", tools=[configured_tool])
    registry = Registry(tools=[configured_tool])

    config = agent.to_dict()
    restored = Agent.from_dict(json.loads(json.dumps(config)), registry=registry, strict=True)

    assert restored.model is None
    assert len(restored.tools) == 1
    restored_tool = restored.tools[0]
    assert isinstance(restored_tool, Function)
    call = FunctionCall(function=restored_tool, arguments={"text": "preserved"})
    result = await call.aexecute() if async_tool else call.execute()
    assert result.result == "preserved"
    resaved_tool = restored.to_dict()["tools"][0]
    assert resaved_tool["name"] == entrypoint.__name__
    assert resaved_tool["parameters"]["properties"] == config["tools"][0]["parameters"]["properties"]
    assert resaved_tool.get("toolkit") == (None if async_tool else "echo_tools")


def test_to_dict_without_model_does_not_resolve_tool_factory():
    def tool_factory():
        raise AssertionError("Serializing configuration must not call the tool factory")

    agent = Agent(tools=tool_factory)

    assert "tools" not in agent.to_dict()
    assert agent.model is None


@pytest.mark.parametrize("with_model", [False, True], ids=["no-model", "native-structured-output-model"])
def test_parse_tools_with_output_schema_only_infers_strictness_from_a_model(with_model):
    model = OpenAIChat() if with_model else None
    agent = Agent(tools=[echo], model=model)
    run_context = RunContext(run_id="run", session_id="session", output_schema={"type": "object"})

    parsed = parse_tools(agent, tools=agent.tools, model=model, run_context=run_context)

    assert len(parsed) == 1
    assert parsed[0].name == "echo"
    assert bool(parsed[0].strict) is with_model
